"""Services for the NetBox Asset Tag integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
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

    async def _handle_sync_to_netbox(call: ServiceCall) -> ServiceResponse:
        target_ids: set[str] = set(call.data.get("device_id") or [])
        # Track which requested IDs we actually found in the coordinator
        matched_ids: set[str] = set()

        device_reg = dr.async_get(hass)
        area_reg = ar.async_get(hass)

        synced: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

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

                matched_ids.add(match.ha_device_id)
                device_entry = device_reg.async_get(match.ha_device_id)
                if device_entry is None:
                    skipped.append(
                        {
                            "ha_device_id": match.ha_device_id,
                            "ha_device_name": match.ha_device_name,
                            "netbox_asset_tag": match.netbox_asset_tag,
                            "reason": "device_not_in_registry",
                        }
                    )
                    continue

                payload: dict[str, Any] = {
                    "status": "inventory" if device_entry.disabled_by else "active",
                }

                location_id: int | None = None
                area_name: str | None = None
                if device_entry.area_id:
                    area = area_reg.async_get_area(device_entry.area_id)
                    if area:
                        area_name = area.name
                        location_id = location_map.get(_strip_symbols(area.name))
                        if location_id is not None:
                            payload["location"] = location_id
                        else:
                            _LOGGER.warning(
                                "No NetBox location matched HA area %r (normalized: %r). "
                                "Available locations: %s",
                                area.name,
                                _strip_symbols(area.name),
                                sorted(location_map.keys()),
                            )

                try:
                    await client.async_patch_device(match.netbox_device_id, payload)
                    _LOGGER.info(
                        "Synced %r → NetBox #%d %s: %s",
                        match.ha_device_name,
                        match.netbox_device_id,
                        match.netbox_asset_tag,
                        payload,
                    )
                    synced.append(
                        {
                            "ha_device_id": match.ha_device_id,
                            "ha_device_name": match.ha_device_name,
                            "netbox_device_id": match.netbox_device_id,
                            "netbox_asset_tag": match.netbox_asset_tag,
                            "changes": payload,
                            **({"ha_area": area_name} if area_name else {}),
                            **(
                                {"location_unmatched": True}
                                if area_name and location_id is None
                                else {}
                            ),
                        }
                    )
                except NetBoxApiError as err:
                    _LOGGER.error(
                        "Failed to sync %r (NetBox #%d %s): %s",
                        match.ha_device_name,
                        match.netbox_device_id,
                        match.netbox_asset_tag,
                        err,
                    )
                    errors.append(
                        {
                            "ha_device_id": match.ha_device_id,
                            "ha_device_name": match.ha_device_name,
                            "netbox_device_id": match.netbox_device_id,
                            "netbox_asset_tag": match.netbox_asset_tag,
                            "error": str(err),
                        }
                    )

        # Report device IDs that were explicitly requested but had no coordinator match
        for device_id in target_ids - matched_ids:
            device_entry = device_reg.async_get(device_id)
            name = (
                (device_entry.name_by_user or device_entry.name or device_id)
                if device_entry
                else device_id
            )
            _LOGGER.warning(
                "Device %r (%s) was requested but has no NetBox coordinator match — "
                "it may not be tracked by this integration",
                name,
                device_id,
            )
            skipped.append(
                {
                    "ha_device_id": device_id,
                    "ha_device_name": name,
                    "reason": "no_coordinator_match",
                }
            )

        return {"synced": synced, "skipped": skipped, "errors": errors}

    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC_TO_NETBOX,
        _handle_sync_to_netbox,
        schema=SYNC_SERVICE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove integration services when the last config entry is unloaded."""
    if hass.data.get(DOMAIN):
        return
    if hass.services.has_service(DOMAIN, SERVICE_SYNC_TO_NETBOX):
        hass.services.async_remove(DOMAIN, SERVICE_SYNC_TO_NETBOX)
