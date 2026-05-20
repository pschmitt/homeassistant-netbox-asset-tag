"""Constants for NetBox Asset Tag."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "netbox_asset_tag"
PLATFORMS: list[Platform] = [Platform.SENSOR]

CONF_VERIFY_SSL = "verify_ssl"
CONF_ENABLE_WEAK_MATCHING = "enable_weak_matching"
CONF_MANUAL_OVERRIDES = "manual_overrides"

DEFAULT_SCAN_INTERVAL = 1800
MIN_SCAN_INTERVAL = 300
DEFAULT_VERIFY_SSL = True
DEFAULT_ENABLE_WEAK_MATCHING = False

DEFAULT_REQUEST_TIMEOUT = 20
API_PAGE_SIZE = 250
API_DEVICES_PATH = "/api/dcim/devices/"
API_INTERFACES_PATH = "/api/dcim/interfaces/"

ATTR_MATCHED_IDENTIFIERS = "matched_identifiers"
ATTR_MATCH_METHODS = "match_methods"
ATTR_PRIMARY_MATCH_METHOD = "primary_match_method"
ATTR_NETBOX_DEVICE_ID = "netbox_device_id"
ATTR_NETBOX_URL = "netbox_url"
ATTR_WEAK_MATCH = "weak_match"
ATTR_MANUAL_OVERRIDE = "manual_override"
