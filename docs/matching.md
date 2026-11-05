# Device matching

The integration matches Home Assistant devices against NetBox devices using
normalized hardware identifiers from registry `connections` (`mac`,
`bluetooth`, `zigbee`), registry identifiers (such as ZHA IEEE addresses),
NetBox interface MAC addresses and NetBox custom fields `zigbee_ieee`,
`thread_eui64` and `lorawan_eui`. Optional weaker serial matching from raw
integration identifiers can be enabled in the integration options. When
candidates point to different NetBox devices, the integration ignores the
Home Assistant device instead of guessing.

## NetBox token permissions

The token's NetBox user or group needs these object-level permissions:

| Object | Actions | Purpose |
|--------|---------|---------|
| `dcim.device` | `view` | Match devices |
| `dcim.interface` | `view` | Match interface MACs |
| `dcim.macaddress` | `view` | Match assigned MACs |
| `dcim.location` | `view` | Resolve areas for optional sync |
| `dcim.device` | `change` (optional) | Sync HA device details |
| `extras.journalentry` | `add` (optional) | Add journal entries |

With explicit object permissions, the user can access only covered objects.
The device, interface and MAC-address view permissions are required for
matching; location view is needed when syncing area-to-location data. Omit
the write permissions if you do not use their corresponding actions.

## Asset tag entities

Each matched device gets a diagnostic sensor whose state is the asset tag and
whose attributes include `netbox_url`, `netbox_device_id`,
`matched_identifiers`, `match_methods`, `primary_match_method`, `weak_match`
and `manual_override`.
