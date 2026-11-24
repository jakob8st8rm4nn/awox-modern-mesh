# Provisioning (factory devices / remote controls)

**Connect directly to the factory device**, not to another mesh gateway. Read
its advertisement first, obtain the current factory credentials via
`factory_credentials(mac, model_lookup_code, firmware, name=...)`, and use the
existing target mesh's 16-byte network key. Example 26 uses the name observed
in the remote's advertisement. Example 27 assumes the factory lamp accepts
the default name `unpaired`.

## High-level, APK-style workflow

```python
from awox import AwoXMeshSession, ProvisioningSettings

# current contains the factory credentials for the direct device.
# settings contains the target mesh credentials and the existing 16-byte key.
async with AwoXMeshSession(lambda: proxy.create_transport(remote_mac), current) as mesh:
    result = await mesh.provision(
        current_id, settings,
        groups=ordered_groups_or_none,
        timeout=20.0,
        provisioning_byte=observed_provisioning_byte,
    )
    print(result.completed, result.mesh_id)
```

`provision()` performs one explicit attempt using the SAME connection owner as
other commands: optional `0x0C` list write **without a positive ACK gate**,
Pair04/05, Pair07 validation, network parameters 0x03, key 0x04 and a bounded
0x83 completion window. It captures a separately received 0x0B new address.
If `provisioning_byte == 0xA0`, the observed APK branch skips the normal 03/04
writes; do not infer successful 0x83 completion in that branch.

The timeout must be greater than zero and at most 60 seconds. The default
`timeout=20.0` is **only the deadline for observing the final 0x83 completion
reply**, measured after its outbound GATT write. It is **not** a 20-second
limit for the whole provisioning attempt. The optional group write, credential
writes, Pair07 read, network parameters and connection cleanup may take
additional time under their separate transport/read limits. A timeout does not
establish whether a device applied the settings. Do not retry automatically.

**Results are observations, not proven working hardware.** `completed=False`
means no observed standard completion; it also applies to the special 0xA0
branch. A missing or negative 0x0C response does **not** block the next
requested setup step. A missing or invalid Pair07 result stops the sequence. The direct session
closes after an attempted sequence because the active credentials may have
changed. No retries, rollback, cloud registration, lamp group membership edits
or timing delays are performed automatically.

For ERCU-3groups-Zm, supply three ordered group addresses through `groups=`;
its network `group_address` field is zero. For ERCU-Zm and ERCU-WS-Zm, place the
single button group in `ProvisioningSettings(group_address=...)` and pass
`groups=None`. The device model is *not* inferred by `provision()`; the example
uses the scanned model code to choose the intended mapping. For lamps, do not
write a remote group list unless the device/application explicitly requires it.

## Explicit single steps

These same operations also remain separately available and **do not impose an
ACK gate or automatically continue setup**:

- `set_mesh_credentials(name, password)` sends Pair04/05.
- `read_pair_response()` reads the actual Pair07 characteristic when requested.
- `write_mesh_groups(mesh_id, addresses)` sends the ordered 0x0C group list.
- `set_network_parameters(settings)` builds and sends the APK 0x03 payload.
- `set_network_key(key)` builds and sends the APK 0x04 payload.
- `send_and_track_reply(frame, 0x83, timeout=...)` captures a completion window.

The codecs expose the APK mapping from the network name to the network ID
and extended network ID. The device's mesh address is a separate value.
The 0x0B address response is a separate notification; group-ACK addresses for
factory mesh ID 0 may appear as 0xFFFF, an exception used only for a group
ACK wait. To observe this reply from a directly connected factory device, use
`send_and_track_reply(set_mesh_groups(0, addresses), 0x0C, target=0, factory=True)`
with the frame builder from `awox.groups`, then await the receipt once. This call
sends the frame itself. The session's `set_mesh_groups()` convenience method
matches the requested target address and does not enable the factory exception.

Example 26 waits one second before the credential/network steps for
all three supported remote models. For ERCU-3groups-Zm it first writes the
three ordered groups explicitly, then calls `provision(..., groups=None)` after
the pause. The other two models carry their one group in network parameters.
Example 27 shows the same wizard pause for a lamp without a group write.

## Mesh removal

`remove_from_mesh(mesh_id)` sends one 0x01 removal command. It is not a proven
factory reset. Any later enrollment is a separate explicit decision.
