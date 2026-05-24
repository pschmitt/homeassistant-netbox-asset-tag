"""Auto-sync support for NetBox Asset Tag."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback

from .const import CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC, DOMAIN, SERVICE_SYNC_TO_NETBOX

_LOGGER = logging.getLogger(__name__)

_WATCHED_FIELDS: frozenset[str] = frozenset({"area_id", "disabled_by", "name", "name_by_user"})


@callback
def async_setup_auto_sync(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Register a device-registry listener that triggers sync on relevant changes."""

    @callback
    def _handle_device_registry_updated(event: Event) -> None:
        if not config_entry.options.get(CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC):
            return

        if event.data.get("action") != "update":
            return

        changes: dict = event.data.get("changes", {})
        if not _WATCHED_FIELDS.intersection(changes):
            return

        device_id: str = event.data["device_id"]

        coordinator = (
            hass.data.get(DOMAIN, {})
            .get(config_entry.entry_id, {})
            .get("coordinator")
        )
        if coordinator is None or not coordinator.data:
            return

        for match in coordinator.data.values():
            if match.ha_device_id == device_id:
                _LOGGER.debug(
                    "Auto-sync triggered for %r (changed: %s)",
                    match.ha_device_name,
                    sorted(_WATCHED_FIELDS.intersection(changes)),
                )
                config_entry.async_create_background_task(
                    hass,
                    hass.services.async_call(
                        DOMAIN,
                        SERVICE_SYNC_TO_NETBOX,
                        {"device_id": [device_id]},
                        blocking=True,
                    ),
                    f"netbox_asset_tag_auto_sync_{device_id}",
                )
                break

    config_entry.async_on_unload(
        hass.bus.async_listen(
            "homeassistant_device_registry_updated",
            _handle_device_registry_updated,
        )
    )
