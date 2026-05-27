"""Button platform for NetBox Asset Tag."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.components.persistent_notification import async_create as pn_create
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SERVICE_SYNC_TO_NETBOX
from .coordinator import NetBoxAssetTagCoordinator
from .entity import NetBoxAssetTagEntity
from .registry import get_sync_button_unique_id


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NetBox sync buttons from a config entry."""
    coordinator: NetBoxAssetTagCoordinator = hass.data[DOMAIN][config_entry.entry_id][
        "coordinator"
    ]
    known_entities: set[str] = set()

    @callback
    def async_add_missing_entities() -> None:
        current_unique_ids: set[str] = set()
        new_entities: list[NetBoxSyncButton] = []

        for attached_device_key in coordinator.data:
            entity_unique_id = get_sync_button_unique_id(
                config_entry.entry_id,
                attached_device_key,
            )
            current_unique_ids.add(entity_unique_id)
            if entity_unique_id in known_entities:
                continue

            known_entities.add(entity_unique_id)
            new_entities.append(
                NetBoxSyncButton(
                    coordinator=coordinator,
                    attached_device_key=attached_device_key,
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


class NetBoxSyncButton(NetBoxAssetTagEntity, ButtonEntity):
    """Button that syncs this device's HA state to NetBox."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:cloud-sync"
    _attr_translation_key = "sync_to_netbox"

    def __init__(
        self,
        coordinator: NetBoxAssetTagCoordinator,
        attached_device_key: str,
        unique_id: str,
    ) -> None:
        """Initialize the button."""
        super().__init__(coordinator, attached_device_key)
        self._attr_unique_id = unique_id

    @property
    def name(self) -> str:
        """Return the entity name."""
        return "Sync to NetBox"

    async def async_press(self) -> None:
        """Call sync_to_netbox for this device and notify with the result."""
        match = self.matched_device
        if match is None:
            return

        response = await self.hass.services.async_call(
            DOMAIN,
            SERVICE_SYNC_TO_NETBOX,
            {"device_id": [match.ha_device_id]},
            blocking=True,
            return_response=True,
        ) or {}

        synced = response.get("synced", [])
        errors = response.get("errors", [])
        skipped = response.get("skipped", [])

        lines: list[str] = []

        for entry in synced:
            changes = entry.get("changes", {})
            parts: list[str] = []

            def _diff(ch: dict) -> str:
                old, new = ch.get("old"), ch["new"]
                if old is not None and old != new:
                    return f"~~{old}~~ → **{new}**"
                return f"**{new}**"

            if "status" in changes:
                parts.append(f"- status: {_diff(changes['status'])}")
            if "name" in changes:
                parts.append(f"- name: {_diff(changes['name'])}")
            if "ha_url" in changes:
                ch = changes["ha_url"]
                parts.append(f"- ha_url → {ch['new']}")
            loc_name = entry.get("location_name")
            if loc_name:
                old_loc = entry.get("old_location_name")
                if old_loc and old_loc != loc_name:
                    parts.append(f"- location: ~~{old_loc}~~ → **{loc_name}**")
                else:
                    parts.append(f"- location: **{loc_name}**")
            elif entry.get("location_unmatched"):
                parts.append(f"- location → no match for area *{entry.get('ha_area', '?')}*")
            if parts:
                lines.append("✅ Synced:\n" + "\n".join(parts))
            else:
                lines.append("✅ Synced (no changes)")

        for entry in errors:
            lines.append(f"❌ Error: {entry.get('error', 'unknown error')}")

        for entry in skipped:
            reason = entry.get("reason", "skipped").replace("_", " ")
            lines.append(f"⚠️ Skipped: {reason}")

        if not lines:
            lines = ["Nothing to sync"]

        lines.append(f"[Open in NetBox]({match.netbox_url})")

        pn_create(
            self.hass,
            "\n\n".join(lines),
            title=f"NetBox sync — {match.netbox_asset_tag}",
            notification_id=f"netbox_sync_{match.ha_device_id}",
        )
