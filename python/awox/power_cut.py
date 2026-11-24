"""Power-cut configuration codecs and stored scene fields."""

from __future__ import annotations

from .frames import ExtendedCommand, addressed_query
from dataclasses import dataclass
from .light_settings import LightSettings, decode_light_settings, routine_white_settings


def power_cut_white_scene(brightness_percent: int, temperature_percent: int) -> bytes:
    """PowerCut scene WHITE: four *configuration* bytes, not an immediate light write.

    APK 1.14.11: ic.u.c -> [bit0=1, brightness%, temperature LE16].
    The value is app percentage 0..100, mapped to 153..454 mired.
    """
    if type(brightness_percent) is not int or not 0 <= brightness_percent <= 100:
        raise ValueError("scene brightness must be an integer percentage 0..100")
    if type(temperature_percent) is not int or not 0 <= temperature_percent <= 100:
        raise ValueError("scene temperature must be an integer percentage 0..100")
    return routine_white_settings(brightness_percent, temperature_percent, power_on=True)


def power_cut_color_scene(
    brightness_percent: int, red: int, green: int, blue: int
) -> bytes:
    """APK Power-Cut COLOR scene selected from RGB: [03, brightness%, H, S].

    Both APKs use Android Color.colorToHSV on the chosen RGB color and then
    truncate float32-scaled hue (0..360 -> 0..254) and saturation (0..1 ->
    0..254). Reuse the separately verified RGB converter; don't implement
    another, subtly different colour conversion here. No Bluetooth I/O.
    """
    if type(brightness_percent) is not int or not 0 <= brightness_percent <= 100:
        raise ValueError("scene brightness must be an integer percentage 0..100")
    from .lighting import rgb_to_native

    hue_native, saturation_native = rgb_to_native(red, green, blue)
    return bytes((3, brightness_percent, hue_native, saturation_native))


@dataclass(frozen=True)
class PowerCutConfiguration:
    """APK power_cut_get_mode listener: mode plus optional decoded scene.

    Original scene bytes and decrypted full response are always preserved.
    Only known active 01/03 scene layouts get decoded light settings.
    """

    mode: str | None
    mode_code: int
    scene_bytes: bytes
    scene_kind: str | None
    mesh_id: int | None = None
    raw_response: bytes = b""

    @property
    def scene_settings(self) -> LightSettings | None:
        """Known active WHITE/COLOR scene or None if not interpretable."""
        if (
            self.mode != "scene"
            or len(self.scene_bytes) != 4
            or self.scene_bytes[0] not in (0x01, 0x03)
        ):
            return None
        return decode_light_settings(self.scene_bytes)


def parse_power_cut_get_mode(decrypted_response: bytes) -> PowerCutConfiguration:
    """Parse a full decrypted 0x43 packet as the Android settings listener does.

    APK 1.14.10: Lv8/a.onRead -> Lh9/a.<init> -> Lt8/a.a.
    APK 1.14.11: Lu8/a.onRead -> Lg9/a.<init> -> Ls8/a.a.
    Bytes 3..6 contain the saved scene, byte 7 the mode (0=on, 1=previous,
    2=scene). The UI distinguishes a colour scene from a white scene using
    bit 1 of the scene's first byte. Known 01/03 scenes can additionally
    be decoded through ``PowerCutConfiguration.scene_settings``.
    """
    if not isinstance(decrypted_response, (bytes, bytearray)):
        raise TypeError("power-cut response must be bytes")
    if len(decrypted_response) < 8 or decrypted_response[0] != 0x43:
        raise ValueError("expected full decrypted 0x43 response with at least 8 bytes")
    response = bytes(decrypted_response)
    if len(response) < 8 or response[0] != 0x43:
        raise ValueError("expected full decrypted 0x43 response with at least 8 bytes")
    scene = response[3:7]
    code = response[7]
    mode = {0: "on", 1: "previous", 2: "scene"}.get(code)
    kind = ("color" if scene[0] & 0x02 else "white") if mode == "scene" else None
    return PowerCutConfiguration(
        mode, code, scene, kind, int.from_bytes(response[1:3], "little"), response
    )


@dataclass(frozen=True)
class PowerCutSetResponse:
    """A received 0x42 answer, *not* proof of a future power-cycle outcome.

    ``status`` is None for an unrecognized device code. No reply before the
    local deadline is represented by None instead of this object. ``mesh_id``
    is decoded from the address bytes 1..2 of the received 0x42 packet, not
    copied from the request. The full decrypted response is retained so
    unknown trailing bytes are not lost.
    """

    mesh_id: int
    status: str | None
    status_code: int
    raw_response: bytes


def parse_power_cut_set_status(decrypted_response: bytes) -> str | None:
    """Decode only the documented 0x42 ACK status; preserve raw bytes upstream.

    Both APK versions map full decrypted packet byte 3 as follows:
    0x00=SUCCESS, 0x01=GENERAL_FAIL, 0x94=TIMEOUT. An unknown code
    returns None rather than being reported as success. This is *not*
    confirmation of persistent device settings after a power cycle.
    """
    if not isinstance(decrypted_response, (bytes, bytearray)):
        raise TypeError("power-cut response must be bytes")
    if len(decrypted_response) < 4 or decrypted_response[0] != 0x42:
        raise ValueError("expected full decrypted 0x42 response with at least 4 bytes")
    return {0x00: "success", 0x01: "general_fail", 0x94: "timeout"}.get(
        decrypted_response[3]
    )


def parse_power_cut_set(decrypted_response: bytes) -> PowerCutSetResponse:
    """Decode the address and status of an APK 0x42 reply."""
    if not isinstance(decrypted_response, (bytes, bytearray)):
        raise TypeError("power-cut response must be bytes")
    raw = bytes(decrypted_response)
    status = parse_power_cut_set_status(raw)
    return PowerCutSetResponse(int.from_bytes(raw[1:3], "little"), status, raw[3], raw)


def power_cut_get_mode(destination: int) -> ExtendedCommand:
    """APK i9.h.c: CRC/length-framed 0x43 + address LE16; offline only."""
    return addressed_query(destination, 0x43)


def power_cut_set_mode(
    destination: int, mode: str, scene: bytes | None = None
) -> ExtendedCommand:
    """APK i9.i.c + u8.b.d: opcode 0x42, address, 4 scene bytes, mode.

    Supported modes in the app are 'on' (0), 'previous' (1), 'scene' (2).
    Mode 'scene' requires four APK-format bytes, built with
    power_cut_white_scene() or power_cut_color_scene().
    No BLE action or state confirmation is performed here.
    """
    modes = {"on": 0, "previous": 1, "scene": 2}
    if not isinstance(mode, str) or mode not in modes:
        raise ValueError("power-cut mode must be on, previous, or scene")
    if mode == "scene":
        if not isinstance(scene, bytes) or len(scene) != 4:
            raise ValueError("scene mode requires four encoded scene bytes")
        if scene[0] not in (1, 3):
            raise ValueError("unrecognized scene light-mode flag")
    elif scene is not None:
        raise ValueError("scene bytes are only valid with scene mode")
    data = (scene if scene is not None else bytes(4)) + bytes((modes[mode],))
    return addressed_query(destination, 0x42, data)
