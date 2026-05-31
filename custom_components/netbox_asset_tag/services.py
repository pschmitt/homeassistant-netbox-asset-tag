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

from .const import (
    CONF_HA_URL_FIELD,
    CONF_SYNC_FIELDS,
    CONF_WRITE_ASSET_TAG_TO_DEVICES,
    DEFAULT_HA_URL_FIELD,
    DEFAULT_SYNC_FIELDS,
    DEFAULT_WRITE_ASSET_TAG_TO_DEVICES,
    DOMAIN,
    SERVICE_SYNC_TO_NETBOX,
    SERVICE_WRITE_ASSET_TAG_TO_DEVICE,
    SYNC_FIELD_HA_URL,
    SYNC_FIELD_LOCATION,
    SYNC_FIELD_NAME,
    SYNC_FIELD_SERIAL,
    SYNC_FIELD_STATUS,
)
from .device_writers import (
    DeviceAssetTagWriterFailed,
    DeviceAssetTagWriterUnsupported,
    async_write_asset_tag_to_device,
)
from .exceptions import NetBoxApiError

_LOGGER = logging.getLogger(__name__)

SYNC_SERVICE_SCHEMA = vol.Schema(
    {
        vol.Optional("device_id", default=[]): vol.All(cv.ensure_list, [cv.string]),
    }
)
WRITE_TO_DEVICE_SERVICE_SCHEMA = vol.Schema(
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

            sync_fields: list[str] = list(
                coordinator.config_entry.options.get(CONF_SYNC_FIELDS, DEFAULT_SYNC_FIELDS)
            )

            location_map: dict[str, tuple[int, str]] = {}
            if SYNC_FIELD_LOCATION in sync_fields:
                try:
                    locations = await client.async_fetch_locations()
                except NetBoxApiError as err:
                    _LOGGER.error("Failed to fetch NetBox locations: %s", err)
                    locations = []
                location_map = {
                    _strip_symbols(loc["name"]): (int(loc["id"]), loc["name"])
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

                payload: dict[str, Any] = {}

                if SYNC_FIELD_STATUS in sync_fields:
                    payload["status"] = "inventory" if device_entry.disabled_by else "active"

                location_id: int | None = None
                location_name: str | None = None
                area_name: str | None = None
                if SYNC_FIELD_LOCATION in sync_fields and device_entry.area_id:
                    area = area_reg.async_get_area(device_entry.area_id)
                    if area:
                        area_name = area.name
                        loc_entry = location_map.get(_strip_symbols(area.name))
                        if loc_entry is not None:
                            location_id, location_name = loc_entry
                            payload["location"] = location_id
                        else:
                            _LOGGER.warning(
                                "No NetBox location matched HA area %r (normalized: %r). "
                                "Available locations: %s",
                                area.name,
                                _strip_symbols(area.name),
                                sorted(location_map.keys()),
                            )

                if SYNC_FIELD_NAME in sync_fields:
                    ha_name = device_entry.name_by_user or device_entry.name
                    if ha_name:
                        payload["name"] = ha_name

                if SYNC_FIELD_SERIAL in sync_fields:
                    ha_serial = device_entry.serial_number
                    if ha_serial:
                        payload["serial"] = ha_serial
                    else:
                        _LOGGER.debug(
                            "Skipping serial sync for %r: HA reports no serial number",
                            match.ha_device_name,
                        )

                ha_device_url: str | None = None
                if SYNC_FIELD_HA_URL in sync_fields:
                    base_url = hass.config.external_url or hass.config.internal_url
                    if base_url:
                        ha_url_field = coordinator.config_entry.options.get(
                            CONF_HA_URL_FIELD, DEFAULT_HA_URL_FIELD
                        )
                        ha_device_url = (
                            f"{base_url.rstrip('/')}/config/devices/device/{match.ha_device_id}"
                        )
                        payload.setdefault("custom_fields", {})[ha_url_field] = ha_device_url
                    else:
                        _LOGGER.warning(
                            "Cannot sync HA device URL to NetBox for %r: "
                            "no external or internal URL configured in Home Assistant",
                            match.ha_device_name,
                        )

                # Fetch current NetBox state so we can show old → new in notifications
                try:
                    current_nb = await client.async_get_device(match.netbox_device_id)
                except NetBoxApiError:
                    current_nb = {}

                try:
                    await client.async_patch_device(match.netbox_device_id, payload)
                    _LOGGER.info(
                        "Synced %r → NetBox #%d %s: %s",
                        match.ha_device_name,
                        match.netbox_device_id,
                        match.netbox_asset_tag,
                        payload,
                    )
                    changes_flat: dict[str, Any] = {}
                    for k, v in payload.items():
                        if k in ("custom_fields", "location"):
                            continue
                        change: dict[str, Any] = {"new": v}
                        if k == "status":
                            nb_status = current_nb.get("status") or {}
                            old = nb_status.get("value") if isinstance(nb_status, dict) else None
                            if old is not None:
                                change["old"] = old
                        elif k == "name":
                            old = current_nb.get("name")
                            if old is not None:
                                change["old"] = old
                        elif k == "serial":
                            old = current_nb.get("serial") or None
                            if old is not None:
                                change["old"] = old
                        changes_flat[k] = change
                    if ha_device_url is not None:
                        ha_url_field = coordinator.config_entry.options.get(
                            CONF_HA_URL_FIELD, DEFAULT_HA_URL_FIELD
                        )
                        old_url = (current_nb.get("custom_fields") or {}).get(ha_url_field)
                        url_change: dict[str, Any] = {"new": ha_device_url}
                        if old_url is not None:
                            url_change["old"] = old_url
                        changes_flat["ha_url"] = url_change

                    old_location_name: str | None = None
                    if location_name is not None:
                        nb_loc = current_nb.get("location") or {}
                        old_location_name = nb_loc.get("name") if isinstance(nb_loc, dict) else None

                    synced.append(
                        {
                            "ha_device_id": match.ha_device_id,
                            "ha_device_name": match.ha_device_name,
                            "netbox_device_id": match.netbox_device_id,
                            "netbox_asset_tag": match.netbox_asset_tag,
                            "changes": changes_flat,
                            **({"ha_area": area_name} if area_name else {}),
                            **({"location_name": location_name} if location_name else {}),
                            **({"old_location_name": old_location_name} if old_location_name else {}),
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

    async def _handle_write_asset_tag_to_device(call: ServiceCall) -> ServiceResponse:
        target_ids: set[str] = set(call.data.get("device_id") or [])
        matched_ids: set[str] = set()

        device_reg = dr.async_get(hass)

        written: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        for entry_data in hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry_data, dict):
                continue
            coordinator = entry_data.get("coordinator")
            if coordinator is None or not coordinator.data:
                continue

            if not coordinator.config_entry.options.get(
                CONF_WRITE_ASSET_TAG_TO_DEVICES,
                DEFAULT_WRITE_ASSET_TAG_TO_DEVICES,
            ):
                for match in coordinator.data.values():
                    if target_ids and match.ha_device_id not in target_ids:
                        continue
                    matched_ids.add(match.ha_device_id)
                    skipped.append(
                        {
                            "ha_device_id": match.ha_device_id,
                            "ha_device_name": match.ha_device_name,
                            "netbox_asset_tag": match.netbox_asset_tag,
                            "reason": "device_asset_tag_writes_disabled",
                        }
                    )
                continue

            for match in coordinator.data.values():
                if target_ids and match.ha_device_id not in target_ids:
                    continue

                matched_ids.add(match.ha_device_id)
                try:
                    result = await async_write_asset_tag_to_device(
                        hass,
                        match.ha_device_id,
                        match.netbox_asset_tag,
                    )
                except DeviceAssetTagWriterUnsupported:
                    skipped.append(
                        {
                            "ha_device_id": match.ha_device_id,
                            "ha_device_name": match.ha_device_name,
                            "netbox_asset_tag": match.netbox_asset_tag,
                            "reason": "device_not_supported",
                        }
                    )
                except DeviceAssetTagWriterFailed as err:
                    _LOGGER.error(
                        "Failed to write asset tag %s to %r: %s",
                        match.netbox_asset_tag,
                        match.ha_device_name,
                        err,
                    )
                    errors.append(
                        {
                            "ha_device_id": match.ha_device_id,
                            "ha_device_name": match.ha_device_name,
                            "netbox_asset_tag": match.netbox_asset_tag,
                            "error": str(err),
                        }
                    )
                else:
                    _LOGGER.info(
                        "Wrote asset tag %s to %r via %s key %s",
                        match.netbox_asset_tag,
                        match.ha_device_name,
                        result.backend,
                        result.key,
                    )
                    written.append(
                        {
                            "ha_device_id": match.ha_device_id,
                            "ha_device_name": match.ha_device_name,
                            "netbox_device_id": match.netbox_device_id,
                            "netbox_asset_tag": match.netbox_asset_tag,
                            "backend": result.backend,
                            "key": result.key,
                        }
                    )

        for device_id in target_ids - matched_ids:
            device_entry = device_reg.async_get(device_id)
            name = (
                (device_entry.name_by_user or device_entry.name or device_id)
                if device_entry
                else device_id
            )
            skipped.append(
                {
                    "ha_device_id": device_id,
                    "ha_device_name": name,
                    "reason": "no_coordinator_match",
                }
            )

        return {"written": written, "skipped": skipped, "errors": errors}

    if not hass.services.has_service(DOMAIN, SERVICE_SYNC_TO_NETBOX):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SYNC_TO_NETBOX,
            _handle_sync_to_netbox,
            schema=SYNC_SERVICE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_WRITE_ASSET_TAG_TO_DEVICE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_WRITE_ASSET_TAG_TO_DEVICE,
            _handle_write_asset_tag_to_device,
            schema=WRITE_TO_DEVICE_SERVICE_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove integration services when the last config entry is unloaded."""
    if hass.data.get(DOMAIN):
        return
    if hass.services.has_service(DOMAIN, SERVICE_SYNC_TO_NETBOX):
        hass.services.async_remove(DOMAIN, SERVICE_SYNC_TO_NETBOX)
    if hass.services.has_service(DOMAIN, SERVICE_WRITE_ASSET_TAG_TO_DEVICE):
        hass.services.async_remove(DOMAIN, SERVICE_WRITE_ASSET_TAG_TO_DEVICE)
