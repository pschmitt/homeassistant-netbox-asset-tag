"""Diagnostics support for NetBox Asset Tag."""

from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

from .const import DOMAIN

TO_REDACT = {CONF_TOKEN}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
) -> dict:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    return {
        "entry": async_redact_data(dict(config_entry.data), TO_REDACT),
        "options": dict(config_entry.options),
        "matched_device_count": len(coordinator.data),
        "matched_devices": [
            {
                "ha_device_id": match.ha_device_id,
                "ha_device_name": match.ha_device_name,
                "netbox_device_id": match.netbox_device_id,
                "netbox_asset_tag": match.netbox_asset_tag,
                "netbox_url": match.netbox_url,
                "matched_identifiers": list(match.matched_identifiers),
            }
            for match in coordinator.data.values()
        ],
    }

