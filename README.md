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

## Configuration

The integration is configured from the Home Assistant UI:

1. Go to **Settings -> Devices & services**.
2. Add **NetBox Asset Tag**.
3. Enter the NetBox URL and API token.
4. Optionally enable **weaker serial matching from raw integration identifiers** in the integration options if you want it to consider integration-specific device IDs.

## Entity model

- **Device**: reuses the existing Home Assistant device
- **Entity**: one sensor per matched device
- **State**: the NetBox asset tag, such as `#AQA-1002`
- **Attributes**:
  - `netbox_url`
  - `netbox_device_id`
  - `matched_identifiers`
  - `match_methods`
  - `primary_match_method`
  - `weak_match`

## Branding

This repository bundles NetBox logo assets sourced from the upstream NetBox project. NetBox and related marks belong to their respective owners. The integration code is GPL-3.0, but the bundled third-party logos are not relicensed under GPL.
