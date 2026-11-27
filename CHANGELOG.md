# Changelog

## [Unreleased]

## [1.0.0] - 2026-11-27

- Expose `is_valid_unicast_mesh_id()` for validating individual device addresses.
- Allow an existing mesh session to reconnect after ESPHome proxy loss once the
  prior BLE connection is confirmed closed locally.
- Check that Pair, Command and Notify are present in the same GATT service
  before starting the mesh login.
- Read supported main lamp `da.b` and `da.c` lamp status frames and
  apply the registered lamp model check to `da.d` as well.
- Expose Dual Zone controls and the fixed RGBW white-picker setting as model
  metadata.
- Read cached Dual Zone status with `get_status(zone=...)` on a lamp or
  `get_status(mesh_id, zone=...)` on a session. Both zones are reported by `on_status`.
- Expose the control zone as `LampStatus.zone` (0 or 1 for Dual Zone,
  `None` for ordinary lamps) and the received zone byte as `MeshStatusFrame.zone_raw`.
  As in the APK, valid Dual Zone reports map raw value 1 to zone 0 and other
  raw values to zone 1.
- Restrict public Dual-Zone setters to integer zones 0 and 1.
- Rename the brightness, Kelvin and raw hue/saturation methods to state their
  input units, and rename the PIR reading to `read_pir_luminosity_raw()`.
  Add `set_hs()` and `set_dual_zone_hs()` for degrees and percent.
  Both accept hue through 360°, which encodes as raw hue 254.

### Upgrading from 0.1.0

- Use the explicit brightness, Kelvin and HS setter names documented in the
  command reference, and use `read_pir_luminosity_raw()` for PIR readings.
- Use `LampStatus.hs_raw` for the hue/saturation pair, `LampStatus.zone`
  for the logical zone and `MeshStatusFrame.zone_raw` for the wire value.
- For a known Dual Zone lamp, `on_status` now reports both zones. Use
  `status.zone` when routing updates to separate light controls.

## [0.1.0] - 2026-11-25

- AwoX HomeControl Bluetooth frame encoders, decoders and mesh login support.
- ESPHome Bluetooth proxy discovery, transport and advertisement monitoring.
- Power, color, brightness, transitions, effects, scenes, groups and Dual-Zone.
- Status, power-cut, PIR, Quiet Mode, schedules and presence operations.
- Provisioning, factory credentials and mesh removal.
- Typed API (`py.typed`), 29 standalone examples and offline regression tests.
- Documentation for installation, public commands, protocol data and safety.

Hardware behavior varies by supported model.
Check model-specific features on the intended hardware.
