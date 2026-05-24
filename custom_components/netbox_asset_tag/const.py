"""Constants for NetBox Asset Tag."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "netbox_asset_tag"
PLATFORMS: list[Platform] = [Platform.BUTTON, Platform.SENSOR]

CONF_VERIFY_SSL = "verify_ssl"
CONF_ENABLE_WEAK_MATCHING = "enable_weak_matching"
CONF_MANUAL_OVERRIDES = "manual_overrides"
CONF_SYNC_FIELDS = "sync_fields"
CONF_HA_URL_FIELD = "ha_url_field"

SYNC_FIELD_STATUS = "status"
SYNC_FIELD_LOCATION = "location"
SYNC_FIELD_NAME = "name"
SYNC_FIELD_HA_URL = "ha_url"
DEFAULT_SYNC_FIELDS: list[str] = [SYNC_FIELD_STATUS, SYNC_FIELD_LOCATION, SYNC_FIELD_NAME]
DEFAULT_HA_URL_FIELD = "homeassistant_url"

DEFAULT_SCAN_INTERVAL = 1800
MIN_SCAN_INTERVAL = 300
DEFAULT_VERIFY_SSL = True
DEFAULT_ENABLE_WEAK_MATCHING = False

DEFAULT_REQUEST_TIMEOUT = 20
API_PAGE_SIZE = 250
API_DEVICES_PATH = "/api/dcim/devices/"
API_INTERFACES_PATH = "/api/dcim/interfaces/"
API_LOCATIONS_PATH = "/api/dcim/locations/"
API_MAC_ADDRESSES_PATH = "/api/dcim/mac-addresses/"

SERVICE_SYNC_TO_NETBOX = "sync_to_netbox"

ATTR_MATCHED_IDENTIFIERS = "matched_identifiers"
ATTR_MATCH_METHODS = "match_methods"
ATTR_PRIMARY_MATCH_METHOD = "primary_match_method"
ATTR_NETBOX_DEVICE_ID = "netbox_device_id"
ATTR_NETBOX_URL = "netbox_url"
ATTR_WEAK_MATCH = "weak_match"
ATTR_MANUAL_OVERRIDE = "manual_override"
