"""API client for NetBox Asset Tag."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .const import (
    API_DEVICES_PATH,
    API_INTERFACES_PATH,
    API_LOCATIONS_PATH,
    API_MAC_ADDRESSES_PATH,
    API_PAGE_SIZE,
    DEFAULT_REQUEST_TIMEOUT,
)
from .exceptions import NetBoxApiError, NetBoxAuthenticationError
from .models import (
    NetBoxDeviceRecord,
    NetBoxInventory,
    parse_device_identifiers,
    normalize_identifier,
    normalize_serial,
)


def normalize_url(url: str) -> str:
    """Return a normalized NetBox URL."""
    return url.rstrip("/")


class NetBoxApiClient:
    """Client for the NetBox API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        token: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self.base_url = normalize_url(base_url)
        self._token = token

    async def async_fetch_locations(self) -> list[dict[str, Any]]:
        """Fetch all NetBox locations."""
        return await self._async_paginate(API_LOCATIONS_PATH)

    async def async_get_device(self, device_id: int) -> dict[str, Any]:
        """GET one NetBox device by ID."""
        return await self._async_get_json(f"api/dcim/devices/{device_id}/")

    async def async_patch_device(
        self, device_id: int, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """PATCH a NetBox device with the given fields."""
        url = urljoin(f"{self.base_url}/", f"api/dcim/devices/{device_id}/")
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Token {self._token}",
        }
        try:
            async with self._session.patch(
                url,
                headers=headers,
                json=payload,
                timeout=DEFAULT_REQUEST_TIMEOUT,
            ) as response:
                if response.status in {401, 403}:
                    raise NetBoxAuthenticationError(
                        "NetBox rejected the supplied API token"
                    )
                if response.status >= 400:
                    body = await response.text()
                    raise NetBoxApiError(
                        f"NetBox PATCH failed with status {response.status}: {body[:200]}"
                    )
                return await response.json()
        except aiohttp.ClientError as err:
            raise NetBoxApiError("Failed to reach NetBox") from err

    async def async_validate(self) -> dict[str, Any]:
        """Validate the configured URL and token."""
        data = await self._async_get_json(f"{API_DEVICES_PATH}?limit=1")
        return {
            "count": int(data.get("count", 0)),
        }

    async def async_fetch_inventory(self) -> NetBoxInventory:
        """Fetch and normalize NetBox devices and interfaces."""
        devices_payload, interfaces_payload, mac_addresses_payload = (
            await self._async_fetch_inventory_payloads()
        )

        devices: dict[int, NetBoxDeviceRecord] = {}
        candidates: dict[str, set[int]] = defaultdict(set)

        for item in devices_payload:
            asset_tag = item.get("asset_tag")
            display_url = item.get("display_url")
            if not asset_tag or not display_url:
                continue

            custom_fields = item.get("custom_fields") or {}
            record = NetBoxDeviceRecord(
                device_id=int(item["id"]),
                name=item.get("name") or item.get("display") or str(item["id"]),
                display=item.get("display") or item.get("name") or str(item["id"]),
                asset_tag=asset_tag,
                display_url=display_url,
                serial=normalize_serial(item.get("serial")),
                zigbee_ieee=normalize_identifier(custom_fields.get("zigbee_ieee")),
                thread_eui64=normalize_identifier(custom_fields.get("thread_eui64")),
                lorawan_eui=normalize_serial(custom_fields.get("lorawan_eui")),
                device_identifiers=parse_device_identifiers(
                    custom_fields.get("device_identifier")
                ),
            )
            devices[record.device_id] = record

            for identifier in (
                record.serial,
                record.zigbee_ieee,
                record.thread_eui64,
                record.lorawan_eui,
                *record.device_identifiers,
            ):
                if identifier:
                    candidates[identifier].add(record.device_id)

        for item in interfaces_payload:
            device = item.get("device") or {}
            device_id = device.get("id")
            if device_id is None or int(device_id) not in devices:
                continue

            mac_address = normalize_identifier(item.get("mac_address"))
            if not mac_address:
                primary_mac = item.get("primary_mac_address") or {}
                mac_address = normalize_identifier(primary_mac.get("mac_address"))
            if mac_address:
                candidates[mac_address].add(int(device_id))

        for item in mac_addresses_payload:
            assigned_object_type = item.get("assigned_object_type")
            if assigned_object_type != "dcim.interface":
                continue

            interface = item.get("assigned_object") or {}
            device = interface.get("device") or {}
            device_id = device.get("id")
            if device_id is None or int(device_id) not in devices:
                continue

            mac_address = normalize_identifier(item.get("mac_address"))
            if mac_address:
                candidates[mac_address].add(int(device_id))

        identifier_to_device_id: dict[str, int] = {}
        identifier_to_match_method: dict[str, str] = {}
        duplicate_identifiers: set[str] = set()
        for identifier, device_ids in candidates.items():
            if len(device_ids) != 1:
                duplicate_identifiers.add(identifier)
                continue
            identifier_to_device_id[identifier] = next(iter(device_ids))
            identifier_to_match_method[identifier] = self._match_method_for_identifier(
                identifier,
                devices,
                interfaces_payload,
                mac_addresses_payload,
            )

        return NetBoxInventory(
            devices=devices,
            identifier_to_device_id=identifier_to_device_id,
            identifier_to_match_method=identifier_to_match_method,
            duplicate_identifiers=duplicate_identifiers,
        )

    @staticmethod
    def _match_method_for_identifier(
        identifier: str,
        devices: dict[int, NetBoxDeviceRecord],
        interfaces_payload: list[dict[str, Any]],
        mac_addresses_payload: list[dict[str, Any]],
    ) -> str:
        """Return the match method for one resolved identifier."""
        for device in devices.values():
            if device.serial == identifier:
                return "serial"
            if device.zigbee_ieee == identifier:
                return "zigbee"
            if device.thread_eui64 == identifier:
                return "thread"
            if device.lorawan_eui == identifier:
                return "lorawan"
            if identifier in device.device_identifiers:
                return "device_identifier"

        for item in interfaces_payload:
            device = item.get("device") or {}
            device_id = device.get("id")
            if device_id is None or int(device_id) not in devices:
                continue
            mac_address = normalize_identifier(item.get("mac_address"))
            if not mac_address:
                primary_mac = item.get("primary_mac_address") or {}
                mac_address = normalize_identifier(primary_mac.get("mac_address"))
            if mac_address == identifier:
                return "mac"

        for item in mac_addresses_payload:
            if item.get("assigned_object_type") != "dcim.interface":
                continue
            assigned_object = item.get("assigned_object") or {}
            device = assigned_object.get("device") or {}
            device_id = device.get("id")
            if device_id is None or int(device_id) not in devices:
                continue
            if normalize_identifier(item.get("mac_address")) == identifier:
                return "mac"

        return "identifier"

    async def _async_fetch_inventory_payloads(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch paginated NetBox devices, interfaces, and MAC addresses."""
        devices, interfaces, mac_addresses = await asyncio.gather(
            self._async_paginate(API_DEVICES_PATH),
            self._async_paginate(API_INTERFACES_PATH),
            self._async_paginate(API_MAC_ADDRESSES_PATH),
        )
        return devices, interfaces, mac_addresses

    async def _async_paginate(self, path: str) -> list[dict[str, Any]]:
        """Return all records from one paginated API endpoint."""
        results: list[dict[str, Any]] = []
        next_url: str | None = f"{path}?limit={API_PAGE_SIZE}"

        while next_url:
            payload = await self._async_get_json(next_url)
            items = payload.get("results")
            if not isinstance(items, list):
                raise NetBoxApiError(f"Unexpected payload for {path}")
            results.extend(item for item in items if isinstance(item, dict))

            raw_next = payload.get("next")
            if isinstance(raw_next, str) and raw_next:
                next_url = raw_next
            else:
                next_url = None

        return results

    async def _async_get_json(self, path_or_url: str) -> dict[str, Any]:
        """GET one NetBox JSON endpoint."""
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            url = path_or_url
        else:
            url = urljoin(f"{self.base_url}/", path_or_url.lstrip("/"))

        headers = {
            "Accept": "application/json",
            "Authorization": f"Token {self._token}",
        }

        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=DEFAULT_REQUEST_TIMEOUT,
            ) as response:
                if response.status in {401, 403}:
                    raise NetBoxAuthenticationError(
                        "NetBox rejected the supplied API token"
                    )
                if response.status >= 400:
                    raise NetBoxApiError(
                        f"NetBox request failed with status {response.status}"
                    )
                payload = await response.json()
        except aiohttp.ClientError as err:
            raise NetBoxApiError("Failed to reach NetBox") from err

        if not isinstance(payload, dict):
            raise NetBoxApiError("NetBox returned an unexpected payload")

        return payload
