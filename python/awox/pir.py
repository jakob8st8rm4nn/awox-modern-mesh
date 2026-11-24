"""APK PIR configuration and packed scenes; no inferred firmware units."""

from __future__ import annotations

from dataclasses import dataclass
import math
from ._numeric import _f32, percentage_to_value, value_to_percentage

WHITE_MAX = 127
PRESET_TO_WIRE = {1: 1, 4: 2, 2: 3, 6: 4, 3: 5, 5: 6}
WIRE_TO_PRESET = {value: key for key, value in PRESET_TO_WIRE.items()}
from ._numeric import _integer, _byte
from .frames import ExtendedCommand, query_frame, addressed_query


@dataclass(frozen=True)
class SceneConfig:
    """f9.e.c/b packed light action; mode 0 white, 1 HSV, 2 sequence.

    Hue/saturation are explicit to avoid assuming Android RGB-to-HSV rounding.
    sequence_fade_duration corresponds to v9.j.c, quantized down to 100 units;
    sequence_color_duration is read from v9.j.d; encode_scene ignores it
    and writes the APK constant 8000 (wire value 80), even after a read.
    No time unit is assumed for these raw duration values.
    """

    mode: int
    brightness: int
    temperature: int = 0
    hue: float = 0.0
    saturation: float = 0.0
    sequence_preset: int = 12
    sequence_fade_duration: int = 0
    sequence_color_duration: int = 8000


def encode_scene(config: SceneConfig, *, schedule: bool = False) -> bytes:
    """f9.e.c; f9.e.d supports the same white/HSV layouts for schedules.

    APK conversion is not a byte-preserving roundtrip of decoded settings.
    """
    _integer(config.mode, 0, 2, "scene mode")
    if config.mode == 0:
        return bytes(
            (
                percentage_to_value(config.brightness, 1, WHITE_MAX),
                percentage_to_value(config.temperature, 0, WHITE_MAX),
                0,
            )
        )
    if config.mode == 1:
        if not 0 <= config.hue < 360 or not math.isfinite(config.hue):
            raise ValueError("hue must be finite in 0..<360 degrees")
        if not 0 <= config.saturation <= 1 or not math.isfinite(config.saturation):
            raise ValueError("saturation must be finite in 0..1")
        hue = int(_f32(config.hue))
        saturation = int(_f32(_f32(config.saturation) * _f32(100.0)))
        return bytes(
            (
                percentage_to_value(config.brightness, 10, 100),
                saturation | ((hue & 1) << 7),
                (hue >> 1) & 255,
            )
        )
    if config.mode == 2 and not schedule:
        if type(config.sequence_preset) is not int:
            raise ValueError("sequence_preset must be an integer")
        _integer(config.sequence_fade_duration, 0, 3199, "sequence_fade_duration")
        steps = config.sequence_fade_duration // 100
        return bytes(
            (
                percentage_to_value(config.brightness, 10, 100),
                PRESET_TO_WIRE.get(config.sequence_preset, 0) | ((steps & 15) << 4),
                ((steps >> 4) & 1) | (80 << 1),
            )
        )
    raise ValueError("supported scene modes are 0/1, plus 2 outside schedules")


def decode_scene(mode: int, data: bytes, *, masked_white: bool = True) -> SceneConfig:
    """f9.e.b (masked white) or f9.e.a (unmasked white).

    An unknown mode retains its mode number with brightness -1, matching the
    APK's partial decode. Other fields in that case are unused placeholders;
    no scene contents are inferred, and encoding unknown modes stays invalid.
    """
    if type(mode) is not int:
        raise ValueError("scene mode must be an integer")
    if len(data) != 3:
        raise ValueError("scene configuration requires three bytes")
    if mode == 0:
        mask = 127 if masked_white else 255
        return SceneConfig(
            0,
            value_to_percentage(data[0] & mask, 1, WHITE_MAX),
            temperature=value_to_percentage(data[1] & mask, 0, WHITE_MAX),
        )
    if mode == 1:
        return SceneConfig(
            1,
            value_to_percentage(data[0], 10, 100),
            hue=(data[1] >> 7) + (data[2] << 1),
            saturation=(data[1] & 127) / 100.0,
        )
    if mode == 2:
        return SceneConfig(
            2,
            value_to_percentage(data[0], 10, 100),
            sequence_preset=WIRE_TO_PRESET.get(data[1] & 15, 12),
            sequence_fade_duration=((data[1] >> 4) + ((data[2] & 1) << 4)) * 100,
            sequence_color_duration=(data[2] >> 1) * 100,
        )
    return SceneConfig(mode, -1)


@dataclass(frozen=True)
class PirSettings:
    """PIR configuration fields and original uninterpreted high flag bits.

    encode() and decode() operate on bytes without device communication.
    """
    nightlight: SceneConfig
    motion: SceneConfig
    sensitivity: int
    timeout: int
    motion_enabled: bool
    nightlight_enabled: bool
    luminosity_threshold: int
    reserved_flags_raw: int = 0  # C8 high bits 5..7, unclassified in APK

    def encode(self) -> bytes:
        """Encode as the APK does; not a lossless backup/restore operation."""
        if (
            type(self.motion_enabled) is not bool
            or type(self.nightlight_enabled) is not bool
        ):
            raise TypeError("motion_enabled and nightlight_enabled must be bool")
        if not isinstance(self.nightlight, SceneConfig) or not isinstance(
            self.motion, SceneConfig
        ):
            raise TypeError("nightlight and motion must be SceneConfig")
        _integer(self.nightlight.mode, 0, 2, "nightlight mode")
        _integer(self.motion.mode, 0, 2, "motion mode")
        _integer(self.sensitivity, 0, 15, "sensitivity")
        _byte(self.timeout, "timeout")
        _integer(self.luminosity_threshold, 0, 7, "luminosity threshold")
        if type(self.reserved_flags_raw) is not int or self.reserved_flags_raw & ~0xE0:
            raise ValueError("reserved PIR C8 flags must only use bits 5..7")
        return (
            bytes(
                (
                    self.nightlight.mode
                    | (self.motion.mode << 2)
                    | (self.sensitivity << 4),
                    self.timeout,
                )
            )
            + encode_scene(self.nightlight)
            + encode_scene(self.motion)
            + bytes(
                (
                    int(self.motion_enabled)
                    | (int(self.nightlight_enabled) << 1)
                    | (self.luminosity_threshold << 2)
                    | self.reserved_flags_raw,
                )
            )
        )

    @classmethod
    def decode(cls, data: bytes) -> "PirSettings":
        """Decode the PIR settings payload into a PirSettings instance."""
        if len(data) != 9:
            raise ValueError("PIR settings require nine bytes")
        return cls(
            decode_scene(data[0] & 3, data[2:5]),
            decode_scene((data[0] >> 2) & 3, data[5:8]),
            data[0] >> 4,
            data[1],
            bool(data[8] & 1),
            bool(data[8] & 2),
            (data[8] >> 2) & 7,
            data[8] & 0xE0,
        )


def pir_settings_get(destination: int) -> ExtendedCommand:
    """APK i9.l: 12 + destination LE16; no settings are changed."""
    return addressed_query(destination, 0x12)


def pir_settings_set(settings: PirSettings) -> ExtendedCommand:
    """APK i9.m: one unaddressed 11 + nine PIR configuration bytes.

    There is no target address in this command. Never imply a specific
    receiver or automatic success acknowledgement from the wire layout.
    """
    if not isinstance(settings, PirSettings):
        raise TypeError("settings must be PirSettings")
    return ExtendedCommand(query_frame(b"\x11" + settings.encode()))


def pir_luminosity_get(destination: int) -> ExtendedCommand:
    """APK i9.k: 13 + destination LE16; reply is a raw byte, not lux."""
    return addressed_query(destination, 0x13)
