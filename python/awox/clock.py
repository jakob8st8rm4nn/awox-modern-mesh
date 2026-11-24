"""Pure, explicit Modern Mesh time encoders from APK i9.s / i9.t.

No wall-clock access, Bluetooth, login, retry, automatic timezone generation or
implicit device write. Both original query payloads deliberately omit a target
address; they are controller-context commands, NOT addressed lamp setters.

These functions preserve the packet shape proven by the project DEX analysis.
They do not recreate the Android i9.e0 POSIX zone-rule generator.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Time29Ack:
    """A 0x29 status NOTIFICATION observed during one explicit ACK wait.

    A status 0 means positive APK protocol acknowledgement, not proof of an
    accurate/persisted device clock. There is no transaction ID, device
    provenance or reliable link from an individual write to this response.
    """

    status_code: int
    raw_payload: bytes

    @property
    def success(self) -> bool:
        """True when the returned 0x29 status code equals zero."""
        return self.status_code == 0


from .frames import ExtendedCommand, query_frame

UTC_2000_UNIX_SECONDS = 946684800
MAX_TIME_SECONDS = 0xFFFFFFFF


def _device_seconds(unix_milliseconds: int) -> int:
    if type(unix_milliseconds) is not int:
        raise TypeError("unix_milliseconds must be an integer")
    # Java's timestamp is milliseconds; the APK converts it to whole seconds.
    # Bounding instead of silently wrapping the original 32-bit wire field.
    seconds = unix_milliseconds // 1000 - UTC_2000_UNIX_SECONDS
    if not 0 <= seconds <= MAX_TIME_SECONDS:
        raise ValueError(
            "timestamp is not representable as uint32 seconds since 2000-01-01 UTC"
        )
    return seconds


def build_time(unix_milliseconds: int, offset_seconds: int) -> ExtendedCommand:
    """APK i9.s.c, property ``time``, query opcode 0x30.

    Payload: 30 || uint32_LE(seconds since UTC 2000) || int32_LE(current
    GMT/UTC offset incl. DST, in seconds) || 00. The APK *computes* the
    offset using Java TimeZone.getOffset(time); here the caller supplies it.

    No address in the payload, no automatic time or offset acquisition.
    """
    seconds = _device_seconds(unix_milliseconds)
    if type(offset_seconds) is not int:
        raise TypeError("offset_seconds must be an integer")
    if not -(1 << 31) <= offset_seconds < (1 << 31):
        raise ValueError("offset_seconds must fit signed 32 bits")
    payload = (
        b"\x30"
        + seconds.to_bytes(4, "little")
        + offset_seconds.to_bytes(4, "little", signed=True)
        + b"\x00"
    )
    return ExtendedCommand(query_frame(payload))


def build_time_with_timezone(
    unix_milliseconds: int, posix_rule: str
) -> ExtendedCommand:
    """APK i9.t.c, property ``time_with_timezone``, opcode 0x29.

    Payload: 29 || uint32_LE(seconds since UTC 2000) || 32 ASCII bytes.
    The APK's i9.e0 constructs the rule from ZoneRules; that conversion is
    NOT provided or claimed equivalent here. Supply a verified rule yourself.
    Length <= 30 and zero padding are drawn from the static APK analysis.
    """
    seconds = _device_seconds(unix_milliseconds)
    if not isinstance(posix_rule, str):
        raise TypeError("posix_rule must be a string")
    if not str.isascii(posix_rule):
        raise ValueError("posix_rule must contain ASCII only")
    if not 1 <= len(posix_rule) <= 30:
        raise ValueError(
            "posix_rule must contain 1..30 printable non-space ASCII bytes"
        )
    try:
        rule = posix_rule.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("posix_rule must contain ASCII only") from exc
    if not 1 <= len(rule) <= 30 or any(byte < 0x21 or byte > 0x7E for byte in rule):
        raise ValueError(
            "posix_rule must contain 1..30 printable non-space ASCII bytes"
        )
    return ExtendedCommand(
        query_frame(b"\x29" + seconds.to_bytes(4, "little") + rule.ljust(32, b"\x00"))
    )
