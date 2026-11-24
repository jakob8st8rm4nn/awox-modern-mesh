"""Conservative modern-mesh light status parser and per-device RAM store.

Hardware captures confirm the EGLO-ZM-RGB-TW 20-byte layout. This lighting
view additionally requires an APK-registered lamp model; RCU, PIR and unknown
models remain available through the raw status decoder, not as LampStatus.
A successful AES decode is NOT cryptographic authentication.
No BLE, files, credentials or hardware access occurs in this module.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable, Mapping

from .frames import ExtendedCommand, ExtendedNotification, _frame_bytes, addressed_query
from ._validation import _validate_received_at, _valid_mesh_destination, _valid_unicast_mesh_id
from .model_properties import _is_light_model

_MAC = re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\Z")


def status_query(destination: int) -> ExtendedCommand:
    """Build one 0x0A status query for a device, group or broadcast."""
    if not _valid_mesh_destination(destination):
        raise ValueError("destination must be a nonzero 16-bit address")
    return addressed_query(destination, 0x0A)


@dataclass(frozen=True)
class LampStatus:
    """Decoded, timestamped registered-lamp status from a supported reply.

    This is an observation, not confirmation of a preceding light command.
    """
    mesh_id: int
    mac_tail_reversed: bytes
    product_code: bytes
    mode: int
    is_on: bool | None
    brightness_raw: int
    hue_raw: int | None
    saturation_raw: int | None
    white_temperature_mired: int | None
    source_opcode: int
    received_monotonic: float
    raw_response: bytes = b""

    @property
    def endpoint_id(self) -> int | None:
        """Endpoint byte in the supported 20-byte APK status layout."""
        return self.raw_response[3] if len(self.raw_response) == 20 else None

    @property
    def provisioning_state_code(self) -> int | None:
        """Raw provisioning byte from the supported APK status layout.

        Retains the firmware value without guessing a named state.
        """
        return self.raw_response[19] if len(self.raw_response) == 20 else None

    @property
    def is_color_mode(self) -> bool:
        """Return the decoded color-mode flag."""
        return bool(self.mode & 0x02)

    @property
    def color_cycle_active(self) -> bool:
        """Return the decoded color-cycle flag."""
        return bool(self.mode & 0x04)

    @property
    def candle_active(self) -> bool:
        """Return the decoded candle-effect flag."""
        return bool(self.mode & 0x10)


def parse_lamp_status(
    notification: ExtendedNotification, *, received_at: float | None = None
) -> LampStatus | None:
    """Parse the *observed* 0x80/0x82 EGLO_ZM_RGB_TW status layout.

    Returns None for other kinds (including 0x0B address replies), malformed
    layouts, non-lamp/unknown models and unsupported variants. Registered
    properties select lamps; this is not hardware validation of every model.
    The evidence does not authenticate frames.
    received_at must be a finite numeric monotonic timestamp or None (now).
    """
    if (
        notification.opcode not in (0x80, 0x82)
        or notification.kind != "mesh_status_raw"
    ):
        return None
    try:
        payload = notification.payload
        if isinstance(payload, (bytes, bytearray, memoryview)):
            size = payload.nbytes if isinstance(payload, memoryview) else len(payload)
            if size != 19:
                return None
        p = _frame_bytes(payload, "status payload")
    except (TypeError, ValueError):
        return None
    # Recorded notification: 1 plaintext opcode + 19 decrypted/tail bytes.
    if len(p) != 19 or p[2:5] != b"\x01\x00\x00" or p[11] != 0x01:
        return None
    mesh_id = int.from_bytes(p[:2], "little")
    if (
        (mesh_id in (0, 0xFFFF) or 0x8000 <= mesh_id <= 0x80FF)
        or p[5:7] == b"\x00\x00"
        or p[7:11] == bytes(4)
    ):
        return None
    # This convenience API is a lighting view, not the raw APK status
    # dispatcher. Model bytes are reversed relative to the descriptor register.
    code = bytes((p[6] & ~0x10, p[5]))
    if _is_light_model(code) is not True:
        return None
    # The APK decodes the state as a bit field, not an enum:
    # bit 0 = power, bit 1 = colour, bit 2 = colour cycle, bit 4 = candle.
    # Keep the entire raw mode byte, including unknown bits. Unknown flags
    # alone do not invalidate a status; only the known bits are interpreted.
    mode = p[12]
    is_on = bool(mode & 0x01)
    is_color = bool(mode & 0x02)

    # White temperature and HSV are selected by the colour bit, independent
    # of power. Unusual white-temperature values are not interpreted as valid
    # UI temperatures, but must not discard the rest of a status observation.
    # The exact received bytes are still available in raw_response[15:17].
    temp_raw = int.from_bytes(p[14:16], "little")
    white_temp = temp_raw if not is_color and 153 <= temp_raw <= 454 else None

    received_at = _validate_received_at(received_at)
    return LampStatus(
        mesh_id=mesh_id,
        mac_tail_reversed=p[7:11],
        product_code=p[5:7],
        mode=mode,
        is_on=is_on,
        brightness_raw=p[13],
        hue_raw=p[16] if is_color else None,
        saturation_raw=p[17] if is_color else None,
        white_temperature_mired=white_temp,
        source_opcode=notification.opcode,
        received_monotonic=time.monotonic() if received_at is None else received_at,
        raw_response=bytes((notification.opcode,)) + p,
    )


def _mac_tail_reversed(mac: str) -> bytes:
    if not isinstance(mac, str) or _MAC.fullmatch(mac) is None:
        raise ValueError("expected a six-byte Bluetooth MAC")
    return bytes.fromhex(mac.replace(":", ""))[2:][::-1]


class StatusStore:
    """Read-only observations, never optimistic command acknowledgements.

    Pass the *known* mesh-id/MAC mapping for conservative device routing.
    Unknown devices and mismatched MAC tails are rejected. Repeated states
    refresh the observation without emitting another change callback.
    clear() invalidates old observations after a disconnect/reconnect.
    """

    def __init__(
        self,
        devices: Mapping[int, str],
        *,
        on_change: Callable[[LampStatus], None] | None = None,
    ) -> None:
        if on_change is not None and not callable(on_change):
            raise TypeError("on_change must be callable or None")
        self._expected = {}
        for mesh_id, mac in devices.items():
            if not _valid_unicast_mesh_id(mesh_id):
                raise ValueError("invalid unicast mesh ID")
            self._expected[mesh_id] = _mac_tail_reversed(mac)
        if len(set(self._expected.values())) != len(self._expected):
            raise ValueError("device MAC tails are not unique")
        self._states: dict[int, LampStatus] = {}
        self.on_change = on_change

    @property
    def states(self) -> dict[int, LampStatus]:
        """Return the stored status mapping."""
        return dict(self._states)

    def get(self, mesh_id: int) -> LampStatus | None:
        """Return an existing stored lamp status; do not query the device."""
        if type(mesh_id) is not int:
            raise TypeError("mesh_id must be an integer")
        return self._states.get(mesh_id)

    def clear(self) -> None:
        """Discard all stored statuses."""
        self._states.clear()

    def _match(self, notification: ExtendedNotification) -> LampStatus | None:
        state = parse_lamp_status(notification)
        if state is not None and self._expected.get(state.mesh_id) == state.mac_tail_reversed:
            return state
        return None

    def observe(
        self, notification: ExtendedNotification
    ) -> tuple[LampStatus | None, bool]:
        """Classify an incoming frame as rejected, unchanged, or changed.

        (None, False) means unsupported, malformed, or wrong-device status.
        (status, False) is a *valid new observation* of unchanged lamp state.
        (status, True) is a new observation with changed lamp state.
        Even unchanged observations refresh received_monotonic. Only changed
        states invoke on_change. No authentication or query ACK is implied.
        """
        state = self._match(notification)
        if state is None:
            return None, False
        previous = self._states.get(state.mesh_id)
        unchanged = previous is not None and (
            previous.product_code,
            previous.mode,
            previous.brightness_raw,
            previous.hue_raw,
            previous.saturation_raw,
            previous.white_temperature_mired,
        ) == (
            state.product_code,
            state.mode,
            state.brightness_raw,
            state.hue_raw,
            state.saturation_raw,
            state.white_temperature_mired,
        )
        # Store the new timestamp (and source opcode) for BOTH changes and
        # repeats. Repeated status reports are not decoder errors.
        self._states[state.mesh_id] = state
        if not unchanged and self.on_change is not None:
            self.on_change(state)
        return state, not unchanged

    def update(self, notification: ExtendedNotification) -> LampStatus | None:
        """Backward-compatible state-change API: None for unchanged/invalid.

        Call observe() when valid unchanged reports need to be distinguished
        from rejected packets, e.g. for transport diagnostics.
        """
        status, changed = self.observe(notification)
        return status if changed else None


@dataclass(frozen=True)
class MeshStatusFrame:
    """Decoded raw mesh endpoint status, separate from the LampStatus view."""
    mesh_id: int
    endpoint: int
    layout: str
    mac_address: str
    mac_embedded_full: bool
    mode: int
    is_on: bool | None
    brightness_raw: int
    hue_raw: int
    saturation_raw: int
    white_temperature_mired: int | None
    temperature_percent_raw: int | None
    provisioning_state_code: int
    format_word_raw: bytes
    field11_raw: int
    source_opcode: int
    raw_response: bytes
    received_monotonic: float

    @property
    def mac_tail_reversed(self) -> bytes:
        """Return the MAC tail in the byte order used for status matching."""
        return bytes.fromhex(self.mac_address.replace(":", ""))[2:][::-1]


def parse_status_variant(
    notification: ExtendedNotification, *, received_at: float | None = None
) -> MeshStatusFrame | None:
    """Decode the three APK status formats without assigning a physical zone.

    da.b: total 20 bytes, nonzero format word, complete six-byte reversed MAC.
    da.d: total 20 bytes, zero format word, reversed four-byte MAC suffix.
    da.c: other total lengths >=19 bytes (>=18 payload bytes plus opcode),
          compact temperature percentage; extra bytes remain in raw_response.
          All lengths above include the opcode. No arbitrary length cap.

    received_at must be a finite numeric monotonic timestamp or None (now).
    This is structural parsing only. Device matching remains a separate step.
    """
    if (
        notification.opcode not in (0x80, 0x82)
        or notification.kind != "mesh_status_raw"
    ):
        return None
    try:
        p = _frame_bytes(notification.payload, "status payload")
    except (TypeError, ValueError):
        return None
    if len(p) < 18:
        return None
    if len(p) == 19:
        layout = "da.b" if p[3:5] != b"\x00\x00" else "da.d"
    else:
        layout = "da.c"
    if layout == "da.b":
        mac = p[5:11][::-1]
    else:
        mac = b"\xa4\xc1" + p[7:11][::-1]
    full = ":".join(f"{part:02X}" for part in mac)
    if layout == "da.c":
        temperature_mired = None
        temperature_percent = p[14]
        hue, saturation, provision = p[15:18]
    else:
        temperature_mired = int.from_bytes(p[14:16], "little")
        temperature_percent = None
        hue, saturation, provision = p[16:19]
    light_model = (
        None if layout == "da.b" else _is_light_model(bytes((p[6] & ~0x10, p[5])))
    )
    received_at = _validate_received_at(received_at)
    return MeshStatusFrame(
        mesh_id=int.from_bytes(p[:2], "little"),
        endpoint=p[2],
        layout=layout,
        mac_address=full,
        mac_embedded_full=(layout == "da.b"),
        mode=p[12],
        is_on=None if light_model is False else bool(p[12] & 1),
        brightness_raw=p[13],
        hue_raw=hue,
        saturation_raw=saturation,
        white_temperature_mired=temperature_mired,
        temperature_percent_raw=temperature_percent,
        provisioning_state_code=provision,
        format_word_raw=p[3:5],
        field11_raw=p[11],
        source_opcode=notification.opcode,
        raw_response=bytes((notification.opcode,)) + p,
        received_monotonic=time.monotonic() if received_at is None else received_at,
    )
