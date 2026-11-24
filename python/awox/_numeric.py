"""APK float32 conversion and shared numeric/bit-field rules."""

from __future__ import annotations

import math
import struct


def _f32(value: float) -> float:
    return struct.unpack("<f", struct.pack("<f", value))[0]


def _integer(value: int, minimum: int, maximum: int, name: str) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f"{name} must be an integer in {minimum}..{maximum}")
    return value


def _byte(value: int, name: str = "value") -> int:
    return _integer(value, 0, 255, name)


def _weekdays_byte(mask: int, repeat: bool) -> int:
    """APK routine weekday bits 0..6 (Sunday first), repeat in bit 7."""
    if type(mask) is not int or not 0 <= mask <= 127:
        raise ValueError("weekday mask must be a seven-bit integer")
    if type(repeat) is not bool:
        raise TypeError("repeat must be bool")
    return mask | (0x80 if repeat else 0)


def percentage_to_value(percentage: int, minimum: int, maximum: int) -> int:
    """MathUtils.percentageToValue(III)I, including clamping/Java float rounding."""
    if minimum >= maximum:
        raise ValueError("minimum must be lower than maximum")
    _integer(percentage, -(1 << 31), (1 << 31) - 1, "percentage")
    percentage = max(0, min(100, percentage))
    value = _f32(_f32((maximum - minimum) * percentage) / _f32(100.0))
    return math.floor(_f32(value + minimum) + 0.5)


def value_to_percentage(value: int, minimum: int, maximum: int) -> int:
    """MathUtils.valueToPercentage(III)I; only increasing ranges are exposed."""
    if minimum >= maximum:
        raise ValueError("minimum must be lower than maximum")
    _integer(value, -(1 << 31), (1 << 31) - 1, "value")
    value = max(minimum, min(maximum, value))
    return math.floor(_f32(_f32((value - minimum) * 100.0) / (maximum - minimum)) + 0.5)
