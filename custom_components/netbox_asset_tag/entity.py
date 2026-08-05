"""Entity helpers for NetBox Asset Tag."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
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
        # Link directly to the matched device instead of copying its
        # identifiers/connections into DeviceInfo: a device now belongs to a
        # single config entry and no longer merges across integrations that
        # share identifiers (HA Core 2026.8, "single config entry per
        # device"). Serial-number enrichment moved to the coordinator, which
        # now writes it via device_registry.async_update_device directly.
        match = self.matched_device
        if match is not None:
            self.device_entry = dr.async_get(coordinator.hass).async_get(
                match.ha_device_id
            )

    @property
    def matched_device(self) -> HomeAssistantDeviceMatch | None:
        """Return the current matched device payload."""
        return self.coordinator.data.get(self._attached_device_key)

    @property
    def available(self) -> bool:
        """Return whether the entity has current match data."""
        return self.coordinator.last_update_success and self.matched_device is not None
