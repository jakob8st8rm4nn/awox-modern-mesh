# Standalone examples

Each example has one purpose and a short, readable sequence. Alternatives are
explained where useful; they are not all executed one after another. Full
parameter and error-case coverage belongs in the tests.

## Running

Install from the repository root with `python -m pip install -e ".[esphome]"`.
Edit the blank connection settings at the top of the chosen script, then run,
for example, `python examples/app_07_power.py`.

Example 01 uses only cloud credentials and the standard library. Examples
02-03 need only proxy settings. Example 04 is offline. The other scripts use
an ESPHome proxy and mesh credentials. The gateway may differ from the target;
Example 14 registers two target lamps on the same connection.

Examples 26–28 form a separate device-setup/removal block. They connect
**directly to the device**, not through another gateway. Examples 26–27 need
the existing mesh's 16-byte network key in addition to name/password and
collect factory-login metadata during a fixed 15-second observation window. For Example 26, activate
smartphone mode (Bluetooth pairing mode) according to your remote's manual,
then confirm the terminal prompt. Example 26 uses the received device name
for the current login; MESH_NAME remains the desired new mesh name. It stops
without writing if no complete named advertisement is received.

Do not commit credentials. Read each opening description before execution.
The Bluetooth examples do not automatically retry device commands, reconnect
or restore earlier settings.

## Examples

| No. | File | One demonstrated sequence |
| --- | --- | --- |
| 01 | `app_01_cloud_account_read.py` | Read cloud account and device records; mask common secrets |
| 02 | `app_02_bluetooth_discovery.py` | Find AwoX devices without a lamp connection |
| 03 | `app_03_advertisement_monitor.py` | Watch passive events and inspect their cache |
| 04 | `app_04_model_registry.py` | Look up one model by code and name, offline |
| 05 | `app_05_session_status.py` | Observe callbacks and the age-filtered status cache |
| 06 | `app_06_read_status.py` | Compare a waiting read with a send-only status query |
| 07 | `app_07_power.py` | Switch one lamp on, pause, then off |
| 08 | `app_08_brightness.py` | Switch on; increase brightness: 50%, then native 220 |
| 09 | `app_09_color_temperature.py` | Switch on; change warm 3000 K to cooler 200 mired (5000 K) |
| 10 | `app_10_color.py` | Switch on; change RGB red to native blue |
| 11 | `app_11_transition.py` | Switch on; watch one three-second brightness fade |
| 12 | `app_12_effects.py` | Switch on; observe Candle, stop it, then observe and stop Color Cycle |
| 13 | `app_13_dual_zone.py` | Switch one selected zone on, red and off |
| 14 | `app_14_multiple_lamps.py` | Read two lamps through one gateway |
| 15 | `app_15_mesh_groups.py` | Assign one membership; switch the group on, blue and off |
| 16 | `app_16_quiet_mode.py` | Send one explicitly configured Quiet Mode command |
| 17 | `app_17_scenes.py` | Save red, change to blue, then recall red |
| 18 | `app_18_power_cut_mode.py` | Read, write one selected power-cut mode, and read back |
| 19 | `app_19_pir_sensor.py` | Read PIR settings/light and write one chosen configuration; optional sequence alternative |
| 20 | `app_20_sync_time_with_timezone.py` | Send 0x29 and 0x30 with one timestamp, about 250 ms apart |
| 21 | `app_21_timer.py` | Read, build one enabled 20-minute OFF timer, read back |
| 22 | `app_22_program.py` | Read, build a weekday 18:30 blue-light program, read back |
| 23 | `app_23_nightlight.py` | Read, build a daily dim-white 21:00-23:00 window, read back |
| 24 | `app_24_dawn_simulator.py` | Read, build a daily 06:30-07:00 white dawn window with a fade field, read back |
| 25 | `app_25_presence_simulator.py` | Read, build one weekday 09:00-09:30 white-light selection, read back |
| 26 | `app_26_remote_provisioning.py` | Enroll ERCU-Zm or ERCU-WS-Zm with one group or ERCU-3groups-Zm with three ordered groups |
| 27 | `app_27_factory_lamp_provisioning.py` | Provision one factory lamp; report completion and an optional new ID |
| 28 | `app_28_remove_from_mesh.py` | Send exactly one explicit removal query and disconnect |
| 29 | `app_29_track_command_reply.py` | Connect directly, write back existing groups once, track the matching 0x0C reply, and read back |

## What you can observe

- **Immediately visible on the lamp:** 07–13 and 17. Examples 08–12 switch
  the lamp on explicitly so the demonstrated brightness, white-temperature,
  color, fade and effects can be seen even if it was initially off. The
  individual setting methods do **not** implicitly turn on lamps. Example 13
  requires a compatible Dual-Zone device.
- **Visible at the gateway or in terminal output:** 01–06 and 14. These
  intentionally do not change lighting; they show scans, model lookup,
  status responses, callbacks and cache entries.
- **Configuration whose effect may happen only later:** 15–16 and 18–25.
  Group control in 15 is immediately visible, but it also permanently
  changes membership; scene slot 1 in 17 is overwritten. PIR/Quiet Mode and
  scheduled actions cannot be verified just by observing a GATT write. Read
  responses and readbacks show stored/observed data, not guaranteed execution.
- **Explicit reply tracking:** 29. Connects directly to the target lamp, reads its group list, and writes it
  back without choosing new groups, observes the 0x0C reply, then reads again.
  The write is still persistent; use a test lamp. A missing reply leaves the
  outcome unknown. `send_and_track_reply()` sends exactly once; combining it
  with `write_mesh_groups()` would send the command twice.
- **Persistent setup or removal:** 26–28. These affect credentials or mesh
  membership. A completion report is not proof that physical buttons work or
  that a removed device can no longer be reached. Test with a spare device.

The scripts are standalone on purpose: each can run after editing its own
settings. The repeated connection boilerplate makes that possible without a
shared hidden helper. They demonstrate one real use case, not every parameter
combination. They do not automatically restore earlier device settings.

## Observation and side effects

- Examples 26–27 replace persistent mesh credentials/key and can assign a new
  ID. They use the actual existing mesh key; they do not generate one or alter
  App/cloud records. Missing completion is an unknown outcome; the new ID
  may be absent even after confirmed completion. Example 26
  uses three ordered BUTTON_GROUPS entries for ERCU-3groups-Zm and one for
  ERCU-Zm/ERCU-WS-Zm. The three-group path sends the group list **without requiring** a positive
  acknowledgement. Both paths wait one second before the credential/network
  sequence. The single-group path embeds the group in network parameters.
  Verify the button assignments on the device.
- Both provisioning examples pass the observed `provisioning_byte` to
  `AwoXMeshSession.provision()`. For `0xA0`, they report that the standard
  0x03 and 0x04 writes were skipped. Verify device operation separately.
- Example 27 only discovers, authenticates and provisions the factory lamp.
  It sends no group reads/writes or light controls and opens no second mesh
  session. An absent new ID is printed as "not reported"; determine identity
  separately before later addressed commands. Group membership is a separate
  task demonstrated in Example 15, not part of provisioning.
- Example 28 can invalidate the old credentials and ID. It neither confirms
  physical removal from GATT completion nor automatically re-enrolls the
  device. Link loss during the write is an unknown outcome, not an instruction
  to resend. Save required settings before deliberately running it.

- Examples 08-12 explicitly switch the target lamp ON before their
  demonstration. The individual brightness, color and effect methods do not
  automatically turn on lamps. Pauses allow observation, not confirmation.
  The fade example observes for four seconds after requesting a three-second
  fade; each effect is observed for twenty seconds.
- GATT write completion is not proof of physical light output. Reads and
  callbacks expose observations; `None` means no matching response. Readback
  is printed for inspection rather than silently treated as verification.
- Example 13 needs compatible Dual-Zone hardware. Raw zone selection does not
  establish a universal mapping to status endpoints.
- Example 15 replaces the target lamp's ENTIRE group list. It reads it back
  before controlling the chosen group. It sends no broadcast or scene writes.
  Other members of that group receive the same commands. The original
  membership list is not restored.
- Example 17 overwrites scene slot 1. Example 18 changes persistent power-cut
  behavior without performing a power cut. Select one `POWER_CUT_MODE`:
  `previous` (default), `on`, or `scene`. Scene uses a fixed 50% white setting
  and replaces the stored custom power-cut scene; it does not write a numbered
  scene slot. Other modes do not demonstrate extra light commands.
- Example 19 writes ONE addressless PIR configuration only after a successful
  initial settings read. Reads are addressed, but the settings write has no
  encoded target or per-device ACK. Luminosity is raw, not lux. To show a
  different action, replace `MOTION_ACTION` with its commented alternative;
  only the chosen configuration is written.
- Example 20 demonstrates the APK branch for MTU 43 or higher. It uses the
  same timestamp for 0x29 and 0x30 and starts 0x30 about 250 ms later without
  waiting for the 0x29 result. Backend queueing can change write spacing.
- Examples 21-25 read the current settings, then build a complete new routine
  using the offline builders. They replace the old fields, including light
  values and unclassified flags, rather than preserving them with `from_read`.
  A missing/invalid initial read prevents the write. To preserve fields from
  an existing valid record where supported, start from `from_read` and edit
  individual fields. The outgoing encoder may still normalize some fields.
  Each example enables one persistent automation and leaves it enabled; it
  may operate the lamp later. To disable instead, change `enabled=True` to
  `enabled=False` (both records for nightlight/dawn). They do not run a second
  enable/disable demonstration or restore the previous configuration.
  The initial two-second pause is for reading the printed settings, not a
  protocol delay. These scripts do not wait for a scheduled hour or countdown,
  and the dawn fade field is not proof of a physical sunrise animation.
- Discovery snapshots, cached advertisements and session statuses have distinct
  freshness contracts. Example 05 sends one initial status query and then
  observes the cache without polling again. Example 06 compares a waiting
  read with a separate send-only request. A live gateway does not prove every
  target is reachable. Group queries, if requested by an application, return
  individual reports rather than a group acknowledgement.

See the [command reference](../documentation/COMMAND_REFERENCE.md) for all
commands and parameters without expanding these demonstration sequences.

See [Getting started](../documentation/GETTING_STARTED.md),
[Python API](../documentation/PYTHON_API.md), and
[Modern Mesh extensions](../documentation/MODERN_MESH_EXTENSIONS.md)
for full parameter ranges and protocol limitations.
