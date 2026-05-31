"""Device-side asset-tag writers for NetBox Asset Tag."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import DEFAULT_DEVICE_ASSET_TAG_KEY

SHELLY_DOMAIN = "shelly"
SHELLY_SERVICE_SET_KVS_VALUE = "set_kvs_value"


@dataclass(slots=True, frozen=True)
class DeviceAssetTagWriteResult:
    """Result of writing an asset tag to a physical device."""

    backend: str
    key: str


class DeviceAssetTagWriterError(Exception):
    """Base class for device writer errors."""


class DeviceAssetTagWriterUnsupported(DeviceAssetTagWriterError):
    """Raised when no compatible writer exists for the device."""


class DeviceAssetTagWriterFailed(DeviceAssetTagWriterError):
    """Raised when a compatible writer failed to write the value."""


def _is_supported_shelly_config_entry(config_entry: ConfigEntry) -> bool:
    """Return whether a Shelly config entry supports KVS writes."""
    if config_entry.domain != SHELLY_DOMAIN:
        return False
    if config_entry.state is not ConfigEntryState.LOADED:
        return False

    try:
        from aioshelly.const import RPC_GENERATIONS  # noqa: PLC0415
        from homeassistant.components.shelly.const import CONF_SLEEP_PERIOD  # noqa: PLC0415
        from homeassistant.components.shelly.utils import get_device_entry_gen  # noqa: PLC0415
    except ImportError:
        return False

    if get_device_entry_gen(config_entry) not in RPC_GENERATIONS:
        return False
    return config_entry.data.get(CONF_SLEEP_PERIOD, 0) <= 0


def device_supports_asset_tag_write(
    hass: HomeAssistant,
    device_id: str,
) -> bool:
    """Return whether the device has a compatible asset-tag writer backend."""
    if not hass.services.has_service(SHELLY_DOMAIN, SHELLY_SERVICE_SET_KVS_VALUE):
        return False

    device_entry = dr.async_get(hass).async_get(device_id)
    if device_entry is None:
        return False

    for entry_id in device_entry.config_entries:
        config_entry = hass.config_entries.async_get_entry(entry_id)
        if config_entry is None:
            continue
        if _is_supported_shelly_config_entry(config_entry):
            return True

    return False


async def async_write_asset_tag_to_device(
    hass: HomeAssistant,
    device_id: str,
    asset_tag: str,
) -> DeviceAssetTagWriteResult:
    """Write an asset tag to a compatible device."""
    if not device_supports_asset_tag_write(hass, device_id):
        raise DeviceAssetTagWriterUnsupported(
            "device has no compatible asset-tag writer backend"
        )

    try:
        await hass.services.async_call(
            SHELLY_DOMAIN,
            SHELLY_SERVICE_SET_KVS_VALUE,
            {
                ATTR_DEVICE_ID: device_id,
                "key": DEFAULT_DEVICE_ASSET_TAG_KEY,
                "value": asset_tag,
            },
            blocking=True,
        )
    except HomeAssistantError as err:
        raise DeviceAssetTagWriterFailed(str(err)) from err

    return DeviceAssetTagWriteResult(
        backend=SHELLY_DOMAIN,
        key=DEFAULT_DEVICE_ASSET_TAG_KEY,
    )
