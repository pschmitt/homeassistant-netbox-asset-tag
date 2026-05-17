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
    API_PAGE_SIZE,
    DEFAULT_REQUEST_TIMEOUT,
)
from .exceptions import NetBoxApiError, NetBoxAuthenticationError
from .models import NetBoxDeviceRecord, NetBoxInventory, normalize_identifier


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

    async def async_validate(self) -> dict[str, Any]:
        """Validate the configured URL and token."""
        data = await self._async_get_json(f"{API_DEVICES_PATH}?limit=1")
        return {
            "count": int(data.get("count", 0)),
        }

    async def async_fetch_inventory(self) -> NetBoxInventory:
        """Fetch and normalize NetBox devices and interfaces."""
        devices_payload, interfaces_payload = await self._async_fetch_devices_and_interfaces()

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
                zigbee_ieee=normalize_identifier(custom_fields.get("zigbee_ieee")),
                thread_eui64=normalize_identifier(custom_fields.get("thread_eui64")),
            )
            devices[record.device_id] = record

            for identifier in (record.zigbee_ieee, record.thread_eui64):
                if identifier:
                    candidates[identifier].add(record.device_id)

        for item in interfaces_payload:
            device = item.get("device") or {}
            device_id = device.get("id")
            if device_id is None or int(device_id) not in devices:
                continue

            mac_address = normalize_identifier(item.get("mac_address"))
            if mac_address:
                candidates[mac_address].add(int(device_id))

        identifier_to_device_id: dict[str, int] = {}
        duplicate_identifiers: set[str] = set()
        for identifier, device_ids in candidates.items():
            if len(device_ids) != 1:
                duplicate_identifiers.add(identifier)
                continue
            identifier_to_device_id[identifier] = next(iter(device_ids))

        return NetBoxInventory(
            devices=devices,
            identifier_to_device_id=identifier_to_device_id,
            duplicate_identifiers=duplicate_identifiers,
        )

    async def _async_fetch_devices_and_interfaces(
        self,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Fetch paginated NetBox devices and interfaces."""
        devices, interfaces = await asyncio.gather(
            self._async_paginate(API_DEVICES_PATH),
            self._async_paginate(API_INTERFACES_PATH),
        )
        return devices, interfaces

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
