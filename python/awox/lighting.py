"""Pure APK lighting, effect, scene and dual-zone encoders. No I/O."""

from __future__ import annotations

import math
from ._numeric import _f32, percentage_to_value
from .frames import (
    build_control,
    ExtendedCommand,
    control,
    query_frame,
    _destination_bytes,
)


DEFAULT_TRANSITION = 200
MAX_TRANSITION = 0xFFFF * 100
MAX_NATIVE = 254
MAX_NATIVE_SATURATION = 255


def transition_bytes(transition: int = DEFAULT_TRANSITION) -> bytes:
    """Encode transition in milliseconds, little-endian 100-ms units.

    Accept integer multiples of 100 ms, including 0 (no requested fade).
    Reject sub-100-ms precision instead of silently rounding. These bytes
    only request a duration; actual hardware timing is not guaranteed.
    """
    if (
        type(transition) is not int
        or not 0 <= transition <= MAX_TRANSITION
        or transition % 100
    ):
        raise ValueError(
            "transition must be an integer number of milliseconds from 0 to "
            "6553500, divisible by 100"
        )
    return (transition // 100).to_bytes(2, "little")


# Ranges observed/documented for the modern device profile, NOT guarantees
# for all AwoX firmware or models.
# The tested EGLO lamp normalizes native brightness 0 to 1;
# expose the effective native range 1..255 in the public API.
MIN_BRIGHTNESS_NATIVE = 1
MAX_BRIGHTNESS_NATIVE = 255
# The original app uses 2..254 for its 0..100% slider conversion.
APP_MIN_BRIGHTNESS_NATIVE = 2
APP_MAX_BRIGHTNESS_NATIVE = 254
MIN_MIREDS = 153
MAX_MIREDS = 454


def _candle_payload(enabled: bool) -> bytes:
    """APK i9.v payload; callers retain their own argument validation."""
    return bytes((0x10, int(enabled), 0x01))


def _color_cycle_payload(enabled: bool) -> bytes:
    """APK i9.w start/stop payload, without companion power commands."""
    return b"\x41\x01\x00\x0c" if enabled else b"\x47\x00\x00\x00"


def _scene_payload(index: int, save: bool) -> bytes:
    """APK i9.a0 save/recall payload; index and save are validated by callers."""
    return bytes((0x04 if save else 0x05, 0, 0, index))


def hsv_to_native(hue: float, saturation: float) -> tuple[int, int]:
    """i9.x.c: Android HSV floats -> native hue/saturation, with float32 truncation.

    This is the proven final encoder stage, separate from the Android/Skia
    RGB-to-HSV conversion used by the colour picker.
    """
    if not 0 <= hue < 360 or not math.isfinite(hue):
        raise ValueError("hue must be finite in 0..<360 degrees")
    if not 0 <= saturation <= 1 or not math.isfinite(saturation):
        raise ValueError("saturation must be finite in 0..1")
    return (
        int(_f32(_f32(_f32(hue) * 254.0) / 360.0)),
        int(_f32(_f32(saturation) * 254.0)),
    )


def brightness_payload_native(
    level: int, *, transition: int = DEFAULT_TRANSITION
) -> bytes:
    """Encode brightness with transition in milliseconds (default 200 ms)."""
    if (
        type(level) is not int
        or not MIN_BRIGHTNESS_NATIVE <= level <= MAX_BRIGHTNESS_NATIVE
    ):
        raise ValueError("native brightness level must be an integer from 1 to 255")
    return bytes((0x04, level)) + transition_bytes(transition) + bytes(3)


def brightness_native_from_percent(percent: int) -> int:
    """Convert 0..100% to the app slider range [2, 254] (half-up).

    Matches APK MathUtils.percentageToValue for integer percentages. This
    verifies numeric encoding, not end-to-end Android slider behavior.
    """
    if type(percent) is not int or not 0 <= percent <= 100:
        raise ValueError("brightness percent must be an integer from 0 to 100")
    return percentage_to_value(
        percent, APP_MIN_BRIGHTNESS_NATIVE, APP_MAX_BRIGHTNESS_NATIVE
    )


def temperature_payload_mired(
    mired: int, *, transition: int = DEFAULT_TRANSITION
) -> bytes:
    """Encode white temperature; transition is in milliseconds (default 200)."""
    if type(mired) is not int or not MIN_MIREDS <= mired <= MAX_MIREDS:
        raise ValueError("white temperature must be an integer from 153 to 454 mired")
    return b"\x0a" + mired.to_bytes(2, "little") + transition_bytes(transition)


def mired_from_kelvin(kelvin: int) -> int:
    """Calculate approximate device mired from Kelvin (inverse scale).

    The device reports mired values and a nominal 153..454 range. Kelvin
    conversion is a UI convenience, not verified against the Android slider.
    This rounding accepts integer Kelvin values 2201..6557; these are
    conversion bounds, not independently verified model-specific limits.
    """
    if type(kelvin) is not int or kelvin <= 0:
        raise ValueError("kelvin must be a positive integer")
    mired = (1_000_000 + kelvin // 2) // kelvin
    if not MIN_MIREDS <= mired <= MAX_MIREDS:
        raise ValueError(
            "kelvin must round to 153..454 mired (integer Kelvin range 2201..6557)"
        )
    return mired


def build_brightness_native(
    session_key: bytes,
    mesh_id: int,
    level: int,
    *,
    transition: int = DEFAULT_TRANSITION,
) -> bytes:
    """Create encrypted brightness command; transition in milliseconds."""
    return build_control(
        session_key,
        mesh_id,
        (0x08, 0x00),
        brightness_payload_native(level, transition=transition),
    )


def build_brightness_percent(
    session_key: bytes,
    mesh_id: int,
    percent: int,
    *,
    transition: int = DEFAULT_TRANSITION,
) -> bytes:
    """Build one brightness frame using the existing 0..100% conversion."""
    return build_brightness_native(
        session_key,
        mesh_id,
        brightness_native_from_percent(percent),
        transition=transition,
    )


def build_temperature_mired(
    session_key: bytes,
    mesh_id: int,
    mired: int,
    *,
    transition: int = DEFAULT_TRANSITION,
) -> bytes:
    """Create encrypted white-temperature command; transition in milliseconds."""
    return build_control(
        session_key,
        mesh_id,
        (0x00, 0x03),
        temperature_payload_mired(mired, transition=transition),
    )


def build_temperature_kelvin(
    session_key: bytes,
    mesh_id: int,
    kelvin: int,
    *,
    transition: int = DEFAULT_TRANSITION,
) -> bytes:
    """Build one white-temperature frame after converting Kelvin to mired."""
    return build_temperature_mired(
        session_key, mesh_id, mired_from_kelvin(kelvin), transition=transition
    )


def color_payload_native(
    hue: int, saturation: int, *, transition: int = DEFAULT_TRANSITION
) -> bytes:
    """Encode native HSV; transition in milliseconds (default 200)."""
    if type(hue) is not int or not (0 <= hue <= MAX_NATIVE):
        raise ValueError("native hue must be an integer from 0 to 254")
    if type(saturation) is not int or not (0 <= saturation <= MAX_NATIVE_SATURATION):
        raise ValueError("native saturation must be an integer from 0 to 255")
    return bytes((0x06, hue, saturation)) + transition_bytes(transition)


def rgb_to_native(r: int, g: int, b: int) -> tuple[int, int]:
    """Convert 8-bit RGB as Android Color.colorToHSV -> i9.x.c native bytes.

    The HSV step follows Skia's SkRGBToHSV calculation using float32
    intermediates, then the APK's truncating final scale. Alpha is irrelevant.
    The protocol discards HSV value (V): pure black and white both encode as
    (hue=0, saturation=0); neither means turn the lamp off.
    """
    return hsv_to_native(*_rgb_to_hsv(r, g, b))


def _rgb_to_hsv(r: int, g: int, b: int) -> tuple[float, float]:
    """Android/Skia hue and saturation, before command-specific scaling."""
    channels = (r, g, b)
    if any(type(x) is not int or not 0 <= x <= 255 for x in channels):
        raise ValueError("RGB channels must be integers from 0 to 255")

    lo, hi = min(channels), max(channels)
    delta = hi - lo
    if delta == 0:
        return (0, 0)  # Skia achromatic/black path: saturation and hue zero.

    # SkRGBToHSV: normalized saturation and hue-sector computation.  SkScalar
    # is float on Android; round each arithmetic stage to float32.
    saturation = _f32(delta / hi)
    if r == hi:
        sector = _f32((g - b) / delta)
    elif g == hi:
        sector = _f32(2.0 + _f32((b - r) / delta))
    else:
        sector = _f32(4.0 + _f32((r - g) / delta))
    hue = _f32(sector * 60.0)
    if hue < 0:
        hue = _f32(hue + 360.0)
    return hue, saturation


def build_color_native(
    session_key: bytes,
    mesh_id: int,
    hue: int,
    saturation: int,
    *,
    transition: int = DEFAULT_TRANSITION,
) -> bytes:
    """Build one colour command, transition in milliseconds; no I/O."""
    return build_control(
        session_key,
        mesh_id,
        (0x00, 0x03),
        color_payload_native(hue, saturation, transition=transition),
    )


def build_color_rgb(
    session_key: bytes,
    mesh_id: int,
    r: int,
    g: int,
    b: int,
    *,
    transition: int = DEFAULT_TRANSITION,
) -> bytes:
    """Build an APK-style RGB colour frame; brightness is not sent."""
    hue, saturation = rgb_to_native(r, g, b)
    return build_color_native(
        session_key, mesh_id, hue, saturation, transition=transition
    )


def _validate_mesh_id(mesh_id: int) -> None:
    if not _valid_unicast_mesh_id(mesh_id):
        raise ValueError("mesh_id must be a confirmed individual (unicast) device ID")


def build_power_command(session_key: bytes, mesh_id: int, on: bool) -> bytes:
    """Create one recorded 17-byte device power frame, no Bluetooth I/O."""
    _validate_mesh_id(mesh_id)
    if type(on) is not bool:
        raise ValueError("power state must be a bool")
    return build_control(session_key, mesh_id, (0x06, 0x00), b"\x01" if on else b"\x00")


def build_candle_command(session_key: bytes, mesh_id: int, enabled: bool) -> bytes:
    """APK i9.v: 08 00 / 10 (01 or 00) 01; one addressed frame."""
    _validate_mesh_id(mesh_id)
    if type(enabled) is not bool:
        raise ValueError("candle enabled must be a bool")
    return build_control(session_key, mesh_id, (0x08, 0x00), _candle_payload(enabled))


def build_color_cycle_command(session_key: bytes, mesh_id: int, enabled: bool) -> bytes:
    """APK i9.w (color_sequence_colors): 00 03, 41=start / 47=stop."""
    _validate_mesh_id(mesh_id)
    if type(enabled) is not bool:
        raise ValueError("color cycle enabled must be a bool")
    return build_control(
        session_key, mesh_id, (0x00, 0x03), _color_cycle_payload(enabled)
    )


from ._validation import _valid_unicast_mesh_id


def quiet_mode(
    destination: int, *, action: int, enabled: bool, parameter: int = 30
) -> ExtendedCommand:
    """APK i9.q: one 40 action targetLE enabled parameter query.

    action 1/2 are observed; 30 is the APK caller's actual byte value.
    Neither the duration/unit nor firmware-side effects are proven.
    """
    if type(action) is not int or action not in (1, 2):
        raise ValueError("quiet action must be 1 or 2")
    if type(enabled) is not bool:
        raise ValueError("quiet enabled must be bool")
    if type(parameter) is not int or not 0 <= parameter <= 255:
        raise ValueError("quiet parameter must be a byte")
    return ExtendedCommand(
        query_frame(
            b"@"
            + bytes((action,))
            + _destination_bytes(destination)
            + bytes((int(enabled), parameter))
        )
    )


def _dual_zone(destination: int, payload: bytes) -> ExtendedCommand:
    """APK j9.*: 52 FF command followed by exact dual-zone fields."""
    return control(destination, b"\xffR", payload)


def dual_zone_power(destination: int, state: int, zone: int) -> ExtendedCommand:
    """Raw state 0,1,2; state 2 has no established 'toggle' meaning."""
    if type(state) is not int or state not in (0, 1, 2):
        raise ValueError("state must be 0, 1 or 2")
    if type(zone) is not int or not 0 <= zone <= 255:
        raise ValueError("zone must be a byte")
    return _dual_zone(destination, bytes((state, zone)))


def dual_zone_brightness(destination: int, zone: int, percent: int) -> ExtendedCommand:
    """Encode the existing dual-zone brightness percentage as a frame."""
    if type(zone) is not int or not 0 <= zone <= 255:
        raise ValueError("zone must be a byte")
    if type(percent) is not int or not 0 <= percent <= 100:
        raise ValueError("percent must be 0..100")
    return dual_zone_brightness_native(
        destination, zone, percentage_to_value(percent, 2, 254)
    )


def dual_zone_brightness_native(
    destination: int, zone: int, level: int
) -> ExtendedCommand:
    """Dual-zone brightness using a native value from 1 to 255."""
    if type(zone) is not int or not 0 <= zone <= 255:
        raise ValueError("zone must be a byte")
    if type(level) is not int or not 1 <= level <= 255:
        raise ValueError("native dual-zone brightness must be 1..255")
    return _dual_zone(destination, bytes((16, zone, level)) + b"\x00\x02")


def dual_zone_color_native(
    destination: int, zone: int, hue: int, saturation: int
) -> ExtendedCommand:
    """Dual-zone color using native HSV bytes, without RGB conversion."""
    if type(zone) is not int or not 0 <= zone <= 255:
        raise ValueError("zone must be a byte")
    if type(hue) is not int or not 0 <= hue <= 254:
        raise ValueError("native hue must be 0..254")
    if type(saturation) is not int or not 0 <= saturation <= 255:
        raise ValueError("native saturation must be 0..255")
    return _dual_zone(destination, bytes((32, zone, hue, saturation)) + b"\x00\x02")


def dual_zone_temperature_mired(
    destination: int, zone: int, mired: int
) -> ExtendedCommand:
    """Dual-zone white temperature using 153..454 mired, no percentage API."""
    if type(zone) is not int or not 0 <= zone <= 255:
        raise ValueError("zone must be a byte")
    if type(mired) is not int or not 153 <= mired <= 454:
        raise ValueError("dual-zone temperature must be 153..454 mired")
    return _dual_zone(
        destination, b"!" + bytes((zone,)) + mired.to_bytes(2, "little") + b"\x00\x02"
    )


def dual_zone_color(
    destination: int, zone: int, red: int, green: int, blue: int
) -> ExtendedCommand:
    """Encode RGB as one dual-zone color frame."""
    if type(zone) is not int or not 0 <= zone <= 255:
        raise ValueError("zone must be a byte")

    hue, saturation = rgb_to_native(red, green, blue)
    return dual_zone_color_native(destination, zone, hue, saturation)


def dual_zone_temperature(destination: int, zone: int, percent: int) -> ExtendedCommand:
    """Encode the original percentage-based dual-zone temperature frame.

    This legacy encoder is not a public set_* percentage convenience method.
    """
    if type(zone) is not int or not 0 <= zone <= 255:
        raise ValueError("zone must be a byte")
    if type(percent) is not int or not 0 <= percent <= 100:
        raise ValueError("percent must be 0..100")
    return dual_zone_temperature_mired(
        destination, zone, percentage_to_value(percent, 153, 454)
    )


def native_scene(destination: int, index: int, *, save: bool) -> ExtendedCommand:
    """APK i9.a0/j9.a0: native 05 00, selectors 04=save / 05=recall.

    Verified on EGLO-ZM-RGB-TW index 1 by overwriting red with green
    and recalling it after changing the lamp to blue. No device ACK.
    Validates a non-wrapping one-byte index, does not perform BLE I/O.
    """
    if type(index) is not int or not 0 <= index <= 255:
        raise ValueError("native scene index must be an integer from 0 to 255")
    if type(save) is not bool:
        raise TypeError("save must be bool")
    return control(destination, b"\x00\x05", _scene_payload(index, save))


def set(
    destination: int, property_name: str, value, *, transition: int = DEFAULT_TRANSITION
) -> ExtendedCommand:
    """Encode an immediate property write; transition in milliseconds.

    `power_state` has no transition; leave it at the default for that command.
    """
    if property_name == "power_state":
        if transition != DEFAULT_TRANSITION:
            raise ValueError("power_state has no transition field")
        if not isinstance(value, int) or value not in (0, 1):
            raise ValueError("power state must be 0 or 1")
        return control(destination, b"\x00\x06", bytes((value,)))
    if property_name in ("white_brightness", "color_brightness"):

        level = percentage_to_value(value, 2, 254)
        return control(
            destination,
            b"\x00\x08",
            brightness_payload_native(level, transition=transition),
        )
    if property_name == "white_temperature":

        temperature = percentage_to_value(value, 153, 454)
        return control(
            destination,
            b"\x03\x00",
            temperature_payload_mired(temperature, transition=transition),
        )
    raise ValueError(
        "unimplemented extended property; color_hsv accepts explicit native HSV input"
    )


def color_hsv(
    destination: int,
    hue: float,
    saturation: float,
    *,
    transition: int = DEFAULT_TRANSITION,
) -> ExtendedCommand:
    """i9.x.c, with transition in milliseconds (default 200)."""

    native_hue, native_saturation = hsv_to_native(hue, saturation)
    return control(
        destination,
        b"\x03\x00",
        color_payload_native(native_hue, native_saturation, transition=transition),
    )
