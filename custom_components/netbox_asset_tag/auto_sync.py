"""Auto-sync support for NetBox Asset Tag."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback

from .const import CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC, DOMAIN, SERVICE_SYNC_TO_NETBOX
from .coordinator import NetBoxAssetTagCoordinator

_LOGGER = logging.getLogger(__name__)

_SYNC_WATCHED_FIELDS: frozenset[str] = frozenset(
    {"area_id", "disabled_by", "name", "name_by_user"}
)
_MATCH_WATCHED_FIELDS: frozenset[str] = frozenset(
    {"connections", "identifiers", "serial_number"}
)


@callback
def async_setup_auto_sync(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    coordinator: NetBoxAssetTagCoordinator,
) -> None:
    """Register listeners for device matching and NetBox sync."""

    def _is_enabled() -> bool:
        return config_entry.options.get(CONF_AUTO_SYNC, DEFAULT_AUTO_SYNC)

    @callback
    def _handle_device_registry_updated(event: Event) -> None:
        action = event.data.get("action")
        changes: dict = event.data.get("changes", {})
        device_id: str | None = event.data.get("device_id")

        if action == "create" or (
            action == "update" and _MATCH_WATCHED_FIELDS.intersection(changes)
        ):
            _LOGGER.debug(
                "Refreshing NetBox device matches after Home Assistant device %s: %s",
                action,
                device_id,
            )
            config_entry.async_create_background_task(
                hass,
                coordinator.async_request_refresh(),
                f"netbox_asset_tag_device_match_refresh_{device_id or 'unknown'}",
            )

        if not _is_enabled():
            return

        if action != "update":
            return

        if not _SYNC_WATCHED_FIELDS.intersection(changes):
            return

        if device_id is None:
            return

        if not coordinator.data:
            return

        for match in coordinator.data.values():
            if match.ha_device_id == device_id:
                _LOGGER.debug(
                    "Auto-sync triggered for %r (changed: %s)",
                    match.ha_device_name,
                    sorted(_SYNC_WATCHED_FIELDS.intersection(changes)),
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
