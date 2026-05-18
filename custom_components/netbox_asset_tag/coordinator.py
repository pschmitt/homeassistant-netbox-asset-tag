"""Coordinator for NetBox Asset Tag."""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NetBoxApiClient
from .const import (
    CONF_ENABLE_WEAK_MATCHING,
    DEFAULT_ENABLE_WEAK_MATCHING,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)
from .exceptions import NetBoxApiError, NetBoxAuthenticationError
from .models import (
    HomeAssistantDeviceMatch,
    NetBoxInventory,
    RegistryEntry,
    get_attached_device_key,
    normalize_identifier,
    normalize_serial,
)

_LOGGER = logging.getLogger(__name__)
_SEPARATED_IDENTIFIER_RE = re.compile(
    r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:-]){5,7}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"
)
_SERIAL_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,}")
_WHOLE_IDENTIFIER_RE = re.compile(r"^[0-9A-Fa-f]{12}(?:[0-9A-Fa-f]{4})?$")
_MATTER_NODE_ID_RE = re.compile(
    r"^deviceid_[0-9A-Fa-f]+-([0-9A-Fa-f]+)-MatterNodeDevice$"
)


def _extract_identifier_candidates(value: Any) -> set[str]:
    """Extract normalized MAC or EUI-like identifiers from a string."""
    if value is None:
        return set()

    stripped = str(value).strip()
    if not stripped:
        return set()

    matches: set[str] = set()

    if _WHOLE_IDENTIFIER_RE.fullmatch(stripped):
        normalized = normalize_identifier(stripped)
        if normalized:
            matches.add(normalized)

    for candidate in _SEPARATED_IDENTIFIER_RE.findall(stripped):
        normalized = normalize_identifier(candidate)
        if normalized:
            matches.add(normalized)

    return matches


def _iter_registry_entry_values(entries: Any) -> set[str]:
    """Return identifier-like values from registry entries of varying lengths."""
    values: set[str] = set()
    for entry in entries or ():
        if not isinstance(entry, (list, tuple)):
            values.update(_extract_identifier_candidates(entry))
            continue
        for value in entry[1:]:
            values.update(_extract_identifier_candidates(value))
    return values


def _iter_registry_raw_values(entries: Any) -> set[str]:
    """Return raw string values from registry entries of varying lengths."""
    values: set[str] = set()
    for entry in entries or ():
        if not isinstance(entry, (list, tuple)):
            if entry is not None:
                values.add(str(entry))
            continue
        for value in entry[1:]:
            if value is not None:
                values.add(str(value))
    return values


def _looks_like_serial_candidate(value: str) -> bool:
    """Return True when a raw value looks like a device serial."""
    normalized = normalize_serial(value)
    if normalized is None or len(normalized) < 8:
        return False
    return any(character.isalpha() for character in normalized) and any(
        character.isdigit() for character in normalized
    )


def _extract_serial_candidates(value: Any) -> set[str]:
    """Extract serial-like identifiers from raw registry values."""
    if value is None:
        return set()

    stripped = str(value).strip()
    if not stripped:
        return set()

    matches: set[str] = set()
    if _looks_like_serial_candidate(stripped):
        normalized = normalize_serial(stripped)
        if normalized:
            matches.add(normalized)

    for candidate in _SERIAL_TOKEN_RE.findall(stripped):
        if not _looks_like_serial_candidate(candidate):
            continue
        normalized = normalize_serial(candidate)
        if normalized:
            matches.add(normalized)

    return matches


def _freeze_registry_entries(entries: Any) -> tuple[RegistryEntry, ...]:
    """Return registry entries as stable string tuples."""
    frozen_entries: list[RegistryEntry] = []
    for entry in entries or ():
        if not isinstance(entry, (list, tuple)):
            continue
        frozen_entries.append(tuple(str(part) for part in entry))
    return tuple(sorted(frozen_entries, key=repr))


def _collect_ha_identifiers(device_entry: dr.DeviceEntry) -> set[str]:
    """Collect normalized identifiers from one Home Assistant device."""
    identifiers: set[str] = set()
    identifiers.update(_iter_registry_entry_values(device_entry.connections))
    identifiers.update(_iter_registry_entry_values(device_entry.identifiers))
    serial_number = normalize_serial(device_entry.serial_number)
    if serial_number:
        identifiers.add(serial_number)
    return identifiers


def _collect_weak_ha_identifiers(device_entry: dr.DeviceEntry) -> set[str]:
    """Collect weaker serial-like identifiers from raw Home Assistant values."""
    identifiers: set[str] = set()
    for value in _iter_registry_raw_values(device_entry.identifiers):
        identifiers.update(_extract_serial_candidates(value))
    return identifiers


def _parse_matter_node_id(identifier_value: str) -> int | None:
    """Parse the integer node ID from an HA Matter device identifier string."""
    match = _MATTER_NODE_ID_RE.match(identifier_value)
    if not match:
        return None
    try:
        return int(match.group(1), 16)
    except ValueError:
        return None


async def _async_get_matter_mac(hass: HomeAssistant, node_id: int) -> str | None:
    """Return the normalized Thread/WiFi MAC for a Matter node via the Matter integration."""
    try:
        from homeassistant.components.matter import DOMAIN as _MATTER_DOMAIN  # noqa: PLC0415
    except ImportError:
        return None

    matter_data = hass.data.get(_MATTER_DOMAIN)
    if not matter_data:
        return None

    for entry_data in matter_data.values():
        client = getattr(entry_data, "client", None)
        if client is None:
            continue
        try:
            result = await client.send_command("get_node_diagnostics", node_id=node_id)
            mac = (
                result.get("mac_address")
                if isinstance(result, dict)
                else getattr(result, "mac_address", None)
            )
            if mac:
                return normalize_identifier(mac)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Matter get_node_diagnostics failed for node %d", node_id)
            continue
    return None


def _match_device(
    device_entry: dr.DeviceEntry,
    inventory: NetBoxInventory,
    *,
    enable_weak_matching: bool,
    extra_identifiers: set[str] | None = None,
) -> HomeAssistantDeviceMatch | None:
    """Match one Home Assistant device against the NetBox inventory."""
    strong_identifiers = _collect_ha_identifiers(device_entry)
    if extra_identifiers:
        strong_identifiers = strong_identifiers | extra_identifiers
    weak_identifiers = set()
    if enable_weak_matching:
        weak_identifiers = _collect_weak_ha_identifiers(device_entry) - strong_identifiers

    if not strong_identifiers and not weak_identifiers:
        return None

    strong_device_ids = {
        inventory.identifier_to_device_id[identifier]
        for identifier in strong_identifiers
        if identifier in inventory.identifier_to_device_id
    }
    if len(strong_device_ids) > 1:
        return None

    if len(strong_device_ids) == 1:
        netbox_device_id = next(iter(strong_device_ids))
        weak_match = False
    else:
        weak_device_ids = {
            inventory.identifier_to_device_id[identifier]
            for identifier in weak_identifiers
            if identifier in inventory.identifier_to_device_id
        }
        if len(weak_device_ids) != 1:
            return None
        netbox_device_id = next(iter(weak_device_ids))
        weak_match = True

    netbox_device = inventory.devices[netbox_device_id]
    frozen_identifiers = _freeze_registry_entries(device_entry.identifiers)
    frozen_connections = _freeze_registry_entries(device_entry.connections)
    candidate_identifiers = strong_identifiers | weak_identifiers
    matched_identifiers = tuple(
        sorted(
            identifier
            for identifier in candidate_identifiers
            if inventory.identifier_to_device_id.get(identifier) == netbox_device_id
        )
    )
    match_methods = tuple(
        sorted(
            {
                inventory.identifier_to_match_method[identifier]
                for identifier in matched_identifiers
                if identifier in inventory.identifier_to_match_method
            }
        )
    )

    return HomeAssistantDeviceMatch(
        ha_device_id=device_entry.id,
        attached_device_key=get_attached_device_key(
            frozen_identifiers,
            frozen_connections,
            device_entry.id,
        ),
        ha_device_name=device_entry.name_by_user or device_entry.name or device_entry.id,
        ha_identifiers=frozen_identifiers,
        ha_connections=frozen_connections,
        netbox_device_id=netbox_device.device_id,
        netbox_asset_tag=netbox_device.asset_tag,
        netbox_display=netbox_device.display,
        netbox_url=netbox_device.display_url,
        matched_identifiers=matched_identifiers,
        match_methods=match_methods,
        weak_match=weak_match,
    )


class NetBoxAssetTagCoordinator(DataUpdateCoordinator[dict[str, HomeAssistantDeviceMatch]]):
    """Coordinate NetBox inventory matching against Home Assistant devices."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: NetBoxApiClient,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            update_interval=timedelta(
                seconds=config_entry.options.get(
                    CONF_SCAN_INTERVAL,
                    DEFAULT_SCAN_INTERVAL,
                )
            ),
        )
        self.client = client
        self.config_entry = config_entry

    @property
    def server_url(self) -> str:
        """Return the configured NetBox URL."""
        return self.client.base_url

    async def _async_update_data(self) -> dict[str, HomeAssistantDeviceMatch]:
        """Fetch NetBox data and match it against Home Assistant devices."""
        try:
            inventory = await self.client.async_fetch_inventory()
        except NetBoxAuthenticationError as err:
            raise ConfigEntryAuthFailed from err
        except NetBoxApiError as err:
            raise UpdateFailed(str(err)) from err

        device_registry = dr.async_get(self.hass)
        matches: dict[str, HomeAssistantDeviceMatch] = {}

        for device_entry in device_registry.devices.values():
            extra_ids: set[str] = set()
            for id_type, id_val in device_entry.identifiers:
                if id_type != "matter":
                    continue
                node_id = _parse_matter_node_id(id_val)
                if node_id is None:
                    continue
                mac = await _async_get_matter_mac(self.hass, node_id)
                if mac:
                    extra_ids.add(mac)
                break

            match = _match_device(
                device_entry,
                inventory,
                enable_weak_matching=self.config_entry.options.get(
                    CONF_ENABLE_WEAK_MATCHING,
                    DEFAULT_ENABLE_WEAK_MATCHING,
                ),
                extra_identifiers=extra_ids or None,
            )
            if match is None:
                continue
            existing_match = matches.get(match.attached_device_key)
            if existing_match is None:
                matches[match.attached_device_key] = match
                continue

            if existing_match.netbox_device_id == match.netbox_device_id:
                if len(match.matched_identifiers) > len(existing_match.matched_identifiers):
                    matches[match.attached_device_key] = match
                continue

            _LOGGER.warning(
                "Skipping conflicting NetBox matches for Home Assistant device key %s: %s vs %s",
                match.attached_device_key,
                existing_match.netbox_device_id,
                match.netbox_device_id,
            )

        return matches
