"""Config flow for NetBox Asset Tag."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_NAME, CONF_SCAN_INTERVAL, CONF_TOKEN, CONF_URL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers import area_registry as ar, device_registry as dr
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import NetBoxApiClient, normalize_url
from .const import (
    CONF_MANUAL_OVERRIDES,
    CONF_ENABLE_WEAK_MATCHING,
    CONF_SYNC_FIELDS,
    CONF_VERIFY_SSL,
    DEFAULT_ENABLE_WEAK_MATCHING,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SYNC_FIELDS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    SYNC_FIELD_LOCATION,
    SYNC_FIELD_NAME,
    SYNC_FIELD_STATUS,
)
from .exceptions import NetBoxApiError, NetBoxAuthenticationError
from .models import NetBoxInventory, freeze_registry_entries, get_attached_device_key

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, str]:
    """Validate the config flow input."""
    session = async_create_clientsession(hass, verify_ssl=data[CONF_VERIFY_SSL])
    client = NetBoxApiClient(
        session=session,
        base_url=data[CONF_URL],
        token=data[CONF_TOKEN],
    )
    details = await client.async_validate()
    parsed_url = urlparse(data[CONF_URL])

    return {
        "title": data.get(CONF_NAME) or parsed_url.netloc or "NetBox",
        "unique_id": normalize_url(data[CONF_URL]),
        "device_count": str(details["count"]),
    }


class NetBoxAssetTagConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for NetBox Asset Tag."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> NetBoxAssetTagOptionsFlow:
        """Return the options flow."""
        return NetBoxAssetTagOptionsFlow(config_entry)

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the user step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_URL] = normalize_url(user_input[CONF_URL])

            try:
                info = await validate_input(self.hass, user_input)
            except NetBoxAuthenticationError:
                errors["base"] = "invalid_auth"
            except NetBoxApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception(
                    "Unexpected exception while validating NetBox Asset Tag config"
                )
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["unique_id"])
                self._abort_if_unique_id_configured()
                data = {
                    CONF_URL: user_input[CONF_URL],
                    CONF_TOKEN: user_input[CONF_TOKEN],
                    CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL],
                }
                options = {
                    CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                    CONF_ENABLE_WEAK_MATCHING: DEFAULT_ENABLE_WEAK_MATCHING,
                    CONF_SYNC_FIELDS: DEFAULT_SYNC_FIELDS,
                }
                title = user_input.get(CONF_NAME) or info["title"]
                return self.async_create_entry(title=title, data=data, options=options)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL): TextSelector(),
                    vol.Optional(CONF_NAME): TextSelector(),
                    vol.Required(CONF_TOKEN): TextSelector(
                        TextSelectorConfig(type=TextSelectorType.PASSWORD)
                    ),
                    vol.Required(
                        CONF_VERIFY_SSL,
                        default=DEFAULT_VERIFY_SSL,
                    ): BooleanSelector(),
                }
            ),
            errors=errors,
        )


class NetBoxAssetTagOptionsFlow(OptionsFlow):
    """Handle options for NetBox Asset Tag."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize the options flow."""
        self._config_entry = config_entry
        self._options = dict(config_entry.options)
        self._selected_attached_device_key: str | None = None
        self._inventory: NetBoxInventory | None = None

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show the options menu."""
        del user_input
        return self.async_show_menu(
            step_id="init",
            menu_options=["general", "manual_overrides"],
        )

    async def async_step_general(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage general integration options."""
        if user_input is not None:
            self._options.update(user_input)
            self._options.setdefault(CONF_MANUAL_OVERRIDES, self._get_manual_overrides())
            return self.async_create_entry(title="", data=self._options)

        return self.async_show_form(
            step_id="general",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self._options.get(
                            CONF_SCAN_INTERVAL,
                            DEFAULT_SCAN_INTERVAL,
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=MIN_SCAN_INTERVAL,
                            mode=NumberSelectorMode.BOX,
                            step=1,
                        )
                    ),
                    vol.Required(
                        CONF_ENABLE_WEAK_MATCHING,
                        default=self._options.get(
                            CONF_ENABLE_WEAK_MATCHING,
                            DEFAULT_ENABLE_WEAK_MATCHING,
                        ),
                    ): BooleanSelector(),
                    vol.Required(
                        CONF_SYNC_FIELDS,
                        default=self._options.get(CONF_SYNC_FIELDS, DEFAULT_SYNC_FIELDS),
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=SYNC_FIELD_STATUS, label="Status (active / inventory)"),
                                SelectOptionDict(value=SYNC_FIELD_LOCATION, label="Location (from HA area)"),
                                SelectOptionDict(value=SYNC_FIELD_NAME, label="Name (from HA device name)"),
                            ],
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    ),
                }
            ),
        )

    async def async_step_manual_overrides(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Show the manual override management menu."""
        del user_input
        menu_options = ["add_override"]
        if self._get_manual_overrides():
            menu_options.append("remove_override")
        return self.async_show_menu(
            step_id="manual_overrides",
            menu_options=menu_options,
        )

    async def async_step_add_override(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Choose the Home Assistant device to override."""
        if user_input is not None:
            self._selected_attached_device_key = user_input["attached_device_key"]
            return await self.async_step_add_override_target()

        options = await self._async_build_home_assistant_device_options()
        return self.async_show_form(
            step_id="add_override",
            data_schema=vol.Schema(
                {
                    vol.Required("attached_device_key"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_add_override_target(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Choose the NetBox target for a manual override."""
        if user_input is not None:
            overrides = self._get_manual_overrides()
            overrides[self._selected_attached_device_key or ""] = int(user_input["netbox_device_id"])
            self._options[CONF_MANUAL_OVERRIDES] = overrides
            return self.async_create_entry(title="", data=self._options)

        options = await self._async_build_netbox_device_options()
        return self.async_show_form(
            step_id="add_override_target",
            data_schema=vol.Schema(
                {
                    vol.Required("netbox_device_id"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    async def async_step_remove_override(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Remove an existing manual override."""
        if user_input is not None:
            overrides = self._get_manual_overrides()
            overrides.pop(user_input["attached_device_key"], None)
            self._options[CONF_MANUAL_OVERRIDES] = overrides
            return self.async_create_entry(title="", data=self._options)

        options = await self._async_build_existing_override_options()
        return self.async_show_form(
            step_id="remove_override",
            data_schema=vol.Schema(
                {
                    vol.Required("attached_device_key"): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            mode=SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
        )

    def _get_manual_overrides(self) -> dict[str, int]:
        """Return manual overrides normalized to a string->int mapping."""
        raw_overrides = self._options.get(CONF_MANUAL_OVERRIDES, {}) or {}
        overrides: dict[str, int] = {}
        for attached_device_key, netbox_device_id in raw_overrides.items():
            try:
                overrides[str(attached_device_key)] = int(netbox_device_id)
            except (TypeError, ValueError):
                continue
        return overrides

    async def _async_get_inventory(self) -> NetBoxInventory:
        """Fetch and cache the NetBox inventory for override selection."""
        if self._inventory is not None:
            return self._inventory

        client: NetBoxApiClient | None = (
            self.hass.data.get(DOMAIN, {})
            .get(self._config_entry.entry_id, {})
            .get("client")
        )
        if client is None:
            session = async_create_clientsession(
                self.hass,
                verify_ssl=self._config_entry.data[CONF_VERIFY_SSL],
            )
            client = NetBoxApiClient(
                session=session,
                base_url=self._config_entry.data[CONF_URL],
                token=self._config_entry.data[CONF_TOKEN],
            )

        self._inventory = await client.async_fetch_inventory()
        return self._inventory

    async def _async_build_home_assistant_device_options(self) -> list[SelectOptionDict]:
        """Return dropdown options for Home Assistant devices."""
        device_registry = dr.async_get(self.hass)
        area_registry = ar.async_get(self.hass)
        matched_device_keys = set(
            self.hass.data.get(DOMAIN, {})
            .get(self._config_entry.entry_id, {})
            .get("coordinator", {})
            .data.keys()
            if self.hass.data.get(DOMAIN, {}).get(self._config_entry.entry_id)
            else ()
        )

        sortable_options: list[tuple[bool, str, SelectOptionDict]] = []
        for device_entry in device_registry.devices.values():
            if device_entry.entry_type is not None:
                continue

            frozen_identifiers = freeze_registry_entries(device_entry.identifiers)
            frozen_connections = freeze_registry_entries(device_entry.connections)
            attached_device_key = get_attached_device_key(
                frozen_identifiers,
                frozen_connections,
                device_entry.id,
            )
            is_matched = attached_device_key in matched_device_keys
            area_name = ""
            if device_entry.area_id:
                area_entry = area_registry.async_get_area(device_entry.area_id)
                area_name = area_entry.name if area_entry else ""

            name = device_entry.name_by_user or device_entry.name or device_entry.id
            model = " ".join(
                part for part in (device_entry.manufacturer, device_entry.model) if part
            )
            label_parts = [name]
            if model:
                label_parts.append(model)
            if area_name:
                label_parts.append(area_name)
            label_parts.append("matched" if is_matched else "unmatched")
            label = " - ".join(label_parts)

            sortable_options.append(
                (
                    is_matched,
                    label.lower(),
                    SelectOptionDict(value=attached_device_key, label=label),
                )
            )

        sortable_options.sort(key=lambda item: (item[0], item[1]))
        return [option for _, __, option in sortable_options]

    async def _async_build_netbox_device_options(self) -> list[SelectOptionDict]:
        """Return dropdown options for NetBox devices."""
        inventory = await self._async_get_inventory()
        return [
            SelectOptionDict(value=str(device.device_id), label=device.display)
            for device in sorted(
                inventory.devices.values(),
                key=lambda device: device.display.lower(),
            )
        ]

    async def _async_build_existing_override_options(self) -> list[SelectOptionDict]:
        """Return dropdown options for existing manual overrides."""
        inventory = await self._async_get_inventory()
        device_registry = dr.async_get(self.hass)
        area_registry = ar.async_get(self.hass)
        labels_by_key: dict[str, str] = {}

        for device_entry in device_registry.devices.values():
            frozen_identifiers = freeze_registry_entries(device_entry.identifiers)
            frozen_connections = freeze_registry_entries(device_entry.connections)
            attached_device_key = get_attached_device_key(
                frozen_identifiers,
                frozen_connections,
                device_entry.id,
            )
            area_name = ""
            if device_entry.area_id:
                area_entry = area_registry.async_get_area(device_entry.area_id)
                area_name = area_entry.name if area_entry else ""
            device_name = device_entry.name_by_user or device_entry.name or device_entry.id
            if area_name:
                device_name = f"{device_name} - {area_name}"
            labels_by_key[attached_device_key] = device_name

        options: list[SelectOptionDict] = []
        for attached_device_key, netbox_device_id in sorted(self._get_manual_overrides().items()):
            netbox_device = inventory.devices.get(netbox_device_id)
            ha_label = labels_by_key.get(attached_device_key, attached_device_key)
            netbox_label = (
                netbox_device.display if netbox_device is not None else f"NetBox device {netbox_device_id}"
            )
            options.append(
                SelectOptionDict(
                    value=attached_device_key,
                    label=f"{ha_label} -> {netbox_label}",
                )
            )

        return options
