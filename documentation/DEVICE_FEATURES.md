# Model-specific protocol features

## PIR

`pir` owns SceneConfig, PirSettings and scene packing. 0x12 reads settings,
0x13 reads raw luminosity and 0x11 writes an addressless settings structure.
The raw luminosity byte is not a known lux unit. Scene-sequence durations use
the APK's quantization and fixed encoded field; no additional meaning is
inferred. Read/edit/write is not necessarily a byte-preserving firmware backup.
Replies lack an individual source address, so concurrent reads are ambiguous.

## Dual-zone and Quiet Mode

`lighting.dual_zone_*` emits the original special layout; zone and raw state
are explicit fields. The high-level `set_dual_zone_power()` accepts a
boolean `enabled` value. The frame builder also accepts raw state 2, whose
behavior is unspecified.
Quiet Mode accepts its explicit action, enabled bit and raw parameter.
The session exposes the last raw signed result bytes, not a reliable addressed
device confirmation. These layouts are APK-backed, not hardware-proven on every
registered model.

## Stored light settings and routines

Immediate color truncates APK float32 scaling; stored routine color rounds as
the separate APK encoder does. The two conversions are intentionally distinct.
Routine builders create explicit values, while from_read preserves unknown
fields where supported. A timer send normalizes only its transmitted time-mode
bits. Presence has its own layout and 48 half-hour slots.

Nightlight uses routines 5/6 and dawn uses 7/8. Status 0x99 for routine 5 or 7 is the observed continuation condition.
`set_nightlight()` and `set_dawn_simulator()` send the second record only when
that condition is met. Single-step `set_schedule_part()` leaves continuation
to the caller. Routine response 0x33 is not interchangeable with presence
response 0x3B.

## Time

`clock.build_time` (0x30) and `build_time_with_timezone` (0x29) require explicit
timestamps and offsets/rules. They acquire no current clock implicitly.
`timezone_rule` formats explicit APK-style rule values, not a complete Android
IANA/ICU database. Example 20 uses one timestamp and starts 0x30 about 250 ms
after starting 0x29. It demonstrates the app's branch for MTU 43 or higher.
The example requires that MTU and does not implement automatic fallback or
retries. The app sends only 0x30 below that threshold.
