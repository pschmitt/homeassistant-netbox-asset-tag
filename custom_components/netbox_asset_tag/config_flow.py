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
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import NetBoxApiClient, normalize_url
from .const import (
    CONF_ENABLE_WEAK_MATCHING,
    CONF_VERIFY_SSL,
    DEFAULT_ENABLE_WEAK_MATCHING,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)
from .exceptions import NetBoxApiError, NetBoxAuthenticationError

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

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage integration options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        default=self._config_entry.options.get(
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
                        default=self._config_entry.options.get(
                            CONF_ENABLE_WEAK_MATCHING,
                            DEFAULT_ENABLE_WEAK_MATCHING,
                        ),
                    ): BooleanSelector(),
                }
            ),
        )
