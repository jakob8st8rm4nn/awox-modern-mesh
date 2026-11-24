"""Explicit group/broadcast write destinations, without fake lamp registration.

No receive state is attached to a destination; statuses remain individual.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .session import AwoXMeshSession

from .status import LampStatus
from .groups import MeshGroupMembership, MeshGroupSetResponse
from .power_cut import PowerCutConfiguration, PowerCutSetResponse
from .schedule import SchedulePart, ScheduleRead, ScheduleWritePart, ScheduleWriteResult
from .presence import PresenceRead, PresenceWritePart, PresenceSetResponse
from .pir import PirSettings
from ._validation import _valid_mesh_destination
from .lighting import color_payload_native, rgb_to_native
from .lighting import DEFAULT_TRANSITION
from .lighting import _candle_payload, _color_cycle_payload, _scene_payload
from .lighting import (
    brightness_payload_native,
    brightness_native_from_percent,
    mired_from_kelvin,
    temperature_payload_mired,
)


class MeshTarget:
    """Explicit recipient of one-shot light writes, group or broadcast.

    A completed GATT write does not prove that any member acted. No retries,
    polling, automatic unicast fan-out or group-specific callbacks are added.
    """

    def __init__(self, mesh: AwoXMeshSession, destination: int) -> None:
        if not _valid_mesh_destination(destination):
            raise ValueError("destination must be a nonzero 16-bit address")
        self._mesh = mesh
        self._destination = destination

    @property
    def destination(self) -> int:
        """Bound recipient; create another target to use another address."""
        return self._destination

    async def _send(self, command_le: bytes, payload: bytes) -> None:
        """Send one addressed control through the owning mesh session."""
        await self._mesh._write_control_destination(
            self.destination, command_le, payload
        )

    async def set_power(self, enabled: bool) -> None:
        """Send exactly one on/off control; never wait for a device ACK."""
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        await self._send(b"\x00\x06", bytes((enabled,)))

    async def set_brightness_native(
        self, level: int, *, transition: int = DEFAULT_TRANSITION
    ) -> None:
        """Send native brightness 1..255; transition in milliseconds (default 200)."""
        await self._send(
            b"\x00\x08", brightness_payload_native(level, transition=transition)
        )

    async def set_brightness(
        self, percent: int, *, transition: int = DEFAULT_TRANSITION
    ) -> None:
        """Set 0..100%; transition is in milliseconds (default 200).

        Integer percentages use the APK MathUtils numeric rounding rule;
        this does not establish end-to-end Android slider behavior.
        """
        await self.set_brightness_native(
            brightness_native_from_percent(percent), transition=transition
        )

    async def set_color_temperature_mired(
        self, mired: int, *, transition: int = DEFAULT_TRANSITION
    ) -> None:
        """Send 153..454 mired; transition in milliseconds (default 200).

        No model-specific clamp is applied.
        """
        await self._send(
            b"\x03\x00", temperature_payload_mired(mired, transition=transition)
        )

    async def set_color_temperature(
        self, kelvin: int, *, transition: int = DEFAULT_TRANSITION
    ) -> None:
        """Set Kelvin; transition in milliseconds (default 200).

        Kelvin conversion is approximate, not a model-specific limit.
        """
        await self.set_color_temperature_mired(
            mired_from_kelvin(kelvin), transition=transition
        )

    async def set_color_native(
        self, hue: int, saturation: int, *, transition: int = DEFAULT_TRANSITION
    ) -> None:
        """Set native HSV; transition in milliseconds (default 200)."""
        await self._send(
            b"\x03\x00", color_payload_native(hue, saturation, transition=transition)
        )

    async def set_rgb(
        self, red: int, green: int, blue: int, *, transition: int = DEFAULT_TRANSITION
    ) -> None:
        """Set RGB; transition is in milliseconds (default 200).

        Android/Skia-style RGB to hue/saturation; brightness is not sent.
        Black (0,0,0) does NOT turn the lamp off: as in the original APK
        encoder, hue=0/saturation=0 and brightness remains unchanged.
        """
        hue, saturation = rgb_to_native(red, green, blue)
        await self.set_color_native(hue, saturation, transition=transition)

    async def set_candle_mode(self, enabled: bool) -> None:
        """APK set_candle_mode: one effect write, no automatic power-on.

        True starts candle; False sends the candle-off command. A completed
        GATT write is not a device acknowledgement or verified effect state.
        """
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        # control_frame() reverses the two-byte command argument.
        # APK candle opcode on the wire is 08 00, so supply 00 08 here.
        await self._send(b"\x00\x08", _candle_payload(enabled))

    async def set_color_cycle(self, enabled: bool) -> None:
        """APK color_sequence_colors: one start/stop write, no implicit extras.

        True sends 0x41; False sends 0x47. The device effect is not confirmed
        by the normal status-ACK contract. No retries or automatic restore.
        """
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")
        await self._send(b"\x03\x00", _color_cycle_payload(enabled))

    async def save_scene(self, index: int) -> None:
        """Save current state to native scene index 0..255 (APK selector 04).

        GATT success is not a device ACK or persistence proof.
        """
        if type(index) is not int or not 0 <= index <= 255:
            raise ValueError("index must be a byte")
        await self._send(b"\x00\x05", _scene_payload(index, True))

    async def recall_scene(self, index: int) -> None:
        """Recall native scene index 0..255 (APK selector 05), one write."""
        if type(index) is not int or not 0 <= index <= 255:
            raise ValueError("index must be a byte")
        await self._send(b"\x00\x05", _scene_payload(index, False))


class Lamp(MeshTarget):
    """Registered individual target; no independent connection or state copy."""

    @property
    def mesh_id(self) -> int:
        """Registered mesh ID of this individual lamp."""
        return self.destination

    @property
    def status(self) -> LampStatus | None:
        """Last accepted cached status; does not send a Bluetooth query."""
        return self._mesh.get_status(self.destination)

    async def request_status(self) -> None:
        """Send one status query and observe any response separately."""
        await self._mesh.request_status(self.destination)

    async def read_status(self, *, timeout: float = 15.0) -> LampStatus | None:
        """Query this lamp once and wait for a fresh status notification."""
        return await self._mesh.read_status(self.destination, timeout=timeout)

    async def read_mesh_groups(self, *, timeout: float = 15.0) -> MeshGroupMembership | None:
        """Read the entire stored group list with a single addressed 0x08 query.

        None means no valid reply, NOT an empty membership list. The returned
        object's group_addresses is a tuple of group IDs; raw_response is
        retained. Address matching is not cryptographic device attribution.
        """
        return await self._mesh.read_mesh_groups(self.destination, timeout=timeout)

    async def write_mesh_groups(self, groups: list[int] | tuple[int, ...]) -> None:
        """Replace the full group list without waiting for a device reply."""
        await self._mesh.write_mesh_groups(self.destination, groups)

    async def set_mesh_groups(self, groups: list[int] | tuple[int, ...], *, timeout: float = 5.0) -> MeshGroupSetResponse | None:
        """REPLACE ALL memberships with a single 0x0C command.

        A result with success=True is a device ACK, NOT verified persistence;
        use read_mesh_groups() separately to check stored data. None means no
        answer, not success. No retry or automatic rollback.
        """
        return await self._mesh.set_mesh_groups(self.destination, groups, timeout=timeout)

    async def read_power_cut_mode(self, *, timeout: float = 15.0) -> PowerCutConfiguration | None:
        """Read the stored power-cut mode, without changing the setting.

        Returns None when no 0x43 response arrives. The response address is
        checked, but is not an authenticated identity or causal ACK.
        """
        return await self._mesh.read_power_cut_mode(self.destination, timeout=timeout)

    async def write_power_cut_mode(self, mode: str, scene: bytes | None = None) -> None:
        """Send one power-cut-mode write without waiting for the 0x42 reply."""
        await self._mesh.write_power_cut_mode(self.destination, mode, scene)

    async def set_power_cut_mode(self, mode: str, scene: bytes | None = None, *, timeout: float = 5.0) -> PowerCutSetResponse | None:
        """Save a power-cut setting with one 0x42 command and await its ACK.

        mode: 'on', 'previous' or 'scene'; for a scene supply four bytes from
        power_cut_white_scene()/power_cut_color_scene(). No automatic readback.
        None means no 0x42 response before the local timeout. A received
        device TIMEOUT code (0x94) is returned as status='timeout'.
        The APK's ordinary 'on' write uses scene bytes 00000000; this is not
        a byte-preserving restore of an existing inactive scene (e.g. FFFFFFFF).
        """
        return await self._mesh.set_power_cut_mode(
            self.destination, mode, scene, timeout=timeout
        )

    async def read_schedule_part(self, routine_id: int, *, timeout: float = 15.0) -> SchedulePart | None:
        """Read one selected schedule routine without reading its companion routine."""
        return await self._mesh.read_schedule_part(
            self.destination, routine_id, timeout=timeout
        )

    async def set_schedule_part(self, part: ScheduleWritePart) -> None:
        """Write a single schedule part, without waiting or continuing a pair."""
        await self._mesh.set_schedule_part(self.destination, part)

    async def read_timer(self, *, timeout: float = 15.0) -> ScheduleRead | None:
        """Read-only APK countdown timer (0x35, routine 2), once.

        Returns a single-part ScheduleRead, or None if no matching
        notification arrives. No schedule writes, retries or clock sync.
        """
        return await self._mesh._read_schedule(self.destination, "timer", timeout=timeout)

    async def read_program(self, *, timeout: float = 15.0) -> ScheduleRead | None:
        """Read-only APK time program (0x35, routine 3), once.

        Returns one ScheduleRead, or None if no matched reply. A valid
        reply does not prove that every stored program slot was read.
        This does not create, activate, edit or synchronise a program.
        """
        return await self._mesh._read_schedule(self.destination, "program", timeout=timeout)

    async def read_nightlight(self, *, timeout: float = 15.0) -> ScheduleRead | None:
        """Read-only APK 0x35 routines 5 and (if valid first reply) 6."""
        return await self._mesh._read_schedule(self.destination, "nightlight", timeout=timeout)

    async def read_dawn_simulator(self, *, timeout: float = 15.0) -> ScheduleRead | None:
        """Read-only APK 0x35 routines 7 and (if valid first reply) 8."""
        return await self._mesh._read_schedule(self.destination, "dawn_simulator", timeout=timeout)

    async def set_timer(self, settings: ScheduleWritePart, *, timeout: float = 15.0) -> ScheduleWriteResult:
        """Write exactly one APK 0x33 timer routine 2; possible persistent change.

        settings is a ScheduleWritePart (typically from a valid read).
        No automatic timer activation, backup, readback, retry or rollback.
        A positive 0x00 ACK does not prove persistence; check read_timer().
        """
        return await self._mesh._set_schedule(self.destination, "timer", settings, timeout=timeout)

    async def set_program(self, settings: ScheduleWritePart, *, timeout: float = 15.0) -> ScheduleWriteResult:
        """Write exactly one APK 0x33 program routine 3, no hidden automation.

        settings must be a ScheduleWritePart (for example from a
        valid read_program result). A positive 0x00 ACK is not proof of
        persistence or execution. No retry, backup, readback, time sync,
        or automatic rollback is performed by the library.
        """
        return await self._mesh._set_schedule(self.destination, "program", settings, timeout=timeout)

    async def set_nightlight(self, start: ScheduleWritePart, end: ScheduleWritePart, *, timeout: float = 15.0) -> ScheduleWriteResult:
        """Write APK routines 5/6; ONLY continue on the device's 0x99 reply.

        This is a persistent device change. No automatic backup/readback,
        time sync, retry, rollback, or claim of final execution.
        """
        return await self._mesh._set_schedule(
            self.destination, "nightlight", start, end, timeout=timeout
        )

    async def set_dawn_simulator(self, start: ScheduleWritePart, end: ScheduleWritePart, *, timeout: float = 15.0) -> ScheduleWriteResult:
        """Write APK routines 7/8; MAY change persistent lamp automation."""
        return await self._mesh._set_schedule(
            self.destination, "dawn_simulator", start, end, timeout=timeout
        )

    async def read_presence_simulator(self, *, timeout: float = 15.0) -> PresenceRead | None:
        """Read-only APK 0x3C presence simulator, routine 1, once.

        Returns PresenceRead, or None when no matching reply arrives.
        No activation, scheduling, retries or clock synchronization.
        """
        return await self._mesh.read_presence_simulator(self.destination, timeout=timeout)

    async def write_presence_simulator(self, settings: PresenceWritePart) -> None:
        """Send one 0x3B presence setting without waiting for an ACK."""
        await self._mesh.write_presence_simulator(self.destination, settings)

    async def set_presence_simulator(self, settings: PresenceWritePart, *, timeout: float = 15.0) -> PresenceSetResponse | None:
        """One original 0x3B configuration write; no automatic recovery.

        settings is PresenceWritePart, usually derived from an explicit
        read. A positive 0x00 ACK is not proof of stored values/execution.
        This call does not toggle, retry, read back or restore automatically.
        """
        return await self._mesh.set_presence_simulator(
            self.destination, settings, timeout=timeout
        )

    async def read_pir_settings(self, *, timeout: float = 15.0) -> PirSettings | None:
        """Read PIR settings for this lamp; the protocol reply has no device address."""
        return await self._mesh.read_pir_settings(self.destination, timeout=timeout)

    async def read_pir_luminosity(self, *, timeout: float = 15.0) -> int | None:
        """Read the raw PIR luminosity value (0..255), not lux."""
        return await self._mesh.read_pir_luminosity(self.destination, timeout=timeout)

    async def set_dual_zone_power(self, zone: int, enabled: bool) -> None:
        """Set on/off for one zone on this lamp. Raw state 2 remains low-level."""
        await self._mesh.set_dual_zone_power(self.destination, zone, enabled)

    async def set_dual_zone_brightness(self, zone: int, percent: int) -> None:
        """Set brightness percentage for a selected lamp zone."""
        await self._mesh.set_dual_zone_brightness(self.destination, zone, percent)

    async def set_dual_zone_brightness_native(self, zone: int, level: int) -> None:
        """Set a native brightness value for a selected lamp zone."""
        await self._mesh.set_dual_zone_brightness_native(self.destination, zone, level)

    async def set_dual_zone_rgb(self, zone: int, red: int, green: int, blue: int) -> None:
        """Set RGB color for a selected lamp zone."""
        await self._mesh.set_dual_zone_rgb(self.destination, zone, red, green, blue)

    async def set_dual_zone_color_native(self, zone: int, hue: int, saturation: int) -> None:
        """Set native hue and saturation for a selected lamp zone."""
        await self._mesh.set_dual_zone_color_native(self.destination, zone, hue, saturation)

    async def set_dual_zone_color_temperature(self, zone: int, kelvin: int) -> None:
        """Set Kelvin color temperature for a selected lamp zone."""
        await self._mesh.set_dual_zone_color_temperature(self.destination, zone, kelvin)

    async def set_dual_zone_color_temperature_mired(self, zone: int, mired: int) -> None:
        """Set mired color temperature for a selected lamp zone."""
        await self._mesh.set_dual_zone_color_temperature_mired(self.destination, zone, mired)
