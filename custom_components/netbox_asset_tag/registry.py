"""Registry helpers for NetBox Asset Tag."""

from __future__ import annotations

from collections.abc import Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_WRITE_ASSET_TAG_TO_DEVICES,
    DEFAULT_WRITE_ASSET_TAG_TO_DEVICES,
    DOMAIN,
)
from .device_writers import device_supports_asset_tag_write
from .models import HomeAssistantDeviceMatch


def get_asset_tag_unique_id(entry_id: str, attached_device_key: str) -> str:
    """Return the stable unique ID for one asset-tag sensor entity."""
    return f"{entry_id}_{attached_device_key}"


def get_sync_button_unique_id(entry_id: str, attached_device_key: str) -> str:
    """Return the stable unique ID for one sync-button entity."""
    return f"{entry_id}_{attached_device_key}_sync"


def get_device_write_button_unique_id(entry_id: str, attached_device_key: str) -> str:
    """Return the stable unique ID for one device-write button entity."""
    return f"{entry_id}_{attached_device_key}_write_asset_tag_to_device"


@callback
def async_cleanup_registry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    matches: Mapping[str, HomeAssistantDeviceMatch],
) -> None:
    """Remove stale NetBox Asset Tag entities from the entity registry."""
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    current_unique_ids = {
        get_asset_tag_unique_id(config_entry.entry_id, match.attached_device_key)
        for match in matches.values()
    } | {
        get_sync_button_unique_id(config_entry.entry_id, match.attached_device_key)
        for match in matches.values()
    }
    if config_entry.options.get(
        CONF_WRITE_ASSET_TAG_TO_DEVICES,
        DEFAULT_WRITE_ASSET_TAG_TO_DEVICES,
    ):
        current_unique_ids |= {
            get_device_write_button_unique_id(
                config_entry.entry_id,
                match.attached_device_key,
            )
            for match in matches.values()
            if device_supports_asset_tag_write(hass, match.ha_device_id)
        }

    # Devices where this config entry is the sole remaining owner: the primary
    # integration was removed but the NetBox match still exists.  netbox_asset_tag
    # only enriches devices owned by other integrations, so these are orphans and
    # their entities should be evicted (HA will then auto-detach the config entry).
    orphaned_device_ids: set[str] = {
        match.ha_device_id
        for match in matches.values()
        if (dev := device_registry.async_get(match.ha_device_id)) is not None
        and dev.config_entries <= {config_entry.entry_id}
    }

    # Ghost device sweep: devices that carry our config entry but are not in the
    # current match set and have no entities from any integration.  These are
    # left-over duplicates from earlier runs (e.g., a device-linking experiment).
    # Matched device IDs are excluded: their entities may not be in the registry
    # yet (entity creation is queued asynchronously after platform setup).
    matched_device_ids = {m.ha_device_id for m in matches.values()}
    for device_entry in list(device_registry.devices.values()):
        if config_entry.entry_id not in device_entry.config_entries:
            continue
        if device_entry.id in matched_device_ids:
            continue
        if er.async_entries_for_device(entity_registry, device_entry.id):
            continue
        device_registry.async_remove_device(device_entry.id)

    for entity_entry in er.async_entries_for_config_entry(
        entity_registry,
        config_entry.entry_id,
    ):
        if entity_entry.platform != DOMAIN or not entity_entry.unique_id:
            continue
        if (
            entity_entry.unique_id in current_unique_ids
            and entity_entry.device_id not in orphaned_device_ids
        ):
            continue
        entity_registry.async_remove(entity_entry.entity_id)
