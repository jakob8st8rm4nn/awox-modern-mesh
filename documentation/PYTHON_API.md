# Python API and response windows

## Session and targets

`AwoXMeshSession(transport_factory, credentials, devices=None, ...)` performs no
I/O until `connect()` or async-context entry. The callbacks `on_notification`,
`on_status`, `on_mesh_status`, `on_disconnect` are synchronous. Callback
exceptions are logged and isolated from session processing. `lamp(id)` returns a typed `Lamp`; `group(address)` and
`broadcast()` return typed `MeshTarget`. This enables method suggestions in
editors such as Pylance.

## Individual device addresses

`awox.is_valid_unicast_mesh_id(value)` checks whether a value can identify an
individual device. It accepts integers from `0x0001` to `0xFFFE`, excluding
group addresses `0x8000`–`0x80FF`. Booleans, strings, and `None` return `False`.
Use it to filter imported or discovered IDs before creating a session.
It checks the address only and performs no Bluetooth I/O.

## Command naming

| Prefix | Meaning |
| --- | --- |
| `set_...` | Change a device setting. Whether it waits for a device reply depends on the method. |
| `write_...` | Send a setting change and return after the GATT write. Available for groups, power-cut mode, presence and time with timezone. |
| `read_...` | Request a device value. The return contract describes how a missing or invalid reply is represented. |
| `get_...` | Return an available cached value without a Bluetooth request. |

See the [command reference](COMMAND_REFERENCE.md) for arguments and the
[operation table](#observable-contracts-for-public-convenience-operations) for
the reply a method tracks.

## Lighting values

Brightness percentages map 0–100% to protocol values 2–254. Raw brightness
accepts 1–255 for regular and Dual-Zone commands. `set_hs()` and
`set_dual_zone_hs()` take hue in degrees from 0 through 360 inclusive and
saturation in percent from 0 to 100. A 360° input encodes as raw hue 254.
The `*_hs_raw()` methods take raw hue 0–254 and saturation 0–255. White temperature accepts 153–454 mired. The Kelvin setters encode 2200 K as 454 mired.
The `*_color_temperature_kelvin()` methods convert Kelvin to mired.

For ordinary lighting methods with a `transition` parameter, use an integer
multiple of 100 ms from 0 to 6,553,500 ms. The default is 200 ms. Zero requests
an immediate change. The upper limit is the frame field's capacity. Actual
fade timing depends on the device.

Each ordinary lighting setter sends its own command. An application that
requires a separate power command or spacing between writes supplies those
steps explicitly.

## Model metadata

`AwoXModel.color_temperature_range_kelvin` returns `(min_kelvin, max_kelvin)`
for adjustable white. Models with a documented range specific to their model
name use that range. Other models with adjustable white, including Dual Zone
models with no documented zone-specific limits, use the 2200–6500 K control
range. Actual limits can vary by device. Fixed-white and RGBW models, and
other devices without adjustable white, return `None`. Kelvin setters use
protocol limits independently of this property.

`lookup_dual_zone_properties(model_name, zone)` exposes the APK's controls
for the two zones of known Dual Zone models. Zone 0 includes RGB, while both
zones expose power, brightness and white temperature. An unsupported model
or zone returns `None`.

`lookup_fixed_white_picker_percent(model_name)` returns the APK's fixed
white-picker setting for a known model (`80` for `EGLO-ZMB-RGB-W`) or
`None`. The value describes the app's picker coordinate. Actual LED color
temperature depends on the device.

## Status queries

Use `await lamp.read_status()` to wait for a status result or
`await lamp.request_status()` to send once and observe any later reply through
the cache or callbacks. `await mesh.request_status(destination)` also accepts
group and broadcast addresses. Use `awox.status.status_query(destination)`
to build the same 0x0A frame without sending it.

`read_status()` waits for the main lamp state (zone 0 on a Dual Zone lamp).
It accepts `da.b`, `da.c` or the
previously supported `da.d` layout. For `da.b`, supply the known APK model
name when creating the session, for example
`AwoXMeshSession(factory, credentials, {mesh_id: mac}, device_models={mesh_id: "EGLO-ZM-RGB-TW"})`.
This layout carries the full MAC and leaves `LampStatus.product_code` as
`None`. For compact `da.c` white status, `temperature_percent_raw` retains
the received value. Values from 0 to 100 also yield an approximate Mired
value through the APK's percentage conversion. For `da.c` and `da.d`, an
unknown configured model name can fall back to an unambiguous lamp code in
the packet. `da.d` always requires a recognized lamp
code. The raw status remains available through `mesh.mesh_states` and
`on_mesh_status`.

Dual-Zone setters accept integer zone numbers 0 and 1.

For a known Dual Zone model registered with `device_models`,
`lamp.get_status(zone=0)` and `lamp.get_status(zone=1)` read the two cached
zone states. `mesh.get_status(mesh_id, zone=...)` provides the same access.
Omit `zone` or use `lamp.status` to read the main state. Both valid zone
reports invoke `on_status`, including repeated observations, with
`LampStatus.zone` set to 0 or 1. `StatusStore.on_change` only fires when
its stored lamp state changes. For normal lamps `zone` is `None`. The raw frame preserves the received byte as `zone_raw`.
For valid reports from known Dual Zone models, raw value 1 maps to zone 0
and all other values map to zone 1, following the APK's state handling.
Zone 1 exposes power, brightness and white temperature. Its
color mode, color values and effect flags are unavailable (`None`).
The typed cache keeps the last valid observation for each zone until it
expires or the session closes. The raw cache may include newer frames that
were rejected by the lamp model check.
Use `mesh.mesh_states` to inspect the original `MeshStatusFrame`.
Use `await lamp.request_status()` to send a fresh query separately.

`LampStatus` keeps `brightness_raw`, `hs_raw` and
`white_temperature_mired`. The `hs_raw` tuple contains the reported hue and saturation bytes. When
both bytes are in the setter's range, use `set_hs_raw(*status.hs_raw)`.
The computed `hs` tuple uses the units accepted by `set_hs(*status.hs)`.

The status provides these computed properties:

| Property | Value |
| --- | --- |
| `brightness_percent` | Integer 0–100 using the APK's clamped 2–254 conversion. |
| `color_temperature_mired` | The same reported or derived value as `white_temperature_mired`. |
| `color_temperature_kelvin` | The available white temperature, rounded to integer Kelvin. |
| `hs` | Hue in degrees (0 up to 360) and saturation in percent (0–100). |
| `rgb` | Three RGB values (0–255), calculated at full HSV value. Use the separate brightness field for dimming. |

Unavailable color or white-temperature values return `None`. These properties
are computed from the status already received.

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

The table describes the implemented operations. “None” in the Tracked reply column means the operation returns after the
transport write. `None` in the Return column may also indicate a timeout
for a method that waits for a reply. BLE errors propagate.
Methods on `lamp` use its mesh ID; Session-level methods take a destination
where shown. No command is retried automatically.

| Method | Writes / steps | Tracked reply | Return if observed / absent |
| --- | --- | --- | --- |
| `set_power()` | One control power write | None | `None` after write |
| `set_brightness_percent()` | One brightness write; percent conversion | None | `None` after write |
| `set_brightness_raw()` | One native-brightness write | None | `None` after write |
| `set_rgb()` | One RGB-to-native color write | None | `None` after write |
| `set_hs()` | One color write; hue in degrees and saturation in percent | None | `None` after write |
| `set_hs_raw()` | One native color write | None | `None` after write |
| `set_color_temperature_kelvin()` | Kelvin conversion and one white write | None | `None` after write |
| `set_color_temperature_mired()` | One native mired white write | None | `None` after write |
| `set_candle_mode()` | One effect write | None | `None` after write |
| `set_color_cycle()` | One effect write | None | `None` after write |
| `save_scene()` / `recall_scene()` | One scene write each | None | `None` after write |
| `set_dual_zone_power()` | One 0x52-based zone power write | None | `None` after write |
| `set_dual_zone_brightness_percent()` | One 0x52-based zone percent brightness write | None | `None` after write |
| `set_dual_zone_brightness_raw()` | One 0x52-based zone native brightness write | None | `None` after write |
| `set_dual_zone_rgb()` | One 0x52-based zone RGB color write | None | `None` after write |
| `set_dual_zone_hs()` | One 0x52-based zone color write; hue in degrees and saturation in percent | None | `None` after write |
| `set_dual_zone_hs_raw()` | One 0x52-based zone native color write | None | `None` after write |
| `set_dual_zone_color_temperature_kelvin()` | Kelvin converted to mired, one zone write | None | `None` after write |
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
| `set_mesh_credentials()` | Pair04/05 credential writes | None. Use `read_pair_response()` to check Pair07 | `None` after writes |
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
| `read_pir_luminosity_raw()` | One 0x13 query | Unaddressed 0x13 | raw byte / `None` on timeout (not lux) |
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
