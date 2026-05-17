"""Sensor platform for NetBox Asset Tag."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_MATCHED_IDENTIFIERS,
    ATTR_MATCH_METHODS,
    ATTR_NETBOX_DEVICE_ID,
    ATTR_NETBOX_URL,
    ATTR_PRIMARY_MATCH_METHOD,
    DOMAIN,
)
from .coordinator import NetBoxAssetTagCoordinator
from .entity import NetBoxAssetTagEntity
from .registry import get_asset_tag_unique_id


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NetBox Asset Tag sensors from a config entry."""
    coordinator: NetBoxAssetTagCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]
    known_entities: set[str] = set()

    @callback
    def async_add_missing_entities() -> None:
        current_unique_ids: set[str] = set()
        new_entities: list[NetBoxAssetTagSensor] = []

        for match in coordinator.data.values():
            entity_unique_id = get_asset_tag_unique_id(
                config_entry.entry_id,
                match.ha_device_id,
            )
            current_unique_ids.add(entity_unique_id)
            if entity_unique_id in known_entities:
                continue

            known_entities.add(entity_unique_id)
            new_entities.append(
                NetBoxAssetTagSensor(
                    coordinator=coordinator,
                    ha_device_id=match.ha_device_id,
                    unique_id=entity_unique_id,
                )
            )

        known_entities.clear()
        known_entities.update(current_unique_ids)

        if new_entities:
            async_add_entities(new_entities)

    async_add_missing_entities()
    config_entry.async_on_unload(
        coordinator.async_add_listener(async_add_missing_entities)
    )


class NetBoxAssetTagSensor(NetBoxAssetTagEntity, SensorEntity):
    """Sensor representing a NetBox asset tag."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:tag"

    def __init__(
        self,
        coordinator: NetBoxAssetTagCoordinator,
        ha_device_id: str,
        unique_id: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, ha_device_id)
        self._attr_unique_id = unique_id

    @property
    def name(self) -> str:
        """Return the entity name."""
        return "NetBox Asset Tag"

    @property
    def native_value(self) -> str | None:
        """Return the asset tag."""
        match = self.matched_device
        if match is None:
            return None
        return match.netbox_asset_tag

    @property
    def extra_state_attributes(self) -> dict[str, str | int | list[str]]:
        """Return extra attributes for the matched NetBox device."""
        match = self.matched_device
        if match is None:
            return {}

        return {
            ATTR_NETBOX_URL: match.netbox_url,
            ATTR_NETBOX_DEVICE_ID: match.netbox_device_id,
            ATTR_MATCHED_IDENTIFIERS: list(match.matched_identifiers),
            ATTR_MATCH_METHODS: list(match.match_methods),
            ATTR_PRIMARY_MATCH_METHOD: match.match_methods[0] if match.match_methods else None,
        }
