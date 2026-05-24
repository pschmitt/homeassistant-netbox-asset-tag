"""Services for the NetBox Asset Tag integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, SERVICE_SYNC_TO_NETBOX
from .exceptions import NetBoxApiError

_LOGGER = logging.getLogger(__name__)

SYNC_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
    }
)


def _strip_symbols(name: str) -> str:
    """Strip emoji/symbols from a location name and casefold for comparison."""
    plain = re.sub(r"[^\w\s]", " ", name, flags=re.UNICODE)
    return " ".join(plain.split()).casefold()


async def async_register_services(hass: HomeAssistant) -> None:
    """Register integration services (idempotent — safe to call on every entry load)."""
    if hass.services.has_service(DOMAIN, SERVICE_SYNC_TO_NETBOX):
        return

    async def _handle_sync_to_netbox(call: ServiceCall) -> None:
        target_ids: set[str] = set(call.data.get("device_id") or [])

        device_reg = dr.async_get(hass)
        area_reg = ar.async_get(hass)

        for entry_data in hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry_data, dict):
                continue
            coordinator = entry_data.get("coordinator")
            client = entry_data.get("client")
            if coordinator is None or client is None or not coordinator.data:
                continue

            try:
                locations = await client.async_fetch_locations()
            except NetBoxApiError as err:
                _LOGGER.error("Failed to fetch NetBox locations: %s", err)
                locations = []

            location_map: dict[str, int] = {
                _strip_symbols(loc["name"]): int(loc["id"])
                for loc in locations
                if loc.get("name") and loc.get("id") is not None
            }

            for match in coordinator.data.values():
                if target_ids and match.ha_device_id not in target_ids:
                    continue

                device_entry = device_reg.async_get(match.ha_device_id)
                if device_entry is None:
                    continue

                payload: dict[str, Any] = {
                    "status": "inventory" if device_entry.disabled_by else "active",
                }

                if device_entry.area_id:
                    area = area_reg.async_get_area(device_entry.area_id)
                    if area:
                        loc_id = location_map.get(_strip_symbols(area.name))
                        if loc_id is not None:
                            payload["location"] = loc_id
                        else:
                            _LOGGER.debug(
                                "No NetBox location match for HA area %r (normalized: %r)",
                                area.name,
                                _strip_symbols(area.name),
                            )

                try:
                    await client.async_patch_device(match.netbox_device_id, payload)
                    _LOGGER.info(
                        "Synced %r → NetBox #%d: %s",
                        match.ha_device_name,
                        match.netbox_device_id,
                        payload,
                    )
                except NetBoxApiError as err:
                    _LOGGER.error(
                        "Failed to sync %r (NetBox #%d): %s",
                        match.ha_device_name,
                        match.netbox_device_id,
                        err,
                    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_TO_NETBOX,
        _handle_sync_to_netbox,
        schema=SYNC_SERVICE_SCHEMA,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove integration services when the last config entry is unloaded."""
    if hass.data.get(DOMAIN):
        return
    if hass.services.has_service(DOMAIN, SERVICE_SYNC_TO_NETBOX):
        hass.services.async_remove(DOMAIN, SERVICE_SYNC_TO_NETBOX)
