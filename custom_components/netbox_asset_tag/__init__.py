"""The NetBox Asset Tag integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import NetBoxApiClient
from .auto_sync import async_setup_auto_sync
from .const import CONF_VERIFY_SSL, DOMAIN, PLATFORMS
from .coordinator import NetBoxAssetTagCoordinator
from .registry import async_cleanup_registry
from .services import async_register_services, async_unregister_services


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the NetBox Asset Tag integration."""
    del config
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up NetBox Asset Tag from a config entry."""
    session = async_create_clientsession(
        hass,
        verify_ssl=config_entry.data[CONF_VERIFY_SSL],
    )
    client = NetBoxApiClient(
        session=session,
        base_url=config_entry.data[CONF_URL],
        token=config_entry.data[CONF_TOKEN],
    )
    coordinator = NetBoxAssetTagCoordinator(hass, client, config_entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][config_entry.entry_id] = {
        "client": client,
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    async_cleanup_registry(hass, config_entry, coordinator.data)
    await async_register_services(hass)

    @callback
    def async_cleanup_listener() -> None:
        """Remove stale entities after coordinator updates."""
        async_cleanup_registry(hass, config_entry, coordinator.data)

    config_entry.async_on_unload(coordinator.async_add_listener(async_cleanup_listener))
    config_entry.async_on_unload(config_entry.add_update_listener(async_update_listener))
    async_setup_auto_sync(hass, config_entry, coordinator)

    @callback
    def _on_component_loaded(event: Event) -> None:
        if event.data.get("component") == "matter":
            config_entry.async_create_background_task(
                hass,
                coordinator.async_request_refresh(),
                "netbox_asset_tag_matter_refresh",
            )

    config_entry.async_on_unload(
        hass.bus.async_listen("component_loaded", _on_component_loaded)
    )

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a NetBox Asset Tag config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(config_entry.entry_id, None)
        async_unregister_services(hass)
    return unload_ok


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow a user to delete a device from this config entry.

    NetBox Asset Tag does not own devices; it only enriches devices provided by
    other integrations with an asset-tag sensor and helper buttons, so it should
    never be the sole reason a device cannot be deleted.

    Removal is refused only when the device is still actively matched to NetBox
    *and* still backed by another integration: in that case the asset-tag entity
    would just be recreated on the next coordinator refresh, so the deletion
    would not stick and allowing it would only cause churn. Orphaned devices
    that this integration alone keeps alive are always removable.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
    coordinator = entry_data.get("coordinator") if entry_data else None
    matches = getattr(coordinator, "data", None) or {}
    still_matched = any(
        match.ha_device_id == device_entry.id for match in matches.values()
    )
    backed_by_other_integration = any(
        entry_id != config_entry.entry_id
        for entry_id in device_entry.config_entries
    )
    return not (still_matched and backed_by_other_integration)


async def async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload the integration after options changes."""
    await hass.config_entries.async_reload(config_entry.entry_id)

