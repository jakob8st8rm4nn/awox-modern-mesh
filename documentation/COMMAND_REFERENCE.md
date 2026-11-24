# Command reference

The signatures below show public call arguments. Some type annotations and
internal arguments are omitted for readability. See [Python API](PYTHON_API.md)
for response and timeout contracts, and [Provisioning](PROVISIONING.md) for
device enrollment. The pure codecs build or decode bytes without BLE I/O.

## Session and targets

### AwoXMeshSession

| Method | Meaning |
| --- | --- |
| `broadcast(self) -> 'MeshTarget'` | Explicit FFFF write target; never aggregates received status. |
| `connect(self, *, timeout: 'float' = 30.0) -> 'None'` | Perform a single BLE/session/login attempt; propagate actual failures. |
| `disconnect(self) -> 'None'` | Interrupt any in-progress connect, then close the current session. |
| `get_status(self, mesh_id)` | Return a cached lamp status while connected, subject to the age filter. |
| `group(self, destination: 'int') -> 'MeshTarget'` | Explicit non-lamp target; address classification is caller-owned. |
| `lamp(self, mesh_id: 'int') -> 'Lamp'` | Return a target for an individually registered mesh ID. |
| `provision(self, mesh_id: 'int', settings: 'provisioning.ProvisioningSettings', *, groups: 'list[int] \| tuple[int, ...] \| None' = None, timeout: 'float' = 20.0, provisioning_byte: 'int \| None' = None) -> 'provisioning.ProvisioningResult'` | Direct setup: optional 0x0C, Pair04/05, Pair07, then 0x03/0x04 and 0x83 observation on the standard path. |
| `read_dawn_simulator(self, destination, *, timeout: 'float' = 15.0)` | Read-only APK 0x35 routines 7 and (if valid first reply) 8. |
| `read_mesh_groups(self, destination, *, timeout=15.0)` | Read the full current membership list, never replay across reconnects. |
| `read_nightlight(self, destination, *, timeout: 'float' = 15.0)` | Read-only APK 0x35 routines 5 and (if valid first reply) 6. |
| `read_pair_response(self)` | Read the current connection's Pair1914 response. |
| `read_pir_luminosity(self, destination, *, timeout=15.0)` | 0x13 addressed query; returns raw 0..255 or None, not lux. |
| `read_pir_settings(self, destination, *, timeout=15.0)` | 0x12 addressed query; reply has no source address or request ID. |
| `read_power_cut_mode(self, destination, *, timeout=15.0)` | Read a stored configuration on this *current* mesh connection. |
| `read_presence_simulator(self, destination, *, timeout=15.0)` | Read-only APK 0x3C presence simulator, routine 1, once. |
| `read_program(self, destination, *, timeout: 'float' = 15.0)` | Read-only APK time program (0x35, routine 3), once. |
| `read_schedule_part(self, destination, routine_id, *, timeout=15.0)` | Request one specified 0x35 routine and decode its response, if received. |
| `read_status(self, mesh_id, *, timeout=15.0)` | Send one addressed 0x0A request and wait for a new status observation. |
| `read_timer(self, destination, *, timeout: 'float' = 15.0)` | Read-only APK countdown timer (0x35, routine 2), once. |
| `remove_from_mesh(self, destination)` | One explicit kick-out of a registered device; no retry or readback. |
| `request_status(self, destination)` | Write ONE 0x0A status request to an explicit mesh destination. |
| `send(self, frame: 'ExtendedCommand')` | Send one caller-built frame without waiting for a device response. |
| `send_and_track_reply(self, frame, opcode, *, target=None, routine=None, timeout=15.0, factory=False) -> 'Receipt'` | Send once and retain a bounded response window without awaiting it. |
| `set_dawn_simulator(self, destination, start, end, *, timeout: 'float' = 15.0)` | Write APK routines 7/8; MAY change persistent lamp automation. |
| `set_dual_zone_brightness(self, destination, zone, percent) -> 'None'` | Write a dual-zone brightness percentage using the existing encoder. |
| `set_dual_zone_brightness_native(self, destination, zone, level) -> 'None'` | Write a dual-zone brightness value in the encoder's native range. |
| `set_dual_zone_color_native(self, destination, zone, hue, saturation) -> 'None'` | Send dual-zone native hue and saturation values without RGB conversion. |
| `set_dual_zone_color_temperature(self, destination, zone, kelvin) -> 'None'` | Convert Kelvin to mired and send one dual-zone temperature command. |
| `set_dual_zone_color_temperature_mired(self, destination, zone, mired) -> 'None'` | Send a dual-zone temperature command using a mired value directly. |
| `set_dual_zone_power(self, destination: 'int', zone: 'int', enabled: 'bool') -> 'None'` | Write dual-zone power using a Boolean on/off value. |
| `set_dual_zone_rgb(self, destination, zone, red, green, blue) -> 'None'` | Convert RGB to the dual-zone native color representation and send once. |
| `set_mesh_credentials(self, name: str \| bytes, password: str \| bytes) -> None` | Write the supplied mesh name and password to the current connection. |
| `set_mesh_groups(self, destination: 'int', addresses, *, timeout: 'float' = 5.0) -> 'groups.MeshGroupSetResponse \| None'` | Replace memberships and return the addressed 0x0C ACK, if observed. See [Provisioning](PROVISIONING.md#explicit-single-steps) for the explicit factory exception. |
| `set_network_key(self, key)` | Send one encoded network-key frame. |
| `set_network_parameters(self, settings)` | Send the network parameter frame from ProvisioningSettings. |
| `set_nightlight(self, destination, start, end, *, timeout: 'float' = 15.0)` | Write APK routines 5/6; ONLY continue on the device's 0x99 reply. |
| `set_pir_settings(self, settings)` | Send one unaddressed 0x11 PIR configuration. No device ACK is awaited. |
| `set_power_cut_mode(self, destination, mode, scene=None, *, timeout: 'float' = 5.0) -> 'power_cut.PowerCutSetResponse \| None'` | Write 0x42, await the matching ACK and return its decoded result. |
| `set_presence_simulator(self, destination, settings, *, timeout: 'float' = 15.0) -> 'presence.PresenceSetResponse \| None'` | One original 0x3B configuration write; no automatic recovery. |
| `set_program(self, destination, settings, *, timeout: 'float' = 15.0)` | Write exactly one APK 0x33 program routine 3, no hidden automation. |
| `set_quiet_mode(self, destination, *, action, enabled, parameter=30)` | Send one quiet-mode command. A 0x40 notification is not a correlated ACK. |
| `set_schedule_part(self, destination, part) -> 'None'` | One raw 0x33 schedule write; the caller owns any follow-up. |
| `set_time(self, unix_milliseconds, offset_seconds)` | Explicit one-shot APK 0x30 time write for this MESH SESSION. |
| `set_time_with_timezone(self, unix_milliseconds, posix_rule, *, timeout: 'float' = 5.0) -> 'clock.Time29Ack \| None'` | Send 0x29 and wait for the APK status, but never sync 0x30 automatically. |
| `set_timer(self, destination, settings, *, timeout: 'float' = 15.0)` | Write exactly one APK 0x33 timer routine 2; possible persistent change. |
| `write_mesh_groups(self, destination: 'int', addresses) -> 'None'` | Replace group list once, without an acknowledgement wait. |
| `write_power_cut_mode(self, destination, mode, scene=None) -> 'None'` | Write one 0x42 mode without an ACK wait. |
| `write_presence_simulator(self, destination, settings) -> 'None'` | Send one 0x3B presence configuration without awaiting a device ACK. |
| `write_time_with_timezone(self, unix_milliseconds: int, posix_rule: str) -> None` | Send one 0x29 time and timezone write without waiting for a device reply. |

### Lamp

| Method | Meaning |
| --- | --- |
| `read_dawn_simulator(self, *, timeout: 'float' = 15.0)` | Read-only APK 0x35 routines 7 and (if valid first reply) 8. |
| `read_mesh_groups(self, *, timeout=15.0)` | Read group membership with one addressed 0x08 query. Use a direct connection for backups or before writing membership back. |
| `read_nightlight(self, *, timeout: 'float' = 15.0)` | Read-only APK 0x35 routines 5 and (if valid first reply) 6. |
| `read_pir_luminosity(self, *, timeout: 'float' = 15.0)` | Read the raw PIR luminosity value (0..255), not lux. |
| `read_pir_settings(self, *, timeout: 'float' = 15.0)` | Read PIR settings for this lamp; the protocol reply has no device address. |
| `read_power_cut_mode(self, *, timeout=15.0)` | Read the stored power-cut mode, without changing the setting. |
| `read_presence_simulator(self, *, timeout=15.0)` | Read-only APK 0x3C presence simulator, routine 1, once. |
| `read_program(self, *, timeout: 'float' = 15.0)` | Read-only APK time program (0x35, routine 3), once. |
| `read_schedule_part(self, routine_id, *, timeout=15.0)` | Read one selected schedule routine without reading its companion routine. |
| `read_status(self, *, timeout=15.0)` | Query this lamp once and wait for a fresh status notification. |
| `request_status(self) -> None` | Send one 0x0A query for this lamp. Observe responses via the status cache or callback. |
| `read_timer(self, *, timeout: 'float' = 15.0)` | Read-only APK countdown timer (0x35, routine 2), once. |
| `recall_scene(self, index: 'int') -> 'None'` | Recall native scene index 0..255 (APK selector 05), one write. |
| `save_scene(self, index: 'int') -> 'None'` | Save current state to native scene index 0..255 (APK selector 04). |
| `set_brightness(self, percent: 'int', *, transition: 'int' = 200) -> 'None'` | Set 0..100%; transition is in milliseconds (default 200). |
| `set_brightness_native(self, level: 'int', *, transition: 'int' = 200) -> 'None'` | Send native brightness 1..255; transition in milliseconds (default 200). |
| `set_candle_mode(self, enabled: 'bool') -> 'None'` | APK set_candle_mode: one effect write, no automatic power-on. |
| `set_color_cycle(self, enabled: 'bool') -> 'None'` | APK color_sequence_colors: one start/stop write, no implicit extras. |
| `set_color_native(self, hue: 'int', saturation: 'int', *, transition: 'int' = 200) -> 'None'` | Set native HSV; transition in milliseconds (default 200). |
| `set_color_temperature(self, kelvin: 'int', *, transition: 'int' = 200) -> 'None'` | Set Kelvin; transition in milliseconds (default 200). |
| `set_color_temperature_mired(self, mired: 'int', *, transition: 'int' = 200) -> 'None'` | Send 153..454 mired; transition in milliseconds (default 200). |
| `set_dawn_simulator(self, start, end, *, timeout: 'float' = 15.0)` | Write APK routines 7/8; MAY change persistent lamp automation. |
| `set_dual_zone_brightness(self, zone: 'int', percent: 'int') -> 'None'` | Set brightness percentage for a selected lamp zone. |
| `set_dual_zone_brightness_native(self, zone: 'int', level: 'int') -> 'None'` | Set a native brightness value for a selected lamp zone. |
| `set_dual_zone_color_native(self, zone: 'int', hue: 'int', saturation: 'int') -> 'None'` | Set native hue and saturation for a selected lamp zone. |
| `set_dual_zone_color_temperature(self, zone: 'int', kelvin: 'int') -> 'None'` | Set Kelvin color temperature for a selected lamp zone. |
| `set_dual_zone_color_temperature_mired(self, zone: 'int', mired: 'int') -> 'None'` | Set mired color temperature for a selected lamp zone. |
| `set_dual_zone_power(self, zone: 'int', enabled: 'bool') -> 'None'` | Set on/off for one zone on this lamp. Raw state 2 remains low-level. |
| `set_dual_zone_rgb(self, zone: 'int', red: 'int', green: 'int', blue: 'int') -> 'None'` | Set RGB color for a selected lamp zone. |
| `set_mesh_groups(self, groups, *, timeout: 'float' = 5.0)` | REPLACE ALL memberships with a single 0x0C command. |
| `set_nightlight(self, start, end, *, timeout: 'float' = 15.0)` | Write APK routines 5/6; ONLY continue on the device's 0x99 reply. |
| `set_power(self, enabled: 'bool') -> 'None'` | Send exactly one on/off control; never wait for a device ACK. |
| `set_power_cut_mode(self, mode, scene=None, *, timeout: 'float' = 5.0)` | Save a power-cut setting with one 0x42 command and await its ACK. |
| `set_presence_simulator(self, settings, *, timeout: 'float' = 15.0)` | One original 0x3B configuration write; no automatic recovery. |
| `set_program(self, settings, *, timeout: 'float' = 15.0)` | Write exactly one APK 0x33 program routine 3, no hidden automation. |
| `set_rgb(self, red: 'int', green: 'int', blue: 'int', *, transition: 'int' = 200) -> 'None'` | Set RGB; transition is in milliseconds (default 200). |
| `set_schedule_part(self, part) -> 'None'` | Write a single schedule part, without waiting or continuing a pair. |
| `set_timer(self, settings, *, timeout: 'float' = 15.0)` | Write exactly one APK 0x33 timer routine 2; possible persistent change. |
| `write_mesh_groups(self, groups) -> 'None'` | Replace the full group list without waiting for a device reply. |
| `write_power_cut_mode(self, mode, scene=None) -> 'None'` | Send one power-cut-mode write without waiting for the 0x42 reply. |
| `write_presence_simulator(self, settings) -> 'None'` | Send one 0x3B presence setting without waiting for an ACK. |

### MeshTarget

| Method | Meaning |
| --- | --- |
| `recall_scene(self, index: 'int') -> 'None'` | Recall native scene index 0..255 (APK selector 05), one write. |
| `save_scene(self, index: 'int') -> 'None'` | Save current state to native scene index 0..255 (APK selector 04). |
| `set_brightness(self, percent: 'int', *, transition: 'int' = 200) -> 'None'` | Set 0..100%; transition is in milliseconds (default 200). |
| `set_brightness_native(self, level: 'int', *, transition: 'int' = 200) -> 'None'` | Send native brightness 1..255; transition in milliseconds (default 200). |
| `set_candle_mode(self, enabled: 'bool') -> 'None'` | APK set_candle_mode: one effect write, no automatic power-on. |
| `set_color_cycle(self, enabled: 'bool') -> 'None'` | APK color_sequence_colors: one start/stop write, no implicit extras. |
| `set_color_native(self, hue: 'int', saturation: 'int', *, transition: 'int' = 200) -> 'None'` | Set native HSV; transition in milliseconds (default 200). |
| `set_color_temperature(self, kelvin: 'int', *, transition: 'int' = 200) -> 'None'` | Set Kelvin; transition in milliseconds (default 200). |
| `set_color_temperature_mired(self, mired: 'int', *, transition: 'int' = 200) -> 'None'` | Send 153..454 mired; transition in milliseconds (default 200). |
| `set_power(self, enabled: 'bool') -> 'None'` | Send exactly one on/off control; never wait for a device ACK. |
| `set_rgb(self, red: 'int', green: 'int', blue: 'int', *, transition: 'int' = 200) -> 'None'` | Set RGB; transition is in milliseconds (default 200). |

### Receipt

| Method | Meaning |
| --- | --- |
| `wait(self, *, timeout=None)` | Return the captured notification or None within the remaining window. Use one waiter per receipt. A timeout or cancellation of an active wait ends tracking. |

### ESPHomeProxy

| Method | Meaning |
| --- | --- |
| `create_transport(self, mac: 'str') -> 'ESPHomeNoCCCDTransport'` | Look up a CONNECTABLE advertisement from this proxy, no OS scan. |
| `get_advertisement(self, mac: 'str') -> 'AdvertisementRecord \| None'` | Return the last received/observed advertisement, without BLE I/O. |
| `on_advertisement(self, callback: 'Callable[[DiscoveredDevice], None]') -> 'Callable[[], None]'` | Subscribe to incoming proxy advertisement events, returns unsubscribe. |
| `scan_mesh_devices(self, duration: 'float' = 6.5)` | Discover AwoX advertisements received by this ESPHome proxy. |

## frames

| Function | Meaning |
| --- | --- |
| `addressed_query(destination: 'int', opcode: 'int', suffix: 'bytes' = b'') -> 'ExtendedCommand'` | Build one query with an explicit little-endian 16-bit destination. |
| `build_control(session_key: 'bytes', mesh_id: 'int', opcode: 'tuple[int, int]', payload: 'bytes' = b'') -> 'bytes'` | Build a control command for a known, device-specific mesh id. |
| `build_query(session_key: 'bytes', opcode: 'int', payload: 'bytes' = b'') -> 'bytes'` | Example: 0A + FFFF is the observed, broadcast, READ-ONLY status request. |
| `control(destination: 'int', command_le: 'bytes', payload: 'bytes') -> 'ExtendedCommand'` | Build a control frame, preserving the APK's reversed argument convention. |
| `control_frame(destination_le: 'bytes', command_le: 'bytes', payload: 'bytes' = b'') -> 'bytes'` | g9.c.f with its ORIGINAL two-byte-array argument conventions. |
| `crc8(data: 'bytes') -> 'int'` | Reflected CRC-8, table-free form using 0x6C (initial state zero). |
| `decode_notification(session_key: 'bytes', packet: 'bytes') -> 'ExtendedNotification'` | Decrypt a receive envelope; payload interpretation belongs to codecs. |
| `encrypt_frame(session_key: 'bytes', frame: 'bytes') -> 'bytes'` | g9.j.H: keep flag; ATT-encrypt padded bytes1:17; keep tail unchanged. |
| `open_frame(session_key: 'bytes', packet: 'bytes') -> 'DecodedFrame'` | Decode and CRC-check a captured command packet; no source authentication. |
| `query_frame(payload: 'bytes') -> 'bytes'` | g9.c.b: 02 \|\| CRC8(length \|\| payload) \|\| length \|\| payload. |
| `seal_frame(session_key: 'bytes', flag: 'int', body: 'bytes') -> 'bytes'` | Encrypt first 16 bytes incl. CRC; append remaining data without encryption. |
| `transform_extended_packet(packet: 'bytes \| bytearray \| memoryview', material: 'bytes', att_transform: 'AttTransform' = aes_att_encryption) -> 'bytes'` | g9.j.H: leave opcode and tail unchanged; transform padded first block. |

## authentication

| Function | Meaning |
| --- | --- |
| `derive_session_key(name: 'str \| bytes', password: 'str \| bytes', client_random: 'bytes', response: 'bytes') -> 'bytes'` | Derive 16-byte session key after a success response, no tag authentication. |
| `login_request(name: 'str \| bytes', password: 'str \| bytes', client_random: 'bytes') -> 'bytes'` | 17-byte ATT login request (0C \| random8 \| encrypted proof8). |
| `network_update_packets(session_key: 'bytes', name: 'bytes', password: 'bytes') -> 'tuple[bytes, bytes]'` | g9.j.T: two Pair1914 packets (04/05), unlike legacy's three packets. |

## lighting

| Function | Meaning |
| --- | --- |
| `brightness_native_from_percent(percent: 'int') -> 'int'` | Convert 0..100% to the app slider range [2, 254] (half-up). |
| `brightness_payload_native(level: 'int', *, transition: 'int' = 200) -> 'bytes'` | Encode brightness with transition in milliseconds (default 200 ms). |
| `build_brightness_native(session_key: 'bytes', mesh_id: 'int', level: 'int', *, transition: 'int' = 200) -> 'bytes'` | Create encrypted brightness command; transition in milliseconds. |
| `build_brightness_percent(session_key: 'bytes', mesh_id: 'int', percent: 'int', *, transition: 'int' = 200) -> 'bytes'` |  Build one brightness frame using the existing 0..100% conversion. |
| `build_candle_command(session_key: 'bytes', mesh_id: 'int', enabled: 'bool') -> 'bytes'` | APK i9.v: 08 00 / 10 (01 or 00) 01; one addressed frame. |
| `build_color_cycle_command(session_key: 'bytes', mesh_id: 'int', enabled: 'bool') -> 'bytes'` | APK i9.w (color_sequence_colors): 00 03, 41=start / 47=stop. |
| `build_color_native(session_key: 'bytes', mesh_id: 'int', hue: 'int', saturation: 'int', *, transition: 'int' = 200) -> 'bytes'` | Build one colour command, transition in milliseconds; no I/O. |
| `build_color_rgb(session_key: 'bytes', mesh_id: 'int', r: 'int', g: 'int', b: 'int', *, transition: 'int' = 200) -> 'bytes'` | Build an APK-style RGB colour frame; brightness is not sent. |
| `build_power_command(session_key: 'bytes', mesh_id: 'int', on: 'bool') -> 'bytes'` | Create one recorded 17-byte device power frame, no Bluetooth I/O. |
| `build_temperature_kelvin(session_key: 'bytes', mesh_id: 'int', kelvin: 'int', *, transition: 'int' = 200) -> 'bytes'` |  Build one white-temperature frame after converting Kelvin to mired. |
| `build_temperature_mired(session_key: 'bytes', mesh_id: 'int', mired: 'int', *, transition: 'int' = 200) -> 'bytes'` | Create encrypted white-temperature command; transition in milliseconds. |
| `color_hsv(destination: 'int', hue: 'float', saturation: 'float', *, transition: 'int' = 200) -> 'ExtendedCommand'` | i9.x.c, with transition in milliseconds (default 200). |
| `color_payload_native(hue: 'int', saturation: 'int', *, transition: 'int' = 200) -> 'bytes'` | Encode native HSV; transition in milliseconds (default 200). |
| `dual_zone_brightness(destination: 'int', zone: 'int', percent: 'int') -> 'ExtendedCommand'` |  Encode the existing dual-zone brightness percentage as a frame. |
| `dual_zone_color(destination: 'int', zone: 'int', red: 'int', green: 'int', blue: 'int') -> 'ExtendedCommand'` |  Encode RGB as one dual-zone color frame. |
| `dual_zone_brightness_native(destination: int, zone: int, level: int) -> ExtendedCommand` | Build a Dual-Zone brightness frame using native values 1–255. |
| `dual_zone_color_native(destination: int, zone: int, hue: int, saturation: int) -> ExtendedCommand` | Build a Dual-Zone color frame with hue 0–254 and saturation 0–255. |
| `dual_zone_power(destination: 'int', state: 'int', zone: 'int') -> 'ExtendedCommand'` | Raw state 0,1,2; state 2 has no established 'toggle' meaning. |
| `dual_zone_temperature(destination: 'int', zone: 'int', percent: 'int') -> 'ExtendedCommand'` |  Encode the original percentage-based dual-zone temperature frame. |
| `dual_zone_temperature_mired(destination: int, zone: int, mired: int) -> ExtendedCommand` | Build a Dual-Zone white-temperature frame using 153–454 mired. |
| `hsv_to_native(hue: 'float', saturation: 'float') -> 'tuple[int, int]'` | i9.x.c: Android HSV floats -> native hue/saturation, with float32 truncation. |
| `mired_from_kelvin(kelvin: 'int') -> 'int'` | Calculate approximate device mired from Kelvin (inverse scale). |
| `native_scene(destination: 'int', index: 'int', *, save: 'bool') -> 'ExtendedCommand'` | APK i9.a0/j9.a0: native 05 00, selectors 04=save / 05=recall. |
| `quiet_mode(destination: 'int', *, action: 'int', enabled: 'bool', parameter: 'int' = 30) -> 'ExtendedCommand'` | APK i9.q: one 40 action targetLE enabled parameter query. |
| `rgb_to_native(r: 'int', g: 'int', b: 'int') -> 'tuple[int, int]'` | Convert 8-bit RGB as Android Color.colorToHSV -> i9.x.c native bytes. |
| `set(destination: 'int', property_name: 'str', value, *, transition: 'int' = 200) -> 'ExtendedCommand'` | Encode an immediate property write; transition in milliseconds. |
| `temperature_payload_mired(mired: 'int', *, transition: 'int' = 200) -> 'bytes'` | Encode white temperature; transition is in milliseconds (default 200). |
| `transition_bytes(transition: 'int' = 200) -> 'bytes'` | Encode transition in milliseconds, little-endian 100-ms units. |

## status

| Function | Meaning |
| --- | --- |
| `status_query(destination: int) -> ExtendedCommand` | Build one 0x0A status query for an individual target, group or broadcast. No write occurs until the caller sends the frame. |

## groups

| Function | Meaning |
| --- | --- |
| `get_mesh_groups(destination: 'int') -> 'ExtendedCommand'` | APK i9.c.c / j9.c.c: read one device's group membership. |
| `parse_mesh_groups_get(decrypted_response: 'bytes') -> 'MeshGroupMembership'` | APK DeviceSettingsActivity.onRead: count at byte 4, IDs LE16 at 5+. |
| `parse_mesh_groups_set_result(decrypted_response: 'bytes') -> 'MeshGroupSetResponse'` | APK g9.j.e / h9.i.e: address LE16 and raw result at byte 3. |
| `set_mesh_groups(destination: 'int', group_addresses) -> 'ExtendedCommand'` | APK i9.n.c / j9.n.c: replace a device's group-address list. |

## power_cut

| Function | Meaning |
| --- | --- |
| `parse_power_cut_get_mode(decrypted_response: 'bytes') -> 'PowerCutConfiguration'` | Parse a full decrypted 0x43 packet as the Android settings listener does. |
| `parse_power_cut_set(decrypted_response: 'bytes') -> 'PowerCutSetResponse'` | Decode the complete 0x42 reply, including the device address, status code and raw response bytes. |
| `parse_power_cut_set_status(decrypted_response: 'bytes') -> 'str \| None'` | Decode only the documented 0x42 ACK status; preserve raw bytes upstream. |
| `power_cut_color_scene(brightness_percent: 'int', red: 'int', green: 'int', blue: 'int') -> 'bytes'` | APK Power-Cut COLOR scene selected from RGB: [03, brightness%, H, S]. |
| `power_cut_get_mode(destination: 'int') -> 'ExtendedCommand'` | APK i9.h.c: CRC/length-framed 0x43 + address LE16; offline only. |
| `power_cut_set_mode(destination: 'int', mode: 'str', scene: 'bytes \| None' = None) -> 'ExtendedCommand'` | APK i9.i.c + u8.b.d: opcode 0x42, address, 4 scene bytes, mode. |
| `power_cut_white_scene(brightness_percent: 'int', temperature_percent: 'int') -> 'bytes'` | PowerCut scene WHITE: four *configuration* bytes, not an immediate light write. |

## Stored routine builders

These builders prepare fields for a later schedule or presence write.

| Builder | Purpose |
| --- | --- |
| `routine_white_settings(brightness_percent, temperature_percent, *, power_on, candle_enabled=False)` | Four stored white-light bytes. Temperature 0–100% maps to 153–454 mired. Brightness `None` encodes `FF`. |
| `routine_color_settings(brightness_percent, red, green, blue, *, power_on, candle_enabled=False)` | Four stored color bytes. RGB is converted to hue and saturation with APK rounding. Brightness is supplied separately. |
| `ScheduleWritePart.timer(minutes, light_fields, *, enabled, fade_minutes=0)` | Build new relative timer settings for routine 2. |
| `ScheduleWritePart.clock(routine_id, hour, minute, light_fields, *, enabled, weekdays_mask=0, repeat=False, fade_minutes=0)` | Build new clock settings for program, nightlight or dawn. Sunday is weekday bit 0. |
| `ScheduleWritePart.from_read(part)` | Copy the ten setting bytes from a valid `SchedulePart`. For grouped read results, pass `start` or `end` separately. |
| `PresenceWritePart.create(light_fields, *, enabled, weekdays_mask=0, repeat=False, random_enabled=False)` | Build routine 1 with all 48 half-hour slots initially clear. Select them with `with_half_hour_slot(index, enabled)`. |
| `PresenceWritePart.from_read(reading)` | Copy the setting bytes from a valid addressed `PresenceRead`. |

The `with_…` methods return an updated settings value. A later encoder can
normalize protocol fields, such as time mode for timers and part markers for
paired writes. See [Modern Mesh features](MODERN_MESH_EXTENSIONS.md).

## schedule

| Function | Meaning |
| --- | --- |
| `parse_schedule_read(decrypted_response: 'bytes') -> 'SchedulePart'` | Decode only fields established in g9.j.e's 0x35 receiver. |
| `parse_schedule_set(decrypted_response: 'bytes') -> 'ScheduleSetResponse'` | APK g9.j.e 0x33 receiver: addr LE, status, action, routine. |
| `schedule_get(destination: 'int', routine_id: 'int') -> 'ExtendedCommand'` | APK i9.e/j9.e: 35 + addressLE16 + routine ID (read only). |
| `schedule_set(destination: 'int', settings) -> 'ExtendedCommand'` | APK i9.r.c / j9.r.c: 33 + addressLE16 + exactly 10 fields. |

## presence

| Function | Meaning |
| --- | --- |
| `parse_presence_read(decrypted_response: 'bytes') -> 'PresenceRead'` | Parse full 0x3C frame after ATT decryption (opcode included). |
| `parse_presence_set(decrypted_response: 'bytes') -> 'PresenceSetResponse'` | APK g9.j.e / h9.i.e: 3B addrLE16 status action routine. |
| `presence_get(destination: 'int') -> 'ExtendedCommand'` | APK i9.d.c / j9.d.c: 3C + addressLE16 + routine 01, read only. |
| `presence_set(destination: 'int', settings) -> 'ExtendedCommand'` | APK i9.p / j9.p: 3B + addressLE16 + 14 presence bytes. |

## pir

| Function | Meaning |
| --- | --- |
| `decode_scene(mode: 'int', data: 'bytes', *, masked_white: 'bool' = True) -> 'SceneConfig'` | f9.e.b (masked white) or f9.e.a (unmasked white). |
| `encode_scene(config: 'SceneConfig', *, schedule: 'bool' = False) -> 'bytes'` | f9.e.c; f9.e.d supports the same white/HSV layouts for schedules. |
| `pir_luminosity_get(destination: 'int') -> 'ExtendedCommand'` | APK i9.k: 13 + destination LE16; reply is a raw byte, not lux. |
| `pir_settings_get(destination: 'int') -> 'ExtendedCommand'` | APK i9.l: 12 + destination LE16; no settings are changed. |
| `pir_settings_set(settings: 'PirSettings') -> 'ExtendedCommand'` | APK i9.m: one unaddressed 11 + nine PIR configuration bytes. |

## clock

| Function | Meaning |
| --- | --- |
| `build_time(unix_milliseconds: 'int', offset_seconds: 'int') -> 'ExtendedCommand'` | APK i9.s.c, property ``time``, query opcode 0x30. |
| `build_time_with_timezone(unix_milliseconds: 'int', posix_rule: 'str') -> 'ExtendedCommand'` | APK i9.t.c, property ``time_with_timezone``, opcode 0x29. |

## provisioning

| Function | Meaning |
| --- | --- |
| `build_network_key(network_key: 'bytes') -> 'ExtendedCommand'` | APK i9.o: 04 + exactly 16 key bytes + allocation-zero, no target ID. |
| `build_provision_network(channel: 'int', network_id: 'bytes', extended_network_id: 'bytes', *, group_address: 'int' = 0, reserved: 'int' = 0) -> 'ExtendedCommand'` | APK i9.j: 03 + 1/2/8/2/2 bytes + final allocation-zero, no target ID. |
| `factory_credentials(mac: 'str', model_code: 'bytes', firmware: 'str', *, name: 'str' = 'unpaired') -> 'Credentials'` | APK h9.a.b/c and g9.g: explicit factory/default credential selection. |
| `remove_from_mesh(destination: 'int') -> 'ExtendedCommand'` | APK i9.g.c: explicit kick-out query, not a proven full factory reset. |

## timezone_rule

| Function | Meaning |
| --- | --- |
| `apk_posix_offset(offset_seconds: 'int') -> 'str'` | Match i9.e0.a: POSIX sign is INVERSE of GMT offset. |
| `apk_transition_time(seconds: 'int') -> 'str'` | Match i9.e0.b, including its unusual negative-subhour behavior. |
| `format_apk_dst_timezone(standard_name: 'str \| None', standard_offset_seconds: 'int', daylight_name: 'str \| None', start: 'AndroidTransitionRule', end: 'AndroidTransitionRule') -> 'str \| None'` | Match i9.t.c rule assembly with EXPLICIT Java-style transition inputs. |
| `format_apk_fixed_timezone(standard_offset_seconds: 'int', *, has_future_transition: 'bool' = False) -> 'str \| None'` | i9.t.c fixed/no-recurring-rule branch, using i9.e0.a. |
| `format_apk_transition(rule: 'AndroidTransitionRule') -> 'str \| None'` | APK i9.e0.c: M- or J-rule, or None if not representable. |
