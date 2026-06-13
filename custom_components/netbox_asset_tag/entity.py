"""Entity helpers for NetBox Asset Tag."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import NetBoxAssetTagCoordinator
from .models import HomeAssistantDeviceMatch


class NetBoxAssetTagEntity(CoordinatorEntity[NetBoxAssetTagCoordinator]):
    """Base entity for NetBox Asset Tag."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NetBoxAssetTagCoordinator,
        attached_device_key: str,
    ) -> None:
        """Initialize the entity."""
        super().__init__(coordinator)
        self._attached_device_key = attached_device_key

    @property
    def matched_device(self) -> HomeAssistantDeviceMatch | None:
        """Return the current matched device payload."""
        return self.coordinator.data.get(self._attached_device_key)

    @property
    def available(self) -> bool:
        """Return whether the entity has current match data."""
        return self.coordinator.last_update_success and self.matched_device is not None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device information for an existing Home Assistant device."""
        match = self.matched_device
        if match is None:
            return None

        info: dict[str, Any] = {}
        identifiers = {entry for entry in match.ha_identifiers if len(entry) == 2}
        connections = {entry for entry in match.ha_connections if len(entry) == 2}
        if identifiers:
            info["identifiers"] = identifiers
        if connections:
            info["connections"] = connections
        if not info:
            return None

        # Enrich with the NetBox serial when the HA device has none yet, so it
        # shows up in the device card and can help HA merge device entries across
        # integrations that report the same hardware serial.
        if match.netbox_serial:
            device_entry = dr.async_get(self.hass).async_get(match.ha_device_id)
            if device_entry is None or not device_entry.serial_number:
                info["serial_number"] = match.netbox_serial

        return DeviceInfo(**info)
