"""The NetBox Asset Tag integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, CONF_URL
from homeassistant.core import Event, HomeAssistant, callback
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
    async_setup_auto_sync(hass, config_entry)

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
    hass.data[DOMAIN].pop(config_entry.entry_id)
    async_unregister_services(hass)
    return unload_ok


async def async_update_listener(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Reload the integration after options changes."""
    await hass.config_entries.async_reload(config_entry.entry_id)

