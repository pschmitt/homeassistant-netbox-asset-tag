"""Coordinator for NetBox Asset Tag."""

from __future__ import annotations

import asyncio
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
    CONF_MANUAL_OVERRIDES,
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
    freeze_registry_entries,
    get_attached_device_key,
    normalize_device_identifier,
    normalize_identifier,
    normalize_serial,
)

_LOGGER = logging.getLogger(__name__)
_SEPARATED_IDENTIFIER_PATTERNS = (
    re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"),
    re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}-){5}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"),
    re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}:){7}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"),
    re.compile(r"(?<![0-9A-Fa-f])(?:[0-9A-Fa-f]{2}-){7}[0-9A-Fa-f]{2}(?![0-9A-Fa-f])"),
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

    for pattern in _SEPARATED_IDENTIFIER_PATTERNS:
        for candidate in pattern.findall(stripped):
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


def _get_attached_device_key_for_entry(device_entry: dr.DeviceEntry) -> str:
    """Return the stable attached device key for a Home Assistant device."""
    frozen_identifiers = freeze_registry_entries(device_entry.identifiers)
    frozen_connections = freeze_registry_entries(device_entry.connections)
    return get_attached_device_key(
        frozen_identifiers,
        frozen_connections,
        device_entry.id,
    )


def _build_match(
    device_entry: dr.DeviceEntry,
    netbox_device_id: int,
    inventory: NetBoxInventory,
    *,
    matched_identifiers: tuple[str, ...],
    match_methods: tuple[str, ...],
    weak_match: bool,
    manual_override: bool,
    extra_connections: tuple[RegistryEntry, ...] = (),
) -> HomeAssistantDeviceMatch:
    """Build a match payload for one Home Assistant device."""
    netbox_device = inventory.devices[netbox_device_id]
    frozen_identifiers = freeze_registry_entries(device_entry.identifiers)
    frozen_connections = freeze_registry_entries(device_entry.connections)

    return HomeAssistantDeviceMatch(
        ha_device_id=device_entry.id,
        attached_device_key=get_attached_device_key(frozen_identifiers, frozen_connections, device_entry.id),
        ha_device_name=device_entry.name_by_user or device_entry.name or device_entry.id,
        ha_identifiers=frozen_identifiers,
        ha_connections=frozen_connections,
        extra_connections=extra_connections,
        netbox_device_id=netbox_device.device_id,
        netbox_serial=netbox_device.serial,
        netbox_asset_tag=netbox_device.asset_tag,
        netbox_display=netbox_device.display,
        netbox_url=netbox_device.display_url,
        matched_identifiers=matched_identifiers,
        match_methods=match_methods,
        weak_match=weak_match,
        manual_override=manual_override,
    )


def _collect_ha_identifiers(device_entry: dr.DeviceEntry) -> set[str]:
    """Collect normalized identifiers from one Home Assistant device."""
    identifiers: set[str] = set()
    identifiers.update(_iter_registry_entry_values(device_entry.connections))
    identifiers.update(_iter_registry_entry_values(device_entry.identifiers))
    serial_number = normalize_serial(device_entry.serial_number)
    if serial_number:
        identifiers.add(serial_number)
    return identifiers


def _collect_explicit_ha_identifiers(device_entry: dr.DeviceEntry) -> set[str]:
    """Collect exact integration-provided identifiers for generic matching."""
    identifiers: set[str] = set()
    for entry in device_entry.identifiers or ():
        if not isinstance(entry, (list, tuple)) or len(entry) < 2:
            continue
        domain = str(entry[0]).strip()
        raw_value = normalize_device_identifier(str(entry[1]))
        if not raw_value:
            continue
        identifiers.add(raw_value)
        if domain:
            identifiers.add(f"{domain}:{raw_value}")
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
        from homeassistant.components.matter.helpers import get_matter  # noqa: PLC0415
    except ImportError:
        return None

    try:
        matter = get_matter(hass)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Matter adapter not available: %s", err)
        return None

    try:
        result = await matter.matter_client.node_diagnostics(node_id)
        mac = getattr(result, "mac_address", None)
        if mac:
            return normalize_identifier(mac)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Matter node_diagnostics failed for node %d: %s", node_id, err)

    return None


def _get_cast_host(hass: HomeAssistant, cast_uuid_str: str) -> str | None:
    """Return the IP of a Cast device from the cast integration's browser state."""
    try:
        from homeassistant.components.cast import DOMAIN as CAST_DOMAIN  # noqa: PLC0415

        normalized = cast_uuid_str.replace("-", "").lower()
        for entry in hass.config_entries.async_entries(CAST_DOMAIN):
            browser = getattr(getattr(entry, "runtime_data", None), "browser", None)
            if browser is None:
                continue
            for dev_uuid, cast_info in (getattr(browser, "devices", None) or {}).items():
                if str(dev_uuid).replace("-", "").lower() == normalized:
                    host = getattr(cast_info, "host", None)
                    if host:
                        return str(host)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Cast host lookup failed: %s", err)
    return None


async def _async_mac_from_ip(ip: str) -> str | None:
    """Resolve a MAC address from an IP via the system ARP neighbour table."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ip", "neigh", "show", ip,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        for line in stdout.decode().splitlines():
            parts = line.split()
            if "lladdr" in parts:
                idx = parts.index("lladdr")
                if idx + 1 < len(parts):
                    return normalize_identifier(parts[idx + 1])
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("ARP lookup failed for %s: %s", ip, err)
    return None


async def _async_get_cast_mac(hass: HomeAssistant, cast_uuid_str: str) -> str | None:
    """Return the normalized WiFi MAC for a Cast device by ARP-resolving its IP."""
    host = _get_cast_host(hass, cast_uuid_str)
    if not host:
        _LOGGER.debug("Cast host not found for UUID %s", cast_uuid_str)
        return None
    mac = await _async_mac_from_ip(host)
    if mac:
        _LOGGER.debug("Resolved Cast UUID %s → host %s → MAC %s", cast_uuid_str, host, mac)
    else:
        _LOGGER.debug("ARP resolution failed for Cast UUID %s (host %s)", cast_uuid_str, host)
    return mac


def _match_device(
    device_entry: dr.DeviceEntry,
    inventory: NetBoxInventory,
    *,
    enable_weak_matching: bool,
    extra_identifiers: set[str] | None = None,
    extra_connections: tuple[RegistryEntry, ...] = (),
) -> HomeAssistantDeviceMatch | None:
    """Match one Home Assistant device against the NetBox inventory."""
    strong_identifiers = _collect_ha_identifiers(device_entry)
    strong_identifiers.update(_collect_explicit_ha_identifiers(device_entry))
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

    return _build_match(
        device_entry,
        netbox_device_id,
        inventory,
        matched_identifiers=matched_identifiers,
        match_methods=match_methods,
        weak_match=weak_match,
        manual_override=False,
        extra_connections=extra_connections,
    )


def _deduplicate_sibling_matches(
    matches: dict[str, HomeAssistantDeviceMatch],
    device_registry: dr.DeviceRegistry,
) -> None:
    """Remove duplicate coordinator matches for the same NetBox asset.

    When multiple HA devices (e.g., Cast + Android TV Remote for one Chromecast,
    or Hue bridge + ZHA for the same bulb) all map to the same NetBox asset, keep
    only one match so we don't create duplicate asset-tag sensor entities.

    The primary is chosen by:
      1. Most non-MAC, non-DOMAIN identifiers (richer unique ID → more stable device).
      2. Most config entries (more integrations using this device → more canonical).
      3. Tie-break: lexicographic key.
    """
    netbox_to_keys: dict[int, list[str]] = {}
    for key, match in matches.items():
        netbox_to_keys.setdefault(match.netbox_device_id, []).append(key)

    for netbox_device_id, keys in netbox_to_keys.items():
        if len(keys) <= 1:
            continue

        def _sort_key(k: str) -> tuple[int, int, str]:
            m = matches[k]
            non_mac_non_domain = sum(
                1
                for e in m.ha_identifiers
                if len(e) >= 2
                and str(e[0]) != DOMAIN
                and normalize_identifier(str(e[1])) is None
            )
            dev = device_registry.async_get(m.ha_device_id)
            cfg_count = len(dev.config_entries) if dev else 0
            return (non_mac_non_domain, cfg_count, k)

        sorted_keys = sorted(keys, key=_sort_key, reverse=True)
        primary_match = matches[sorted_keys[0]]

        for secondary_key in sorted_keys[1:]:
            secondary_match = matches.pop(secondary_key)
            _LOGGER.debug(
                "Deduplicating sibling match: keeping %s (%s), dropping %s (%s) [NetBox device %d]",
                primary_match.ha_device_name,
                primary_match.ha_device_id,
                secondary_match.ha_device_name,
                secondary_match.ha_device_id,
                netbox_device_id,
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
            config_entry=config_entry,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            update_interval=timedelta(
                seconds=config_entry.options.get(
                    CONF_SCAN_INTERVAL,
                    DEFAULT_SCAN_INTERVAL,
                )
            ),
        )
        self.client = client

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
        attached_devices: dict[str, dr.DeviceEntry] = {}

        for device_entry in device_registry.devices.values():
            attached_devices[_get_attached_device_key_for_entry(device_entry)] = device_entry
            enable_weak = self.config_entry.options.get(
                CONF_ENABLE_WEAK_MATCHING,
                DEFAULT_ENABLE_WEAK_MATCHING,
            )

            # Fast path: try matching with the identifiers/connections HA already knows.
            match = _match_device(device_entry, inventory, enable_weak_matching=enable_weak)

            if match is None:
                # Slow path: augment with ARP-resolved MACs for integrations that
                # communicate with WiFi devices but don't expose a MAC in the registry.
                # Only runs when the fast path failed, so the subprocess cost is paid
                # only for genuinely unmatched devices.
                #
                # MACs gathered here are also stored as extra_connections so that
                # entity.DeviceInfo declares them; HA's device registry then merges
                # device entries from different integrations for the same physical device
                # (e.g., Cast + Android TV Remote both representing one Chromecast).
                extra_ids: set[str] = set()
                extra_conns: list[RegistryEntry] = []

                for entry in device_entry.identifiers:
                    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                        continue
                    if entry[0] != "matter":
                        continue
                    node_id = _parse_matter_node_id(entry[1])
                    if node_id is None:
                        continue
                    mac = await _async_get_matter_mac(self.hass, node_id)
                    if mac:
                        extra_ids.add(mac)
                        extra_conns.append(("mac", mac))
                    break

                for entry in device_entry.identifiers:
                    if not isinstance(entry, (list, tuple)) or len(entry) < 2:
                        continue
                    if entry[0] != "cast":
                        continue
                    mac = await _async_get_cast_mac(self.hass, str(entry[1]))
                    if mac:
                        extra_ids.add(mac)
                        extra_conns.append(("mac", mac))
                    break

                if extra_ids:
                    match = _match_device(
                        device_entry,
                        inventory,
                        enable_weak_matching=enable_weak,
                        extra_identifiers=extra_ids,
                        extra_connections=tuple(extra_conns),
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

        for attached_device_key, netbox_device_id in (
            self.config_entry.options.get(CONF_MANUAL_OVERRIDES, {}) or {}
        ).items():
            device_entry = attached_devices.get(attached_device_key)
            if device_entry is None:
                _LOGGER.debug(
                    "Skipping manual override for missing Home Assistant device key %s",
                    attached_device_key,
                )
                continue

            try:
                resolved_netbox_device_id = int(netbox_device_id)
            except (TypeError, ValueError):
                _LOGGER.debug(
                    "Skipping manual override for Home Assistant device key %s with invalid NetBox device id %r",
                    attached_device_key,
                    netbox_device_id,
                )
                continue

            if resolved_netbox_device_id not in inventory.devices:
                _LOGGER.debug(
                    "Skipping manual override for Home Assistant device key %s because NetBox device %s was not found",
                    attached_device_key,
                    resolved_netbox_device_id,
                )
                continue

            matches[attached_device_key] = _build_match(
                device_entry,
                resolved_netbox_device_id,
                inventory,
                matched_identifiers=(),
                match_methods=("manual_override",),
                weak_match=False,
                manual_override=True,
            )

        _deduplicate_sibling_matches(matches, device_registry)
        return matches
