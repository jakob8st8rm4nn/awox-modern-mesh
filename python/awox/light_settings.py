"""Pure codecs for the APK's shared four-byte routine light settings.

The same byte layout is used in the 0x35 schedule and 0x3C presence
responses (g9.j.e -> g9.c.a, APK 1.14.11). Power-cut scene 0x43 has
compatible bytes for the confirmed WHITE (01) and COLOR (03) variants.
This module never sends Bluetooth commands. Unknown flags are preserved.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from .pir import WIRE_TO_PRESET
from ._numeric import _f32, _integer, percentage_to_value


def _routine_flags(power_on: bool, candle_enabled: bool) -> int:
    if type(power_on) is not bool or type(candle_enabled) is not bool:
        raise TypeError("power_on and candle_enabled must be bool")
    return int(power_on) | (int(candle_enabled) << 4)


def _routine_brightness(value: int | None) -> int:
    # APK i9.r.c: -1 becomes FF; i9.p.c writes the same low byte.
    return 0xFF if value is None else _integer(value, 0, 100, "brightness_percent")


def routine_white_settings(
    brightness_percent: int | None,
    temperature_percent: int,
    *,
    power_on: bool,
    candle_enabled: bool = False,
) -> bytes:
    """Build four routine bytes as APK i9.r.c/i9.p.c, without I/O.

    Temperature 0..100 maps to 153..454 mired (warmth increases).
    Brightness None encodes the APK's FF sentinel; its firmware effect is
    not inferred. These are stored routine fields, not immediate commands.
    """
    flags = _routine_flags(power_on, candle_enabled)
    brightness = _routine_brightness(brightness_percent)
    _integer(temperature_percent, 0, 100, "temperature_percent")
    mired = percentage_to_value(temperature_percent, 153, 454)
    return bytes((flags, brightness)) + mired.to_bytes(2, "little")


def routine_color_settings(
    brightness_percent: int | None,
    red: int,
    green: int,
    blue: int,
    *,
    power_on: bool,
    candle_enabled: bool = False,
) -> bytes:
    """Build APK routine RGB fields, using Math.round rather than truncation.

    Android HSV value is discarded; brightness is supplied separately.
    Brightness None encodes FF, without asserting its firmware meaning.
    """
    from .lighting import _rgb_to_hsv

    flags = _routine_flags(power_on, candle_enabled) | 0x02
    brightness = _routine_brightness(brightness_percent)
    hue, saturation = _rgb_to_hsv(red, green, blue)
    native_hue = math.floor(_f32(_f32(hue * 254.0) / 360.0) + 0.5)
    native_saturation = math.floor(_f32(saturation * 254.0) + 0.5)
    return bytes((flags, brightness, native_hue, native_saturation))


@dataclass(frozen=True)
class LightSettings:
    """Decoded, read-only interpretation; raw_bytes is lossless.

    ``lighting_mode_code`` preserves raw bits 1..2. APK mode decoding
    gives bit 2 (sequence) priority over bit 1 (color). A 0xff brightness, 0xffff temperature,
    or out-of-range values are not reported as valid settings.
    Unused high flag bits are never given invented meanings.
    """

    power_on: bool
    lighting_mode_code: int
    lighting_mode: str | None
    candle_enabled: bool
    brightness_percent: int | None
    temperature_mired: int | None
    hue_native: int | None
    saturation_native: int | None
    sequence_wire_code: int | None
    sequence_preset: int | None
    unknown_flag_bits: int
    raw_bytes: bytes


def decode_light_settings(raw: bytes | bytearray) -> LightSettings:
    """Decode exactly four unencrypted light-configuration bytes.

    This is only a response interpretation. It is deliberately not a
    normal-light command or a hardware state claim.
    """
    if not isinstance(raw, (bytes, bytearray)):
        raise TypeError("light settings must be bytes")
    if len(raw) != 4:
        raise ValueError("light settings must have exactly four bytes")
    data = bytes(raw)
    if len(data) != 4:
        raise ValueError("light settings must have exactly four bytes")

    flags, brightness, c2, c3 = data
    code = (flags >> 1) & 0x03
    mode = "sequence" if flags & 0x04 else "color" if flags & 0x02 else "white"
    # APK sequence preset mapping: wire values 1..6 -> UI presets;
    # other wire values map to APK's fallback preset 12.
    sequence_preset = WIRE_TO_PRESET.get(c2, 12) if mode == "sequence" else None
    brightness_percent = brightness if brightness <= 100 else None
    temperature = int.from_bytes(data[2:4], "little")

    return LightSettings(
        power_on=bool(flags & 0x01),
        lighting_mode_code=code,
        lighting_mode=mode,
        candle_enabled=bool(flags & 0x10),
        brightness_percent=brightness_percent,
        temperature_mired=(
            temperature if mode == "white" and 153 <= temperature <= 454 else None
        ),
        hue_native=c2 if mode == "color" and c2 <= 254 else None,
        saturation_native=c3 if mode == "color" and c3 <= 254 else None,
        sequence_wire_code=c2 if mode == "sequence" else None,
        sequence_preset=sequence_preset,
        unknown_flag_bits=flags & ~0x17,
        raw_bytes=data,
    )
