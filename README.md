<p align="center">
  <img src="logo.png" width="128" alt="NetBox Asset Tag logo">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/marketplace_repository/?owner=pschmitt&amp;repository=homeassistant-netbox-asset-tag&amp;category=integration"><img src="https://my.home-assistant.io/badges/marketplace_repository.svg" alt="Open this integration in Home Assistant Marketplace"></a>
</p>

<h1 align="center">NetBox Asset Tag for Home Assistant</h1>

<p align="center">Attach NetBox asset tags to matched Home Assistant devices and optionally sync device metadata.</p>

## Features

- **Safe matching:** Compare hardware identifiers against NetBox and skip ambiguous devices. See [Device matching](docs/matching.md).
- **Asset tag sensors:** Display a tag and NetBox URL on each matched Home Assistant device.
- **Optional synchronization:** Update NetBox status, location, name and device URL from Home Assistant. See [Device actions](docs/actions.md).
- **Device and journal actions:** Write tags to compatible Shelly devices or create a journal entry for one matched device.

## Install

Use the Marketplace badge above on Home Assistant 2026.11 or later to add this
repository as a custom integration. On older versions, add it as a HACS
custom repository of type **Integration**. Install and restart Home Assistant.
The badge does not imply a public catalog listing. For manual installation,
copy `custom_components/netbox_asset_tag/` into Home Assistant's
`custom_components/` directory and restart.

## Quick start

1. Create a NetBox token with the required view permissions listed in [Device matching](docs/matching.md).
2. Add **NetBox Asset Tag** under **Settings → Devices & services → Add integration**.
3. Enter the NetBox URL and API token, then inspect a matched device's asset tag sensor.

## Documentation

| Topic | Description |
|-------|-------------|
| [Device matching](docs/matching.md) | Identifiers, token permissions and sensor attributes |
| [Device actions](docs/actions.md) | Sync, device-writing and journal services |

## License

[GPL-3.0](LICENSE). NetBox logos belong to their respective owners and are not
relicensed under GPL.
