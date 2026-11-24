"""Offline formatting of APK Modern-Mesh POSIX time-zone rules.

Reconstruction of the *pure formatting* portions of Android i9.e0 (1.14.11)
/ j9.e0 (1.14.10), and i9.t.c's rule assembly. The caller must provide
Java ZoneOffsetTransitionRule-equivalent values and the resolved abbreviations.

There is NO IANA/Android zone database or ICU name lookup, Bluetooth I/O,
implicit clock reading, firmware time synchronization, or retry logic here.
A produced rule is not independently validated against the target firmware.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import re

_MONTH_DAYS_NONLEAP = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_SECONDS_IN_DAY = 86400
_DEFAULT_TRANSITION_SECONDS = 7200
_ANDROID_NAME = re.compile(r"[A-Za-z]{3,}\Z")


def _integer(value: int, name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an integer")
    if not -(1 << 31) < value < (1 << 31):
        # Android ZoneOffsetTransitionRule fields are far narrower than this.
        # Excluding INT_MIN avoids the Java Math.abs(INT_MIN) overflow trap.
        raise ValueError(f"{name} must fit the supported signed-32-bit range")
    return value


def apk_posix_offset(offset_seconds: int) -> str:
    """Match i9.e0.a: POSIX sign is INVERSE of GMT offset.

    Examples: UTC+01:00 => '-1', UTC-05:30 => '5:30'.
    """
    offset_seconds = _integer(offset_seconds, "offset_seconds")
    negative = -offset_seconds
    prefix = "-" if negative < 0 else ""
    magnitude = abs(negative)
    hh, rem = divmod(magnitude, 3600)
    mm, ss = divmod(rem, 60)
    result = f"{prefix}{hh}"
    if mm or ss:
        result += f":{mm:02d}"
    if ss:
        result += f":{ss:02d}"
    return result


def _java_div(n: int, d: int) -> int:
    """Java integer division truncates toward zero (unlike Python //)."""
    return n // d if n >= 0 else -((-n) // d)


def apk_transition_time(seconds: int) -> str:
    """Match i9.e0.b, including its unusual negative-subhour behavior.

    This is the APK's formatter, not a normalization of POSIX transition time.
    In particular, -1800 is rendered as '0:30' by the original algorithm.
    """
    seconds = _integer(seconds, "seconds")
    hh = _java_div(seconds, 3600)
    remainder = seconds - hh * 3600
    minutes = _java_div(remainder, 60)
    mm = abs(minutes)
    ss = abs(remainder - minutes * 60)
    result = str(hh)
    if mm or ss:
        result += f":{mm:02d}"
    if ss:
        result += f":{ss:02d}"
    return result


@dataclass(frozen=True)
class AndroidTransitionRule:
    """Explicit subset of java.time.zone.ZoneOffsetTransitionRule.

    day_of_week: ISO Java DayOfWeek (Monday=1,...,Sunday=7), or None.
    local_time_seconds: seconds since local midnight (0..86399).
    midnight_end_of_day=True represents 24:00 (Java isMidnightEndOfDay).
    time_definition: 'WALL', 'STANDARD', or 'UTC' (Java enum).
    Offsets are GMT/UTC seconds, as returned by ZoneOffset.getTotalSeconds().
    """

    month: int
    day_of_month_indicator: int
    day_of_week: Optional[int]
    local_time_seconds: int
    time_definition: str
    standard_offset_seconds: int
    offset_before_seconds: int
    offset_after_seconds: int
    midnight_end_of_day: bool = False

    def __post_init__(self) -> None:
        m = _integer(self.month, "month")
        if not 1 <= m <= 12:
            raise ValueError("month must be 1..12")
        day = _integer(self.day_of_month_indicator, "day_of_month_indicator")
        if not (-28 <= day <= -1 or 1 <= day <= 31):
            raise ValueError("day_of_month_indicator must be -28..-1 or 1..31")
        if self.day_of_week is not None:
            w = _integer(self.day_of_week, "day_of_week")
            if not 1 <= w <= 7:
                raise ValueError("day_of_week must be 1..7 or None")
        secs = _integer(self.local_time_seconds, "local_time_seconds")
        if not 0 <= secs < _SECONDS_IN_DAY:
            raise ValueError("local_time_seconds must be 0..86399")
        if type(self.midnight_end_of_day) is not bool:
            raise TypeError("midnight_end_of_day must be boolean")
        if self.midnight_end_of_day and secs != 0:
            raise ValueError("midnight_end_of_day requires local_time_seconds == 0")
        if self.time_definition not in ("WALL", "STANDARD", "UTC"):
            raise ValueError("time_definition must be WALL, STANDARD or UTC")
        for name in (
            "standard_offset_seconds",
            "offset_before_seconds",
            "offset_after_seconds",
        ):
            value = _integer(getattr(self, name), name)
            if not -64800 <= value <= 64800:
                raise ValueError(f"{name} outside Java ZoneOffset +/-18-hour range")


def _transition_seconds(rule: AndroidTransitionRule) -> int:
    """APK i9.e0.e: convert from time definition to the POSIX rule time."""
    seconds = _SECONDS_IN_DAY if rule.midnight_end_of_day else rule.local_time_seconds
    if rule.time_definition == "UTC":
        return seconds + rule.offset_before_seconds
    if rule.time_definition == "STANDARD":
        return seconds + rule.offset_before_seconds - rule.standard_offset_seconds
    return seconds


def format_apk_transition(rule: AndroidTransitionRule) -> str | None:
    """APK i9.e0.c: M- or J-rule, or None if not representable.

    A returned string does not imply the firmware accepts that transition.
    """
    if not isinstance(rule, AndroidTransitionRule):
        raise TypeError("rule must be AndroidTransitionRule")
    day = rule.day_of_month_indicator
    if rule.day_of_week is None:
        if day < 0:
            if rule.month == 2:
                return None  # Original special case for February.
            day = _MONTH_DAYS_NONLEAP[rule.month - 1] + day + 1
        # Month.firstDayOfYear(false) uses a non-leap year.
        ordinal = sum(_MONTH_DAYS_NONLEAP[: rule.month - 1]) + day
        rendered = f"J{ordinal}"
    else:
        if (-7 <= day < 0) or day >= 25:
            week = 5
        elif day in (1, 8, 15, 22):
            week = (day - 1) // 7 + 1
        else:
            return None
        weekday = 0 if rule.day_of_week == 7 else rule.day_of_week
        rendered = f"M{rule.month}.{week}.{weekday}"
    seconds = _transition_seconds(rule)
    return (
        rendered
        if seconds == _DEFAULT_TRANSITION_SECONDS
        else f"{rendered}/{apk_transition_time(seconds)}"
    )


def _android_name(name: str | None, fallback: str) -> str:
    """Caller supplies Android-resolved short name; invalid name -> APK fallback."""
    if name is not None and not isinstance(name, str):
        raise TypeError("timezone abbreviation must be a string or None")
    return name if name is not None and _ANDROID_NAME.fullmatch(name) else fallback


def _fits_wire_rule(value: str) -> bool:
    # APK i9.t: empty, NUL and more than 30 US-ASCII bytes are unrepresentable.
    if not 1 <= len(value) <= 30:
        return False
    try:
        data = value.encode("ascii")
    except UnicodeEncodeError:
        return False
    return bool(data) and b"\0" not in data and len(data) <= 30


def format_apk_fixed_timezone(
    standard_offset_seconds: int, *, has_future_transition: bool = False
) -> str | None:
    """i9.t.c fixed/no-recurring-rule branch, using i9.e0.a.

    An APK ZoneRules without recurrence but with a future transition returns
    null, rather than pretending the fixed offset will remain valid forever.
    """
    if type(has_future_transition) is not bool:
        raise TypeError("has_future_transition must be bool")
    _integer(standard_offset_seconds, "standard_offset_seconds")
    if not -64800 <= standard_offset_seconds <= 64800:
        raise ValueError(
            "standard_offset_seconds outside Java ZoneOffset +/-18-hour range"
        )
    value = f"UTC{apk_posix_offset(standard_offset_seconds)}"
    return None if has_future_transition or not _fits_wire_rule(value) else value


def format_apk_dst_timezone(
    standard_name: str | None,
    standard_offset_seconds: int,
    daylight_name: str | None,
    start: AndroidTransitionRule,
    end: AndroidTransitionRule,
) -> str | None:
    """Match i9.t.c rule assembly with EXPLICIT Java-style transition inputs.

    The caller must choose the original Android transition rules and resolve
    the current standard/DST abbreviations. No IANA TZ parser/ICU included.
    Return None where the APK's builder would return null (unsupported rule,
    missing positive/negative transition, or more than 30 rule bytes).
    """
    _integer(standard_offset_seconds, "standard_offset_seconds")
    if not -64800 <= standard_offset_seconds <= 64800:
        raise ValueError(
            "standard_offset_seconds outside Java ZoneOffset +/-18-hour range"
        )
    if not isinstance(start, AndroidTransitionRule) or not isinstance(
        end, AndroidTransitionRule
    ):
        raise TypeError("start and end must be AndroidTransitionRule")
    if start.offset_after_seconds <= start.offset_before_seconds:
        return None
    if end.offset_after_seconds >= end.offset_before_seconds:
        return None
    start_part = format_apk_transition(start)
    end_part = format_apk_transition(end)
    if start_part is None or end_part is None:
        return None
    std_name = _android_name(standard_name, "STD")
    dst_name = _android_name(daylight_name, "DST")
    # The APK omits the DST offset when it is standard_offset + 3600.
    daylight_offset = start.offset_after_seconds
    suffix = (
        ""
        if daylight_offset == standard_offset_seconds + 3600
        else apk_posix_offset(daylight_offset)
    )
    parts = (
        std_name,
        apk_posix_offset(standard_offset_seconds),
        dst_name,
        suffix,
        ",",
        start_part,
        ",",
        end_part,
    )
    if sum(map(len, parts)) > 30:
        return None
    rendered = "".join(parts)
    return rendered if _fits_wire_rule(rendered) else None
