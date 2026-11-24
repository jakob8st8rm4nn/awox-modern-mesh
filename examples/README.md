# Standalone examples

Each script demonstrates one task. The [command reference](../documentation/COMMAND_REFERENCE.md)
lists the full API and its parameters.

## Run an example

Install from the repository root with `python -m pip install ".[esphome]"`.
Fill in the settings at the top of a local copy and run it with Python, for
example `python examples/app_07_power.py`. Keep configured copies and cloud
output private. See [Security](../SECURITY.md).

Example 01 uses the standard library and a HomeControl account. Examples
02–03 only need an ESPHome proxy. Example 04 runs offline. The remaining
examples use a proxy and a mesh or factory login.

A GATT write confirms the Bluetooth operation. Readbacks and callbacks report
device state. The scripts do not automatically retry commands or restore prior
settings.

## Examples

| No. | File | One demonstrated sequence |
| --- | --- | --- |
| 01 | [`app_01_cloud_account_read.py`](app_01_cloud_account_read.py) | Read cloud account and device records; mask common secrets |
| 02 | [`app_02_bluetooth_discovery.py`](app_02_bluetooth_discovery.py) | Find AwoX devices without a lamp connection |
| 03 | [`app_03_advertisement_monitor.py`](app_03_advertisement_monitor.py) | Watch passive events and inspect their cache |
| 04 | [`app_04_model_registry.py`](app_04_model_registry.py) | Look up one model by code and name, offline |
| 05 | [`app_05_session_status.py`](app_05_session_status.py) | Observe callbacks and the age-filtered status cache |
| 06 | [`app_06_read_status.py`](app_06_read_status.py) | Compare a waiting read with a send-only status query |
| 07 | [`app_07_power.py`](app_07_power.py) | Switch one lamp on, pause, then off |
| 08 | [`app_08_brightness.py`](app_08_brightness.py) | Switch on; increase brightness: 50%, then native 220 |
| 09 | [`app_09_color_temperature.py`](app_09_color_temperature.py) | Switch on; change warm 3000 K to cooler 200 mired (5000 K) |
| 10 | [`app_10_color.py`](app_10_color.py) | Switch on; change RGB red to native blue |
| 11 | [`app_11_transition.py`](app_11_transition.py) | Switch on; watch one three-second brightness fade |
| 12 | [`app_12_effects.py`](app_12_effects.py) | Switch on; observe Candle, stop it, then observe and stop Color Cycle |
| 13 | [`app_13_dual_zone.py`](app_13_dual_zone.py) | Switch one selected zone on, red and off |
| 14 | [`app_14_multiple_lamps.py`](app_14_multiple_lamps.py) | Read two lamps through one gateway |
| 15 | [`app_15_mesh_groups.py`](app_15_mesh_groups.py) | Assign one membership; switch the group on, blue and off |
| 16 | [`app_16_quiet_mode.py`](app_16_quiet_mode.py) | Send one explicitly configured Quiet Mode command |
| 17 | [`app_17_scenes.py`](app_17_scenes.py) | Save red, change to blue, then recall red |
| 18 | [`app_18_power_cut_mode.py`](app_18_power_cut_mode.py) | Read, write one selected power-cut mode, and read back |
| 19 | [`app_19_pir_sensor.py`](app_19_pir_sensor.py) | Read PIR settings/light and write one chosen configuration; optional sequence alternative |
| 20 | [`app_20_sync_time_with_timezone.py`](app_20_sync_time_with_timezone.py) | Send 0x29 and 0x30 with one timestamp, about 250 ms apart |
| 21 | [`app_21_timer.py`](app_21_timer.py) | Read, build one enabled 20-minute OFF timer, read back |
| 22 | [`app_22_program.py`](app_22_program.py) | Read, build a weekday 18:30 blue-light program, read back |
| 23 | [`app_23_nightlight.py`](app_23_nightlight.py) | Read, build a daily dim-white 21:00-23:00 window, read back |
| 24 | [`app_24_dawn_simulator.py`](app_24_dawn_simulator.py) | Read, build a daily 06:30-07:00 white dawn window with a fade field, read back |
| 25 | [`app_25_presence_simulator.py`](app_25_presence_simulator.py) | Read, build one weekday 09:00-09:30 white-light selection, read back |
| 26 | [`app_26_remote_provisioning.py`](app_26_remote_provisioning.py) | Enroll ERCU-Zm or ERCU-WS-Zm with one group or ERCU-3groups-Zm with three ordered groups |
| 27 | [`app_27_factory_lamp_provisioning.py`](app_27_factory_lamp_provisioning.py) | Provision one factory lamp; report completion and an optional new ID |
| 28 | [`app_28_remove_from_mesh.py`](app_28_remove_from_mesh.py) | Send exactly one explicit removal query and disconnect |
| 29 | [`app_29_track_command_reply.py`](app_29_track_command_reply.py) | Connect directly, write back existing groups once, track the matching 0x0C reply, and read back |


## Settings that persist

| Examples | What to check before running |
| --- | --- |
| 15 and 29 | Use a direct connection to read the target's group list. Example 15 replaces the whole list and controls the group. Example 29 writes back the observed list once and tracks the reply. It reads the list again after a matching reply arrives. |
| 17 and 18 | Example 17 overwrites numbered scene slot 1. Example 18 changes the power-cut setting. Its custom scene is separate from numbered scenes. |
| 19 and 20 | Example 19 sends one addressless PIR settings write. Example 20 sends clock and timezone commands and requires sufficient MTU. See [Time](../documentation/MODERN_MESH_EXTENSIONS.md#time). |
| 21–25 | Each script replaces and enables a stored routine after a successful initial read. To disable it in the example, set `enabled=False` for each record in that routine. |
| 26–28 | Connect directly. Examples 26 and 27 change mesh credentials and may assign a new mesh ID. Example 28 sends a mesh removal command. See [Provisioning](../documentation/PROVISIONING.md) for the network key and factory login requirements. |

Example 13 requires Dual-Zone hardware. Examples 08–12 send an explicit
`set_power(True)` before demonstrating a lighting command. The setting call
on its own sends one command and adds no separate power write.

For Example 26, activate your remote's smartphone (Bluetooth pairing) mode
according to its manual and confirm the prompt. The script observes the
advertisements for 15 seconds and uses the received device name for the factory
login. For both provisioning examples, the target mesh credentials and key
must already be available. Check the assigned remote groups or confirm the
lamp's new identity after setup.
