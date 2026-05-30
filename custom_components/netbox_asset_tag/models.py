"""Models for NetBox Asset Tag."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, TypeAlias

RegistryEntry: TypeAlias = tuple[str, ...]


def normalize_identifier(value: str | None) -> str | None:
    """Normalize a MAC or EUI-like identifier."""
    if not value:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if ":" in stripped or "-" in stripped:
        parts = [part for part in stripped.replace("-", ":").split(":") if part]
    else:
        compact = stripped.replace(" ", "")
        if len(compact) not in {12, 16}:
            return None
        parts = [compact[index : index + 2] for index in range(0, len(compact), 2)]

    if len(parts) not in {6, 8}:
        return None
    if any(len(part) != 2 for part in parts):
        return None
    if any(not all(character in "0123456789abcdefABCDEF" for character in part) for part in parts):
        return None

    return ":".join(part.lower() for part in parts)


def normalize_serial(value: str | None) -> str | None:
    """Normalize a serial number for matching."""
    if not value:
        return None

    normalized = "".join(character for character in value.strip().upper() if not character.isspace())
    if not normalized:
        return None
    return normalized


def normalize_device_identifier(value: str | None) -> str | None:
    """Normalize a generic device identifier for exact matching."""
    if value is None:
        return None

    normalized = value.strip()
    if not normalized:
        return None
    return normalized


def parse_device_identifiers(value: str | None) -> tuple[str, ...]:
    """Parse a custom-field device identifier into exact-match tokens."""
    if not value:
        return ()

    identifiers: list[str] = []
    for line in value.splitlines():
        for token in line.split(","):
            normalized = normalize_device_identifier(token)
            if normalized and normalized not in identifiers:
                identifiers.append(normalized)

    return tuple(identifiers)


def get_attached_device_key(
    identifiers: tuple[RegistryEntry, ...],
    connections: tuple[RegistryEntry, ...],
    fallback_device_id: str,
) -> str:
    """Return a stable key for the HA device the entity attaches to."""
    exact_identifiers = tuple(sorted(entry for entry in identifiers if len(entry) == 2))
    exact_connections = tuple(sorted(entry for entry in connections if len(entry) == 2))
    if not exact_identifiers and not exact_connections:
        return fallback_device_id

    payload = json.dumps(
        {
            "connections": exact_connections,
            "identifiers": exact_identifiers,
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode(), usedforsecurity=False).hexdigest()


def freeze_registry_entries(entries: Any) -> tuple[RegistryEntry, ...]:
    """Return registry entries as stable string tuples."""
    frozen_entries: list[RegistryEntry] = []
    for entry in entries or ():
        if not isinstance(entry, (list, tuple)):
            continue
        frozen_entries.append(tuple(str(part) for part in entry))
    return tuple(sorted(frozen_entries, key=repr))


@dataclass(slots=True, frozen=True)
class NetBoxDeviceRecord:
    """One normalized NetBox device."""

    device_id: int
    name: str
    display: str
    asset_tag: str
    display_url: str
    serial: str | None
    zigbee_ieee: str | None
    thread_eui64: str | None
    lorawan_eui: str | None
    device_identifiers: tuple[str, ...]


@dataclass(slots=True)
class NetBoxInventory:
    """NetBox inventory indexed for matching."""

    devices: dict[int, NetBoxDeviceRecord]
    identifier_to_device_id: dict[str, int]
    identifier_to_match_method: dict[str, str]
    duplicate_identifiers: set[str]


@dataclass(slots=True, frozen=True)
class HomeAssistantDeviceMatch:
    """One Home Assistant device matched to a NetBox device."""

    ha_device_id: str
    attached_device_key: str
    ha_device_name: str
    ha_identifiers: tuple[RegistryEntry, ...]
    ha_connections: tuple[RegistryEntry, ...]
    netbox_device_id: int
    netbox_asset_tag: str
    netbox_display: str
    netbox_url: str
    matched_identifiers: tuple[str, ...]
    match_methods: tuple[str, ...]
    weak_match: bool
    manual_override: bool
