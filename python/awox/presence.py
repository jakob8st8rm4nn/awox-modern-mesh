"""EGLO presence simulator 0x3C read response (APK 1.14.10/11).

Read/write configuration codecs and response parsing; no automation or
background work. This module performs no device I/O.
The 48 stored half-hour flags are kept individually; APK UI may display them
as 24 hour boxes, but the wire representation is 48 distinct bits.
"""

from __future__ import annotations

from dataclasses import dataclass

from .light_settings import LightSettings, decode_light_settings
from ._numeric import _weekdays_byte


@dataclass(frozen=True)
class PresenceRead:
    """A single addressed 0x3C routine-1 response, with original bytes.

    A non-null ``error_code`` is a device-reported failure, not an inactive
    schedule. An observed response does not prove actual timer execution or
    persistence. Light settings are APK-decoded and raw bytes retained.
    """

    mesh_id: int
    routine_id: int
    enabled: bool | None
    error_code: int | None
    repeat: bool | None
    weekdays_mask: int | None
    light_fields: bytes | None
    half_hour_slots: tuple[bool, ...] | None
    random_enabled: bool | None
    current_part: int | None
    total_part: int | None
    raw_response: bytes

    @property
    def valid(self) -> bool:
        """Whether the decoded presence result is marked valid."""
        return self.error_code is None

    @property
    def light_settings(self) -> LightSettings | None:
        """Shared APK light codec; None if the device replied with an error."""
        return (
            decode_light_settings(self.light_fields)
            if self.light_fields is not None
            else None
        )


def parse_presence_read(decrypted_response: bytes) -> PresenceRead:
    """Parse full 0x3C frame after ATT decryption (opcode included).

    Exact 1.14.11 g9.j.e and 1.14.10 h9.i.e offsets:
    [1:3] address LE, [3] routine low 7/enabled high bit,
    [4] seven weekday flags/repeat high bit, [5:9] light fields,
    [9:15] 48 bits little-endian within bytes, [15] random bit0,
    [16] two 4-bit part counters. Error: [3]=FF, [4]=error, [5]=routine.
    """
    if not isinstance(decrypted_response, (bytes, bytearray)):
        raise TypeError("presence reply must be bytes")
    if len(decrypted_response) < 6 or decrypted_response[0] != 0x3C:
        raise ValueError("expected decrypted 0x3C presence reply")
    raw = bytes(decrypted_response)
    if len(raw) < 6 or raw[0] != 0x3C:
        raise ValueError("expected decrypted 0x3C presence reply")
    mesh_id = int.from_bytes(raw[1:3], "little")
    if raw[3] == 0xFF:
        if raw[5] != 1:
            raise ValueError("unexpected presence error routine ID")
        return PresenceRead(
            mesh_id, 1, None, raw[4], None, None, None, None, None, None, None, raw
        )
    if len(raw) < 17:
        raise ValueError("valid presence reply needs at least 17 bytes")
    routine = raw[3] & 0x7F
    if routine != 1:
        raise ValueError("unexpected presence routine ID")
    slots = tuple(bool(raw[9 + i // 8] & (1 << (i % 8))) for i in range(48))
    return PresenceRead(
        mesh_id=mesh_id,
        routine_id=routine,
        enabled=bool(raw[3] & 0x80),
        error_code=None,
        repeat=bool(raw[4] & 0x80),
        weekdays_mask=raw[4] & 0x7F,
        light_fields=raw[5:9],
        half_hour_slots=slots,
        random_enabled=bool(raw[15] & 1),
        current_part=raw[16] & 0x0F,
        total_part=(raw[16] >> 4) & 0x0F,
        raw_response=raw,
    )


@dataclass(frozen=True)
class PresenceWritePart:
    """Fourteen Modern presence settings bytes, newly built or read from 0x3C.

    Passed unchanged to 0x3B. Edits are explicit; no APK UI or scheduling
    policy is run by this value class. This is a device configuration, not a
    background Python timer.
    """

    settings: bytes

    def __post_init__(self):
        if (
            not isinstance(self.settings, (bytes, bytearray))
            or len(self.settings) != 14
        ):
            raise ValueError("presence settings must be exactly 14 bytes")
        settings = bytes(self.settings)
        if len(settings) != 14:
            raise ValueError("presence settings must be exactly 14 bytes")
        object.__setattr__(self, "settings", settings)
        if (self.settings[0] & 0x7F) != 1:
            raise ValueError("presence routine ID must be 1")

    @classmethod
    def from_read(cls, reading: PresenceRead) -> "PresenceWritePart":
        """Start a writable presence configuration from an existing read result."""
        if (
            not isinstance(reading, PresenceRead)
            or not reading.valid
            or reading.routine_id != 1
            or len(reading.raw_response) < 17
            or reading.raw_response[0] != 0x3C
            or int.from_bytes(reading.raw_response[1:3], "little") != reading.mesh_id
        ):
            raise ValueError("valid, addressed presence 0x3C reply required")
        return cls(reading.raw_response[3:17])

    @classmethod
    def create(
        cls,
        light_fields: bytes,
        *,
        enabled: bool,
        weekdays_mask: int = 0,
        repeat: bool = False,
        random_enabled: bool = False,
    ) -> "PresenceWritePart":
        """Create routine 1 with all 48 half-hour slots initially clear.

        Select slots explicitly with with_half_hour_slot. Unspecified fields
        start at zero, as in the APK i9.p.c buffer. No device I/O.
        """
        return (
            cls(b"\x01" + bytes(13))
            .with_light_fields(light_fields)
            .with_weekdays(weekdays_mask, repeat)
            .with_random_enabled(random_enabled)
            .with_enabled(enabled)
        )

    def with_light_fields(self, light_fields: bytes) -> "PresenceWritePart":
        """Replace only the four light bytes; use routine_*_settings to build them."""
        if not isinstance(light_fields, (bytes, bytearray)) or len(light_fields) != 4:
            raise ValueError("routine light fields must contain exactly four bytes")
        return PresenceWritePart(
            self.settings[:2] + bytes(light_fields) + self.settings[6:]
        )

    def with_weekdays(self, mask: int, repeat: bool) -> "PresenceWritePart":
        """Seven weekdays, Sunday=bit0; recurrence=bit7, as in APK i9.p.c."""
        weekdays = _weekdays_byte(mask, repeat)
        return PresenceWritePart(
            self.settings[:1] + bytes((weekdays,)) + self.settings[2:]
        )

    def with_random_enabled(self, enabled: bool) -> "PresenceWritePart":
        """Change only the APK random bit, retaining all other stored bits."""
        if type(enabled) is not bool:
            raise TypeError("random_enabled must be bool")
        data = bytearray(self.settings)
        data[12] = (data[12] & 0xFE) | int(enabled)
        return PresenceWritePart(bytes(data))

    @property
    def enabled(self) -> bool:
        """Whether the presence simulator is enabled in these raw settings."""
        return bool(self.settings[0] & 0x80)

    def with_enabled(self, value: bool) -> "PresenceWritePart":
        """Return a new part with the presence enable bit changed."""
        if type(value) is not bool:
            raise TypeError("enabled must be a bool")
        data = bytearray(self.settings)
        data[0] = (data[0] & 0x7F) | (0x80 if value else 0)
        return PresenceWritePart(bytes(data))

    def with_half_hour_slot(self, index: int, enabled: bool) -> "PresenceWritePart":
        """Change exactly one of the 48 fields (slot 0 = 00:00-00:30)."""
        if type(index) is not int or not 0 <= index < 48:
            raise ValueError("slot index must be 0..47")
        if type(enabled) is not bool:
            raise TypeError("slot value must be a bool")
        data = bytearray(self.settings)
        byte_index, bit = 6 + index // 8, 1 << (index % 8)
        data[byte_index] = (
            (data[byte_index] | bit) if enabled else (data[byte_index] & ~bit)
        )
        return PresenceWritePart(bytes(data))


@dataclass(frozen=True)
class PresenceSetResponse:
    """ACK for opcode 0x3B; status zero is positive, not persistence proof.

    ACK byte 4 is ``action`` in the original APK; it is not a part counter.
    """

    mesh_id: int
    status_code: int
    action: int
    routine_id: int
    raw_response: bytes

    @property
    def success(self) -> bool:
        """True only for the decoded successful status value."""
        return self.status_code == 0


def parse_presence_set(decrypted_response: bytes) -> PresenceSetResponse:
    """APK g9.j.e / h9.i.e: 3B addrLE16 status action routine.

    The APK shares an ACK dispatch with 0x33 but *not* the opcode. A 0x99
    reply for presence does not authorize a second command.
    """
    if not isinstance(decrypted_response, (bytes, bytearray)):
        raise TypeError("presence write reply must be bytes")
    if len(decrypted_response) < 6 or decrypted_response[0] != 0x3B:
        raise ValueError("expected decrypted 0x3B presence write reply")
    raw = bytes(decrypted_response)
    if len(raw) < 6 or raw[0] != 0x3B:
        raise ValueError("expected decrypted 0x3B presence write reply")
    if raw[5] != 1:
        raise ValueError("unexpected presence ACK routine ID")
    return PresenceSetResponse(
        int.from_bytes(raw[1:3], "little"), raw[3], raw[4], raw[5], raw
    )


from .frames import ExtendedCommand, addressed_query


def presence_get(destination: int) -> ExtendedCommand:
    """APK i9.d.c / j9.d.c: 3C + addressLE16 + routine 01, read only."""
    return addressed_query(destination, 0x3C, b"\x01")


def presence_set(destination: int, settings) -> ExtendedCommand:
    """APK i9.p / j9.p: 3B + addressLE16 + 14 presence bytes."""
    if not isinstance(settings, PresenceWritePart):
        raise TypeError("settings must be PresenceWritePart")
    return addressed_query(destination, 0x3B, settings.settings)
