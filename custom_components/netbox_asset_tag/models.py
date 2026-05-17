"""Models for NetBox Asset Tag."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

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


@dataclass(slots=True)
class NetBoxInventory:
    """NetBox inventory indexed for matching."""

    devices: dict[int, NetBoxDeviceRecord]
    identifier_to_device_id: dict[str, int]
    duplicate_identifiers: set[str]


@dataclass(slots=True, frozen=True)
class HomeAssistantDeviceMatch:
    """One Home Assistant device matched to a NetBox device."""

    ha_device_id: str
    ha_device_name: str
    ha_identifiers: tuple[RegistryEntry, ...]
    ha_connections: tuple[RegistryEntry, ...]
    netbox_device_id: int
    netbox_asset_tag: str
    netbox_display: str
    netbox_url: str
    matched_identifiers: tuple[str, ...]
