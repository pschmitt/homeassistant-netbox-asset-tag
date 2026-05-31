# NetBox Asset Tag for Home Assistant

`netbox_asset_tag` is a Home Assistant custom integration for NetBox that adds one metadata sensor to each matched Home Assistant device.

The sensor:

- attaches to an existing Home Assistant device,
- uses the NetBox asset tag as its state,
- exposes the NetBox device URL as an attribute,
- ignores Home Assistant devices that cannot be matched safely.

## Matching

The integration matches Home Assistant devices against NetBox using normalized hardware identifiers from:

- Home Assistant device `connections`: `mac`, `bluetooth`, `zigbee`
- Home Assistant device `identifiers`: values such as `zha` IEEE addresses and other EUI-like identifiers, including MAC-like substrings embedded in integration-specific IDs
- Home Assistant device `identifiers`: serial-like raw integration identifiers as a weaker fallback when no strict hardware identifier match exists
- NetBox device custom fields:
  - `zigbee_ieee`
  - `thread_eui64`
  - `lorawan_eui`
- NetBox interface MAC addresses on physical devices

When multiple candidate identifiers point at different NetBox devices, the Home Assistant device is ignored instead of guessing.

## Installation

### HACS

1. Open HACS.
2. Add `https://github.com/pschmitt/homeassistant-netbox-asset-tag` as a custom repository of type **Integration**.
3. Install **NetBox Asset Tag**.
4. Restart Home Assistant.

### Manual

Copy `custom_components/netbox_asset_tag` from this repository into:

```text
custom_components/netbox_asset_tag
```

## NetBox API token permissions

The token must belong to a NetBox user (or group) that has the following object-level permissions:

| Object type | Actions |
|---|---|
| `dcim.device` | `view`, `change` |
| `dcim.interface` | `view` |
| `dcim.macaddress` | `view` |
| `dcim.location` | `view` |

`view` on `dcim.device`, `dcim.interface`, and `dcim.macaddress` is required for the coordinator to match Home Assistant devices against NetBox inventory. `view` on `dcim.location` is required to resolve area-to-location mappings for the sync service. `change` on `dcim.device` is required only for the **Sync to NetBox** service and button; omit it if you do not use that feature.

> **Note:** As soon as any explicit object permission is assigned to a NetBox user, that user can only access objects covered by those permissions. If you assign fewer than the four rows above, the coordinator will fail to refresh and all entities will become unavailable.

## Configuration

The integration is configured from the Home Assistant UI:

1. Go to **Settings -> Devices & services**.
2. Add **NetBox Asset Tag**.
3. Enter the NetBox URL and API token.
4. Optionally enable **weaker serial matching from raw integration identifiers** in the integration options if you want it to consider integration-specific device IDs.

## Entity model

Each matched device gets diagnostic entities:

### Asset tag sensor

- **State**: the NetBox asset tag, e.g. `#AQA-1002`
- **Attributes**:
  - `netbox_url`
  - `netbox_device_id`
  - `matched_identifiers`
  - `match_methods`
  - `primary_match_method`
  - `weak_match`
  - `manual_override`

### Sync to NetBox button

Pressing the button calls the `netbox_asset_tag.sync_to_netbox` service scoped to that single device. See [Sync service](#sync-service) below.

### Write asset tag to device button

Compatible physical devices also get a **Write asset tag to device** button. Pressing it stores the matched NetBox asset tag on the device itself.

This feature is enabled by default and can be disabled under **General settings → Enable writing asset tags to compatible devices**.

Current device writer backend:

| Device/integration | Compatibility | Storage |
|---|---|---|
| Shelly | Loaded RPC-generation, non-sleeping Shelly devices with KVS support | KVS key `netbox-asset-tag` |

## Sync service

The integration exposes a `netbox_asset_tag.sync_to_netbox` service that pushes the current Home Assistant device state back to NetBox:

| Field synced | Source | NetBox field |
|---|---|---|
| Status | `disabled_by` is set → `inventory`, otherwise → `active` | `status` |
| Location | HA area name matched against NetBox location names (emoji stripped, case-insensitive) | `location` |
| Name | `name_by_user` if set, otherwise `name` from HA device registry | `name` |
| HA device URL | `{ha_external_url}/config/devices/device/{device_id}` | custom field (configurable, default `homeassistant_url`) |

All four fields are synced by default. The `homeassistant_url` custom field must already exist in NetBox for the HA device URL to be written (see [NetBox setup](#netbox-setup) below). Use `ha_url_field` in Sync settings to change the custom field name. Deselect individual fields under **Settings → Devices & services → NetBox Asset Tag → Configure → Sync settings**.

You can deselect individual fields in **Sync settings → Fields to sync to NetBox**.

The service accepts an optional `device_id` list. Leave it empty to sync all coordinator-matched devices.

## Device asset-tag write service

The integration exposes a `netbox_asset_tag.write_asset_tag_to_device` service that writes the matched NetBox asset tag to compatible physical devices. It uses the same coordinator matching as the sensor and buttons.

The service accepts an optional `device_id` list. Leave it empty to write all coordinator-matched compatible devices.

The service returns a structured response:

```yaml
written:
  - ha_device_name: …
    netbox_asset_tag: "#SLY-0001"
    backend: shelly
    key: netbox-asset-tag
skipped:
  - ha_device_name: …
    reason: device_not_supported
errors:
  - ha_device_name: …
    error: …
```

## Auto-sync

Enable **Auto-sync on device changes** under **Sync settings** to have devices pushed to NetBox automatically whenever any of the following changes in Home Assistant:

- area assignment (→ location)
- device name or user-defined name (→ name)
- disabled state (→ status)

Auto-sync is off by default. It reuses the same sync logic and respects the **Fields to sync** selection.

The service returns a structured response:

```yaml
synced:
  - ha_device_name: …
    netbox_asset_tag: …
    changes: {status: active, location: 16}
    ha_area: Master Bathroom        # present when area is set
    location_unmatched: true        # present when no NetBox location matched
skipped:
  - ha_device_name: …
    reason: no_coordinator_match    # or device_not_in_registry
errors:
  - ha_device_name: …
    error: …
```

## Branding

This repository bundles NetBox logo assets sourced from the upstream NetBox project. NetBox and related marks belong to their respective owners. The integration code is GPL-3.0, but the bundled third-party logos are not relicensed under GPL.
