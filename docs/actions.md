# Device actions

The **Sync to NetBox** button calls `netbox_asset_tag.sync_to_netbox` for a
single matched Home Assistant device. The service can also take a `device_id`
list; with no list, it syncs all matched devices. By default, it syncs:

| NetBox field | Home Assistant source |
|--------------|-----------------------|
| `status` | `inventory` when disabled, otherwise `active` |
| `location` | Area name matched to a NetBox location |
| `name` | User-defined device name, otherwise registry name |
| `homeassistant_url` | Link to the HA device page |

The `homeassistant_url` custom field must already exist in NetBox. Use the
`ha_url_field` sync setting to rename the target field or deselect fields
under **Configure → Sync settings**. Auto-sync on area, name or disabled-state
changes is off by default and uses the same field selection.

Compatible Shelly devices with RPC-generation KVS support also get a
**Write asset tag to device** button. It stores the matched tag in the
`netbox-asset-tag` KVS key. This behavior is enabled by default but can be
disabled under **General settings**. The
`netbox_asset_tag.write_asset_tag_to_device` service optionally takes a
`device_id` list; omitted means all matched compatible devices. It returns
structured `written`, `skipped` and `errors` results.

`netbox_asset_tag.add_journal_entry` creates a NetBox journal entry for
**one** matched HA device. A `device_id` target is required; the service
cannot broadcast to all matched devices:

```yaml
action: netbox_asset_tag.add_journal_entry
data:
  device_id: <Home Assistant device ID>
  comments: Appliance maintenance completed.
  kind: success
```

`kind` defaults to `info` and accepts `info`, `success`, `warning` or
`danger`. The result contains the journal entry ID or an error.
