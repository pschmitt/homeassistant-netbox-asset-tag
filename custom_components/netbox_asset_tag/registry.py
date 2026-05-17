"""Registry helpers for NetBox Asset Tag."""

from __future__ import annotations

from collections.abc import Mapping

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .models import HomeAssistantDeviceMatch


def get_asset_tag_unique_id(entry_id: str, ha_device_id: str) -> str:
    """Return the stable unique ID for one asset-tag entity."""
    return f"{entry_id}_{ha_device_id}"


@callback
def async_cleanup_registry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    matches: Mapping[str, HomeAssistantDeviceMatch],
) -> None:
    """Remove stale NetBox Asset Tag entities from the entity registry."""
    entity_registry = er.async_get(hass)
    current_unique_ids = {
        get_asset_tag_unique_id(config_entry.entry_id, ha_device_id)
        for ha_device_id in matches
    }
    valid_prefix = f"{config_entry.entry_id}_"

    for entity_entry in er.async_entries_for_config_entry(
        entity_registry,
        config_entry.entry_id,
    ):
        if entity_entry.platform != DOMAIN or not entity_entry.unique_id:
            continue
        if entity_entry.unique_id in current_unique_ids:
            continue
        if not entity_entry.unique_id.startswith(valid_prefix):
            continue
        entity_registry.async_remove(entity_entry.entity_id)

