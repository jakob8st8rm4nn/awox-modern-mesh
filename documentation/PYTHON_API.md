# Python API and response windows

## Session and targets

`AwoXMeshSession(transport_factory, credentials, devices=None, ...)` performs no
I/O until `connect()` or async-context entry. The callbacks `on_notification`,
`on_status`, `on_mesh_status`, `on_disconnect` are synchronous. Callback
exceptions are logged and isolated from session processing. `lamp(id)` returns a typed `Lamp`; `group(address)` and
`broadcast()` return typed `MeshTarget`. This enables method suggestions in
editors such as Pylance.

## Command naming

- `set_...` changes a setting. It waits for a reply only for commands whose
  documented contract needs a reply. Common lighting, PIR and Quiet Mode
  operations are send-only.
- `write_...` is offered *in addition* for `set_mesh_groups`,
  `set_power_cut_mode`, `set_presence_simulator`, and `set_time_with_timezone`.
  These alternatives send without a device response wait.
- `read_...` actively queries the device and waits for its response.
- `get_...` returns observations already cached and performs no GATT I/O.
- `set_power(True/False)` controls power using one boolean argument.
- `save_scene()` and `recall_scene()` intentionally remain separate actions.

`set_dual_zone_power(destination, zone, enabled)` uses a `bool`, just like
`set_power`. The raw on-wire state 2 remains accessible via the pure
`lighting.dual_zone_power()` builder, without inventing its meaning. Native
brightness accepts 1..255 for both regular and Dual-Zone commands. Both
percentage methods map 0..100% to the APK's 2..254 range. Native color uses
hue 0..254 and saturation 0..255. Temperature uses 153..454 mired. Kelvin is converted to mired. There is **no public
percent-based Dual-Zone color-temperature setter**.

## Status queries

Use `await lamp.read_status()` to wait for a status result or
`await lamp.request_status()` to send once and observe any later reply through
the cache or callbacks. `await mesh.request_status(destination)` also accepts
group and broadcast addresses. Use `awox.status.status_query(destination)`
to build the same 0x0A frame without sending it.

## ACK-waiting convenience methods

`set_mesh_groups(..., timeout=5)` returns `MeshGroupSetResponse | None`.
For the explicit factory ID 0 / FFFF ACK exception, see [Provisioning](PROVISIONING.md#explicit-single-steps).
`set_power_cut_mode(..., timeout=5)` returns `PowerCutSetResponse | None`.
`set_presence_simulator(..., timeout=15)` returns `PresenceSetResponse | None`.
None means no matching device reply within the observation window, not success.
A nonzero status code may indicate a negative device response. No implicit
readback, retry, rollback or acknowledgement for other group members occurs.

`set_timer()` and `set_program()` each send one 0x33 record and return
`ScheduleWriteResult`. `set_nightlight()` and `set_dawn_simulator()` handle the
APK's two-part sequence and normalize the outgoing part markers (0x10, 0x11).
**The second part is transmitted only after a 0x99 response to the first**.
`read_nightlight()` and `read_dawn_simulator()` read a valid first part before
asking for the second; a missing part is not interpreted as an empty setting.
Paired operations share one deadline starting after acquisition of the
per-device schedule lock. Both parts must start their GATT write and receive any reply before that
deadline. A write already in progress retains its own transport time limit.
For paired writes, `end_sent` indicates that the second GATT write completed,
even if its device reply was absent. `set_schedule_part()` exposes a single write for
callers who explicitly own their own flow.

`set_time()` performs a 0x30 write without an ACK wait.
`write_time_with_timezone()` sends 0x29 and returns after the GATT write.
`set_time_with_timezone(..., timeout=5)` waits for a 0x29 status and returns
`Time29Ack | None`. The reply timeout must be greater than zero and at most
60 seconds. The GATT watchdog and time spent waiting for the write lock are
separate. [Example 20](../examples/app_20_sync_time_with_timezone.py)
runs `set_time_with_timezone()` as a task and starts `set_time()` about 250 ms
later, independently of the 0x29 result. Both commands use the same timestamp.
The example requires MTU 43 or higher and has no automatic MTU fallback.
It checks the wire format before connecting and refreshes the timestamp and
UTC offset after login. Supply a valid POSIX rule for the local timezone. The
builder checks only the encoded format and length of the rule.
For caller-built frames, `send_and_track_reply()` exposes a `Receipt` directly.
The 0x29 reply has no transaction identifier.

## Provisioning timeout

`provision(mesh_id, settings, timeout=20.0, ...)` performs a full explicit
provisioning attempt. The `timeout` must be greater than zero and at most 60
seconds. It bounds **only the final 0x83
completion-reply window** after the key write; it does not bound the earlier
optional group write, credentials, Pair07 read, network parameters, or cleanup.
Each preceding step uses its own transport/read limits. An absent 0x83 result
is not proof that the device stayed unconfigured; avoid automatic retries.
See [Provisioning](PROVISIONING.md) for the complete sequence and 0xA0 branch.

## Explicit response tracking

`send(frame)` encrypts the frame with the session key and performs one GATT
write after mesh login. It does not wait for a device response. `send_and_track_reply(frame, opcode, target=None, routine=None,
timeout=15, factory=False)` creates a `Receipt` and writes once. It arms the
observation before the actual GATT write, so early responses are captured.
`await receipt.wait()` returns an `ExtendedNotification | None` or propagates
connection failure. `wait(timeout=...)` may **shorten** but never extend the
original answer window. Use one waiter per receipt. A timeout or cancellation
of an active wait ends response tracking for the receipt, including for any
other caller waiting on it. Calling `wait()` again cannot capture a response
that arrives after tracking ends. Deadlines begin after the completed GATT write.
Overlapping concurrent windows are rejected (wildcard selectors and 0x80/0x82
status aliases included), and a single incoming message can satisfy at most
one receipt. A receive handler running after the absolute deadline cannot
accept a late reply even if an event-loop timer callback was delayed.
A matched response is a local observation, not a cryptographically
correlated transaction ID.

`factory=True` only permits the factory ID0/FFFF 0x0C group ACK exception.
It is not a general bypass of address filtering.

## Provisioning

`await mesh.provision(mesh_id, settings, *, groups=None, timeout=20,
provisioning_byte=None)` is a high-level, *direct-device* enrollment workflow:
optional 0x0C group-list write (no positive-ACK gate) → Pair04/05 → Pair07
check → 0x03 network fields → 0x04 key → observe 0x83. Caller-provided `provisioning_byte=0xA0`
skips normal 0x03/0x04 sends as observed in the APK. The result is
`ProvisioningResult(completed, mesh_id)`. The direct session is closed after
any attempted sequence, including an error, so the current login cannot be reused
after credentials change. The library never scans for factory metadata, chooses
models or accounts, sleeps for the wizard timer, or retries/rolls back.

Single-step `write_mesh_groups()`, `set_mesh_credentials()`,
`read_pair_response()`, `set_network_parameters()` and `set_network_key()`
remain available. Example 26 waits one second before `provision()` for all
three supported remote models. On the three-group model it first writes the
ordered list explicitly. This timing belongs to the example.

## Notification contract

`on_notification` receives the decrypted **raw** `ExtendedNotification` created
by `awox.frames.decode_notification`: use `opcode` and `payload`; `value` is
the unchanged payload bytes. `kind` is `raw` for general messages and
`mesh_status_raw` for 0x80/0x82; neither is a device-success claim. The
0x37 message is visible to raw listeners rather than silently filtered.

`read_...` and confirmation-waiting `set_...` operations use their own
validated family parsers and return documented domain results or `None`.
The separate, explicitly named `awox.session.decode_apk_notification` exists
for inspecting APK reference response classifications; it is **not** used by
the live callback or as a second live decoder. For the raw receive envelope
use `awox.frames.decode_notification`.


## Observable contracts for public convenience operations

The table describes the implemented operations. A tracked reply of “None”
means the coroutine finishes after the transport write, without waiting for a
mesh reply or verifying a physical change. BLE errors propagate.
Methods on `lamp` use its mesh ID; Session-level methods take a destination
where shown. No command is retried automatically.

| Method | Writes / steps | Tracked reply | Return if observed / absent |
| --- | --- | --- | --- |
| `set_power()` | One control power write | None | `None` after write |
| `set_brightness()` | One brightness write; percent conversion | None | `None` after write |
| `set_brightness_native()` | One native-brightness write | None | `None` after write |
| `set_rgb()` | One RGB-to-native color write | None | `None` after write |
| `set_color_native()` | One native color write | None | `None` after write |
| `set_color_temperature()` | Kelvin conversion and one white write | None | `None` after write |
| `set_color_temperature_mired()` | One native mired white write | None | `None` after write |
| `set_candle_mode()` | One effect write | None | `None` after write |
| `set_color_cycle()` | One effect write | None | `None` after write |
| `save_scene()` / `recall_scene()` | One scene write each | None | `None` after write |
| `set_dual_zone_power()` | One 0x52-based zone power write | None | `None` after write |
| `set_dual_zone_brightness()` | One 0x52-based zone percent brightness write | None | `None` after write |
| `set_dual_zone_brightness_native()` | One 0x52-based zone native brightness write | None | `None` after write |
| `set_dual_zone_rgb()` | One 0x52-based zone RGB color write | None | `None` after write |
| `set_dual_zone_color_native()` | One 0x52-based zone native color write | None | `None` after write |
| `set_dual_zone_color_temperature()` | Kelvin converted to mired, one zone write | None | `None` after write |
| `set_dual_zone_color_temperature_mired()` | One zone mired write | None | `None` after write |
| `set_mesh_groups()` | One 0x0C group write | Addressed 0x0C | `MeshGroupSetResponse` / `None` on timeout |
| `write_mesh_groups()` | One 0x0C group write | None | `None` after write |
| `set_power_cut_mode()` | One 0x42 mode write | Addressed 0x42 | `PowerCutSetResponse` / `None` on timeout |
| `write_power_cut_mode()` | One 0x42 mode write | None | `None` after write |
| `set_timer()` | One 0x33, routine 2 | 0x33/routine 2 | `ScheduleWriteResult`; missing ACK in its fields |
| `set_program()` | One 0x33, routine 3 | 0x33/routine 3 | `ScheduleWriteResult`; missing ACK in its fields |
| `set_nightlight()` | 0x33 routine 5; routine 6 only after 0x99 | 0x33 per sent part | `ScheduleWriteResult`; reports unsent/unanswered part |
| `set_dawn_simulator()` | 0x33 routine 7; routine 8 only after 0x99 | 0x33 per sent part | `ScheduleWriteResult`; reports unsent/unanswered part |
| `set_schedule_part()` | One 0x33 routine write | None | `None` after write; caller decides follow-up |
| `set_presence_simulator()` | One 0x3B config write | Addressed 0x3B, routine 1 | `PresenceSetResponse` / `None` on timeout |
| `write_presence_simulator()` | One 0x3B config write | None | `None` after write |
| `set_pir_settings()` | One unaddressed 0x11 config write | None | `None` after write |
| `set_quiet_mode()` | One 0x40 write | None (0x40 observations are not causally matched) | `None` after write |
| `set_time()` | One 0x30 clock write | None | `None` after write |
| `set_time_with_timezone()` | One 0x29 time-rule write | 0x29 | `Time29Ack` / `None` on timeout |
| `write_time_with_timezone()` | One 0x29 time-rule write | None | `None` after write |
| `set_mesh_credentials()` | Pair04/05 credential writes | No notification wait; Pair07 must be read separately | `None` after writes |
| `set_network_parameters()` | One 0x03 network-parameter write | None | `None` after write |
| `set_network_key()` | One 0x04 key write | None | `None` after write |
| `provision()` | Optional 0x0C write, Pair04/05, Pair07 check, conditional 0x03/0x04, 0x83 observation | Pair07 read and 0x83; no mandatory 0x0C ACK | `ProvisioningResult(completed, mesh_id)`; missing 0x83 gives `completed=False`; invalid Pair07 raises; 0xA0 skips 0x03/0x04 |
| `remove_from_mesh()` | One removal frame | None | `None` after write; removal not independently verified |
| `request_status()` | One 0x0A query | None | `None` after write; use cache/callback for observation |
| `read_status()` | One 0x0A query | 0x80 or 0x82 matching registered identity | `LampStatus` / `None` on timeout |
| `read_mesh_groups()` | One 0x08 query | Addressed 0x08 | `MeshGroupMembership` / `None` on timeout |
| `read_power_cut_mode()` | One 0x43 query | Addressed 0x43 | `PowerCutConfiguration` / `None` on timeout |
| `read_timer()` / `read_program()` | One 0x35 request each (routine 2 / 3) | 0x35 matching routine | `ScheduleRead` / `None` on timeout |
| `read_nightlight()` / `read_dawn_simulator()` | 0x35 start; end only when first reply valid | 0x35 matching each routine | `ScheduleRead` (end may be absent) / `None` when first absent |
| `read_schedule_part()` | One 0x35 routine query | Addressed 0x35 matching routine | `SchedulePart` / `None` on timeout |
| `read_presence_simulator()` | One 0x3C routine 1 query | Addressed 0x3C matching routine | `PresenceRead` / `None` on timeout |
| `read_pir_settings()` | One 0x12 query | Unaddressed 0x12 | `PirSettings` / `None` on timeout |
| `read_pir_luminosity()` | One 0x13 query | Unaddressed 0x13 | raw byte / `None` on timeout (not lux) |
| `read_pair_response()` | One Pair1914 characteristic read | GATT read, not a notification | Raw `bytes`; GATT failure propagates |

Use a direct connection to the target lamp when reading its group list for a
backup or a subsequent write. A query relayed over Mesh can return an empty
list even when the target has stored groups. Example 29 reads directly before
writing the list back.

For reply-tracking methods, `timeout` constrains the local observation window.
Schedule pair methods share a total deadline; the per-frame transport/GATT
watchdogs are separate. The `0xA0` provisioning branch reports no conventional
`0x83` completion and closes the direct session. A missing or negative optional
0x0C reply does not gate the high-level provisioning steps. Caller-controlled
wizard timing is demonstrated in Example 26 rather than enforced by the API.

## Error and concurrency policy

Only one independent `ESPHomeProxy` context can be active per process.
Multiple mesh sessions can use that context. Their GATT locks are separate by default.
A convenience operation waiting for a session lock raises `ConnectionLost` if
its original connection closes or is replaced before it can send. A later
time-program part also uses the original connection.

Invalid inputs are rejected before write where possible. Bluetooth/GATT errors
propagate; a missing protocol response is *not* equivalent to a failed GATT
write. Cancellation remains cancellation. One GATT link serializes its actual
writes, but replies may be addressed ambiguously. Persisted settings and
physical device behavior require explicit readback and hardware tests.
