"""Auto-sync support for NetBox Asset Tag."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback

from .const import CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC, DOMAIN, SERVICE_SYNC_TO_NETBOX
from .coordinator import NetBoxAssetTagCoordinator

_LOGGER = logging.getLogger(__name__)

_WATCHED_FIELDS: frozenset[str] = frozenset({"area_id", "disabled_by", "name", "name_by_user"})


@callback
def async_setup_auto_sync(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: NetBoxAssetTagCoordinator,
) -> None:
    """Register listeners that trigger sync on device changes and coordinator refreshes."""

    def _is_enabled() -> bool:
        return config_entry.options.get(CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC)

    @callback
    def _handle_device_registry_updated(event: Event) -> None:
        if not _is_enabled():
            return

        if event.data.get("action") != "update":
            return

        changes: dict = event.data.get("changes", {})
        if not _WATCHED_FIELDS.intersection(changes):
            return

        device_id: str = event.data["device_id"]

        if not coordinator.data:
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

    @callback
    def _handle_coordinator_refresh() -> None:
        if not _is_enabled():
            return

        if not coordinator.data:
            return

        _LOGGER.debug("Periodic auto-sync triggered by coordinator refresh")
        config_entry.async_create_background_task(
            hass,
            hass.services.async_call(
                DOMAIN,
                SERVICE_SYNC_TO_NETBOX,
                {},
                blocking=True,
            ),
            "netbox_asset_tag_periodic_sync",
        )

    config_entry.async_on_unload(
        hass.bus.async_listen(
            "homeassistant_device_registry_updated",
            _handle_device_registry_updated,
        )
    )
    config_entry.async_on_unload(
        coordinator.async_add_listener(_handle_coordinator_refresh)
    )
