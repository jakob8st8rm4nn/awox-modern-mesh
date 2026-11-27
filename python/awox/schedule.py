"""APK 1.14.10/1.14.11 mesh schedule configuration and replies.

Read-only queries/responses use 0x35; configuration writes/replies use
0x33, as documented by j9.e/i9.e, j9.r/i9.r and h9.i/g9.j. No firmware timing, persistence or slot count
is inferred. In particular a read is NOT a command to enable an automation.
"""

from __future__ import annotations

from dataclasses import dataclass

from .light_settings import LightSettings, decode_light_settings
from ._numeric import _weekdays_byte

SCHEDULE_PAIRS = {"nightlight": (5, 6), "dawn_simulator": (7, 8)}
SCHEDULE_SINGLE_READS = {"timer": 2, "program": 3}  # APK i9.e: single 0x35 query


@dataclass(frozen=True)
class SchedulePart:
    """One decoded schedule routine, including its device error status if present."""
    mesh_id: int
    routine_id: int
    enabled: bool | None
    error_code: int | None
    time_mode: int | None
    minutes: int | None
    hour: int | None
    minute: int | None
    repeat: bool | None
    weekdays_mask: int | None
    fade_minutes: int | None
    light_fields: bytes | None
    current_part: int | None
    total_part: int | None
    raw_response: bytes

    @property
    def valid(self) -> bool:
        """Whether this decoded schedule part has the valid status flag."""
        return self.error_code is None

    @property
    def light_settings(self) -> LightSettings | None:
        """APK-decoded light fields, or None for a device error reply."""
        return (
            decode_light_settings(self.light_fields)
            if self.light_fields is not None
            else None
        )

    @property
    def is_clock_sentinel(self) -> bool:
        """True only for the APK-recognized time_mode=1, 31:63 marker.

        The firmware meaning of this marker is not inferred.
        """
        return self.time_mode == 1 and self.hour == 31 and self.minute == 63

    @property
    def clock_extra_flag(self) -> bool | None:
        """APK f9798n: raw[5] bit 6 in clock mode; purpose not yet proven."""
        if self.time_mode in (None, 0):
            return None
        return bool(self.raw_response[5] & 0x40)


@dataclass(frozen=True)
class ScheduleRead:
    """An addressed schedule read. Timer (2) and program (3) are single-part; 5/6 and 7/8 are pairs.

    For a pair, end=None means missing response, not firmware confirmation
    that the end routine does not exist. For program routine 3, complete
    means ONE addressed valid reply, not proof of all program slots.
    """

    mesh_id: int
    property_name: str
    start: SchedulePart
    end: SchedulePart | None

    @property
    def complete(self) -> bool:
        """Whether the expected schedule part or pair was fully received."""
        if self.property_name in SCHEDULE_SINGLE_READS:
            return (
                self.start.valid
                and self.start.mesh_id == self.mesh_id
                and self.start.routine_id == SCHEDULE_SINGLE_READS[self.property_name]
                and self.end is None
            )
        if self.property_name not in SCHEDULE_PAIRS:
            return False
        start_routine, end_routine = SCHEDULE_PAIRS[self.property_name]
        return (
            self.start.valid
            and self.start.mesh_id == self.mesh_id
            and self.start.routine_id == start_routine
            and self.end is not None
            and self.end.valid
            and self.end.mesh_id == self.mesh_id
            and self.end.routine_id == end_routine
        )


def parse_schedule_read(decrypted_response: bytes) -> SchedulePart:
    """Decode only fields established in g9.j.e's 0x35 receiver.

    Error reply: 35 addrLE FF errorCode routineId. The APK logs this
    instead of returning a positive schedule. Preserve the code as-is.
    Normal reply: 35 addrLE routine/enabled, followed by bytes 4..12
    for time/day/fade/light and current/total. Trailer is retained.
    """
    if not isinstance(decrypted_response, (bytes, bytearray)):
        raise TypeError("schedule reply must be bytes")
    if len(decrypted_response) < 6 or decrypted_response[0] != 0x35:
        raise ValueError("expected decrypted 0x35 schedule response")
    if decrypted_response[3] == 0xFF:
        if decrypted_response[5] not in (2, 3, 5, 6, 7, 8):
            raise ValueError("unexpected schedule-error routine ID")
    else:
        if len(decrypted_response) < 13:
            raise ValueError("valid schedule reply needs at least 13 bytes")
        if decrypted_response[3] & 0x7F not in (2, 3, 5, 6, 7, 8):
            raise ValueError("unexpected schedule routine ID")
    raw = bytes(decrypted_response)
    if len(raw) < 6 or raw[0] != 0x35:
        raise ValueError("expected decrypted 0x35 schedule response")
    mesh_id = int.from_bytes(raw[1:3], "little")
    if raw[3] == 0xFF:
        routine = raw[5]
        if routine not in (2, 3, 5, 6, 7, 8):
            raise ValueError("unexpected schedule-error routine ID")
        return SchedulePart(
            mesh_id,
            routine,
            None,
            raw[4],
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            raw,
        )
    if len(raw) < 13:
        raise ValueError("valid schedule reply needs at least 13 bytes")
    routine = raw[3] & 0x7F
    if routine not in (2, 3, 5, 6, 7, 8):
        raise ValueError("unexpected schedule routine ID")
    # APK g9.j.e forces routine 2 (timer) to relative duration mode.
    mode = 0 if routine == 2 else raw[4] & 3
    # APK: time mode 0 carries a 12-bit duration; for others hour/minute.
    duration = (((raw[4] >> 4) & 0xF) << 8 | raw[5]) if mode == 0 else None
    hour = (raw[5] & 31) if mode != 0 else None
    minute = (raw[4] >> 2) if mode != 0 else None
    return SchedulePart(
        mesh_id,
        routine,
        bool(raw[3] & 0x80),
        None,
        mode,
        duration,
        hour,
        minute,
        bool(raw[6] & 0x80),
        raw[6] & 0x7F,
        raw[7] & 0x3F,
        raw[8:12],
        raw[12] & 0x0F,
        (raw[12] >> 4) & 0x0F,
        raw,
    )


@dataclass(frozen=True)
class ScheduleWritePart:
    """Byte-exact 10-byte schedule settings used in APK i9.r.c (type 0x33).

    This is deliberately a transparent protocol value, not a background
    scheduler. timer/clock build new settings; from_read preserves unknown
    flags/light encodings when editing an existing record. No BLE I/O.
    """

    settings: bytes

    def __post_init__(self):
        if (
            not isinstance(self.settings, (bytes, bytearray))
            or len(self.settings) != 10
        ):
            raise ValueError("schedule settings must contain precisely ten bytes")
        settings = bytes(self.settings)
        if len(settings) != 10:
            raise ValueError("schedule settings must contain precisely ten bytes")
        object.__setattr__(self, "settings", settings)
        if self.routine_id not in (2, 3, 5, 6, 7, 8):
            raise ValueError("supported schedule routine IDs are 2, 3, 5, 6, 7, 8")

    @classmethod
    def from_read(cls, part: SchedulePart) -> "ScheduleWritePart":
        """Copy the ten original schedule setting bytes from a valid read response."""
        if not isinstance(part, SchedulePart) or not part.valid:
            raise ValueError("a valid device schedule response is required")
        raw = part.raw_response
        if len(raw) < 13 or raw[0] != 0x35:
            raise ValueError("invalid original schedule response")
        if int.from_bytes(raw[1:3], "little") != part.mesh_id or (raw[3] & 0x7F) != part.routine_id:
            raise ValueError("original schedule response does not match device or routine")
        return cls(raw[3:13])

    @classmethod
    def timer(
        cls, minutes: int, light_fields: bytes, *, enabled: bool, fade_minutes: int = 0
    ) -> "ScheduleWritePart":
        """Create relative timer routine 2; no implicit device read or write.

        Unspecified fields start at zero, as in the APK encoder's buffer.
        Use from_read when editing a device's existing settings instead.
        """
        return (
            cls(b"\x02" + bytes(9))
            .with_duration_minutes(minutes)
            .with_light_fields(light_fields)
            .with_fade_minutes(fade_minutes)
            .with_enabled(enabled)
        )

    @classmethod
    def clock(
        cls,
        routine_id: int,
        hour: int,
        minute: int,
        light_fields: bytes,
        *,
        enabled: bool,
        weekdays_mask: int = 0,
        repeat: bool = False,
        fade_minutes: int = 0,
    ) -> "ScheduleWritePart":
        """Create clock mode 1 for program (3), nightlight (5/6), dawn (7/8).

        Sunday is weekday bit 0. Other raw time modes/flags are retained by
        from_read; this builder does not assign them unproven meanings.
        Paired writes set their part markers in the existing send path.
        """
        if type(routine_id) is not int or routine_id not in (3, 5, 6, 7, 8):
            raise ValueError("clock routine ID must be 3, 5, 6, 7 or 8")
        return (
            cls(bytes((routine_id, 1)) + bytes(8))
            .with_clock_time(hour, minute)
            .with_weekdays(weekdays_mask, repeat)
            .with_light_fields(light_fields)
            .with_fade_minutes(fade_minutes)
            .with_enabled(enabled)
        )

    def with_light_fields(self, light_fields: bytes) -> "ScheduleWritePart":
        """Replace only the four light bytes; use routine_*_settings to build them."""
        if not isinstance(light_fields, (bytes, bytearray)) or len(light_fields) != 4:
            raise ValueError("routine light fields must contain exactly four bytes")
        return ScheduleWritePart(
            self.settings[:5] + bytes(light_fields) + self.settings[9:]
        )

    def with_fade_minutes(self, minutes: int) -> "ScheduleWritePart":
        """Update the six-bit fade field; preserve its two unknown high bits."""
        if type(minutes) is not int or not 0 <= minutes <= 63:
            raise ValueError("fade_minutes must be an integer 0..63")
        raw = bytearray(self.settings)
        raw[4] = (raw[4] & 0xC0) | minutes
        return ScheduleWritePart(bytes(raw))

    @property
    def routine_id(self) -> int:
        """Routine ID stored in the low seven bits of the first setting byte."""
        return self.settings[0] & 0x7F

    @property
    def enabled(self) -> bool:
        """Enable flag stored in the high bit of the first setting byte."""
        return bool(self.settings[0] & 0x80)

    def with_enabled(self, enabled: bool) -> "ScheduleWritePart":
        """Update ONLY the original APK routine-enable bit (7)."""
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        raw = bytearray(self.settings)
        raw[0] = (raw[0] & 0x7F) | (0x80 if enabled else 0)
        return ScheduleWritePart(bytes(raw))

    def with_clock_time(self, hour: int, minute: int) -> "ScheduleWritePart":
        """Update the APK clock fields, retaining mode and the time flag.

        Time mode 0 is a duration and cannot be edited as clock time.
        """
        if type(hour) is not int or not 0 <= hour <= 23:
            raise ValueError("hour must be 0..23")
        if type(minute) is not int or not 0 <= minute <= 59:
            raise ValueError("minute must be 0..59")
        # The APK always treats routine 2 as a relative-duration timer,
        # even if the received raw mode bits are nonzero.
        if self.routine_id == 2 or (self.settings[1] & 3) == 0:
            raise ValueError(
                "time mode 0 (including timer routine 2) cannot use wall-clock time"
            )
        raw = bytearray(self.settings)
        raw[1] = (raw[1] & 3) | (minute << 2)
        raw[2] = (raw[2] & 0xE0) | hour
        return ScheduleWritePart(bytes(raw))

    def with_duration_minutes(self, minutes: int) -> "ScheduleWritePart":
        """Edit APK's 12-bit relative duration, preserving all unrelated bits.

        For the EGLO timer UI the valid interval is 1..1439 minutes
        (00:00 is rejected by the Android editor). This is not a request
        to activate or run the timer. Only timer routine 2 is accepted.
        """
        if type(minutes) is not int or not 1 <= minutes <= 1439:
            raise ValueError("timer duration must be an integer 1..1439 minutes")
        if self.routine_id != 2:
            raise ValueError("relative timer routine 2 required")
        raw = bytearray(self.settings)
        # The APK decoder forces this routine's effective time mode to 0.
        # The writer must encode that mode as 0 too, while retaining the
        # other, unclassified bits 2..3 of the original response byte.
        raw[1] = (raw[1] & 0x0C) | ((minutes >> 8) << 4)
        raw[2] = minutes & 0xFF
        return ScheduleWritePart(bytes(raw))

    def with_weekdays(self, mask: int, repeat: bool) -> "ScheduleWritePart":
        """Seven days, Sunday=bit0; recurrence=bit7, as original APK."""
        weekdays = _weekdays_byte(mask, repeat)
        raw = bytearray(self.settings)
        raw[3] = weekdays
        return ScheduleWritePart(bytes(raw))


@dataclass(frozen=True)
class ScheduleSetResponse:
    """A 0x33 reply, not proof of persistent execution or saved schedule.

    Code 0x99 is the APK's follow-up trigger for start routines 5 and 7.
    Only 0x00 is the documented success callback; other device codes are
    carried unchanged without invented meanings. ACK byte 4 is called
    ``action`` in the original APK. In observed hardware ACKs it matches
    the response opcode, but the APK does not enforce that relationship.
    """

    mesh_id: int
    status_code: int
    action: int
    routine_id: int
    raw_response: bytes

    @property
    def success(self) -> bool:
        """True only for a decoded successful 0x33 status."""
        return self.status_code == 0

    @property
    def requires_followup(self) -> bool:
        """Whether the 0x33 result requests the second part of a pair."""
        return self.status_code == 0x99 and self.routine_id in (5, 7)


@dataclass(frozen=True)
class ScheduleWriteResult:
    """A completed local write attempt; missing ACK leaves outcome UNKNOWN.

    For timer routine 2 and program routine 3, complete means a positive
    0x00 device ACK to their single packet. For paired routines, complete is strictly an observed
    final response code 0 for routine 6/8 after the 0x99 continuation.
    Neither case proves saved settings or actual execution. No implicit readback, retry or rollback is performed.
    """

    mesh_id: int
    property_name: str
    start_response: ScheduleSetResponse | None
    end_response: ScheduleSetResponse | None
    end_sent: bool

    @property
    def complete(self) -> bool:
        """Whether the requested write or pair has a complete response result."""
        if self.property_name in ("timer", "program"):
            expected_routine = SCHEDULE_SINGLE_READS[self.property_name]
            return bool(
                not self.end_sent
                and self.end_response is None
                and self.start_response is not None
                and self.start_response.mesh_id == self.mesh_id
                and self.start_response.routine_id == expected_routine
                and self.start_response.success
            )
        if self.property_name not in SCHEDULE_PAIRS:
            return False
        start_routine, end_routine = SCHEDULE_PAIRS[self.property_name]
        return bool(
            self.end_sent
            and self.start_response is not None
            and self.start_response.mesh_id == self.mesh_id
            and self.start_response.routine_id == start_routine
            and self.start_response.requires_followup
            and self.end_response is not None
            and self.end_response.mesh_id == self.mesh_id
            and self.end_response.routine_id == end_routine
            and self.end_response.success
        )


def parse_schedule_set(decrypted_response: bytes) -> ScheduleSetResponse:
    """APK g9.j.e 0x33 receiver: addr LE, status, action, routine.

    Response type 0x33 is required for timer, program, nightlight and dawn. Do not
    treat another opcode as a successful device acknowledgement.
    """
    if not isinstance(decrypted_response, (bytes, bytearray)):
        raise TypeError("schedule write reply must be bytes")
    if len(decrypted_response) < 6 or decrypted_response[0] != 0x33:
        raise ValueError("expected decrypted 0x33 schedule reply")
    if decrypted_response[5] not in (2, 3, 5, 6, 7, 8):
        raise ValueError("unexpected schedule-write routine ID")
    raw = bytes(decrypted_response)
    if len(raw) < 6 or raw[0] != 0x33:
        raise ValueError("expected decrypted 0x33 schedule reply")
    routine = raw[5]
    if routine not in (2, 3, 5, 6, 7, 8):
        raise ValueError("unexpected schedule-write routine ID")
    return ScheduleSetResponse(
        int.from_bytes(raw[1:3], "little"), raw[3], raw[4], routine, raw
    )


from .frames import ExtendedCommand, addressed_query


def schedule_get(destination: int, routine_id: int) -> ExtendedCommand:
    """APK i9.e/j9.e: 35 + addressLE16 + routine ID (read only).

    Routine 2 is timer; 3 is program; 5/6 nightlight; 7/8 dawn.
    Reading a routine never enables or writes the automation.
    """
    if type(routine_id) is not int or routine_id not in (2, 3, 5, 6, 7, 8):
        raise ValueError("routine_id must be 2, 3, 5, 6, 7 or 8")
    return addressed_query(destination, 0x35, bytes((routine_id,)))


def schedule_set(destination: int, settings) -> ExtendedCommand:
    """APK i9.r.c / j9.r.c: 33 + addressLE16 + exactly 10 fields.

    Encode a deliberately supplied protocol value. For routine 2 only,
    the APK forces relative time mode 0 in the outgoing packet. Retain
    all original settings and unrelated bits. No implicit start/end
    pairing, retries, clock setting, or write-through side effects.
    """

    if not isinstance(settings, ScheduleWritePart):
        raise TypeError("settings must be ScheduleWritePart")
    encoded_settings = settings.settings
    if settings.routine_id == 2:
        normalized = bytearray(encoded_settings)
        normalized[1] &= 252
        encoded_settings = bytes(normalized)
    return addressed_query(destination, 0x33, encoded_settings)
