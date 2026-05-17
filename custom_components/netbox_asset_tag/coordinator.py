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
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN
from .exceptions import NetBoxApiError, NetBoxAuthenticationError
from .models import (
    HomeAssistantDeviceMatch,
    NetBoxInventory,
    RegistryEntry,
    normalize_identifier,
    normalize_serial,
)

_LOGGER = logging.getLogger(__name__)
_SEPARATED_IDENTIFIER_RE = re.compile(
    r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}[:-]){5,7}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"
)
_WHOLE_IDENTIFIER_RE = re.compile(r"^[0-9A-Fa-f]{12}(?:[0-9A-Fa-f]{4})?$")


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


def _match_device(
    device_entry: dr.DeviceEntry,
    inventory: NetBoxInventory,
) -> HomeAssistantDeviceMatch | None:
    """Match one Home Assistant device against the NetBox inventory."""
    candidate_identifiers = _collect_ha_identifiers(device_entry)
    if not candidate_identifiers:
        return None

    matched_device_ids = {
        inventory.identifier_to_device_id[identifier]
        for identifier in candidate_identifiers
        if identifier in inventory.identifier_to_device_id
    }
    if len(matched_device_ids) != 1:
        return None

    netbox_device_id = next(iter(matched_device_ids))
    netbox_device = inventory.devices[netbox_device_id]
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
        ha_device_name=device_entry.name_by_user or device_entry.name or device_entry.id,
        ha_identifiers=_freeze_registry_entries(device_entry.identifiers),
        ha_connections=_freeze_registry_entries(device_entry.connections),
        netbox_device_id=netbox_device.device_id,
        netbox_asset_tag=netbox_device.asset_tag,
        netbox_display=netbox_device.display,
        netbox_url=netbox_device.display_url,
        matched_identifiers=matched_identifiers,
        match_methods=match_methods,
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
            match = _match_device(device_entry, inventory)
            if match is None:
                continue
            matches[device_entry.id] = match

        return matches
