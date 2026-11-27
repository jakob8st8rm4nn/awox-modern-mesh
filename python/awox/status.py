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
from colorsys import hsv_to_rgb
from dataclasses import dataclass, replace
from typing import Callable, Mapping

from .frames import ExtendedCommand, ExtendedNotification, _frame_bytes, addressed_query
from ._numeric import percentage_to_value, value_to_percentage
from ._validation import _validate_received_at, _valid_mesh_destination, is_valid_unicast_mesh_id
from .model_properties import (
    _is_light_model, _is_light_model_name, lookup_dual_zone_properties, lookup_model_properties,
)

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
    product_code: bytes | None
    mode: int | None
    is_on: bool | None
    brightness_raw: int
    hs_raw: tuple[int, int] | None
    white_temperature_mired: int | None
    source_opcode: int
    received_monotonic: float
    raw_response: bytes = b""
    temperature_percent_raw: int | None = None
    zone: int | None = None

    @property
    def brightness_percent(self) -> int:
        """Return the APK-rounded brightness percentage (0..100)."""
        return value_to_percentage(self.brightness_raw, 2, 254)

    @property
    def color_temperature_mired(self) -> int | None:
        """Return the available white temperature in mired."""
        return self.white_temperature_mired

    @property
    def color_temperature_kelvin(self) -> int | None:
        """Return the available white temperature, rounded to integer Kelvin."""
        mired = self.color_temperature_mired
        return round(1_000_000 / mired) if mired is not None and mired > 0 else None

    @property
    def hs(self) -> tuple[float, float] | None:
        """Return color as (hue degrees, saturation percent) when available."""
        if self.hs_raw is None:
            return None
        hue, saturation = self.hs_raw
        if not 0 <= hue <= 254 or not 0 <= saturation <= 255:
            return None
        return (hue * 360.0 / 254) % 360.0, min(254, saturation) * 100.0 / 254

    @property
    def rgb(self) -> tuple[int, int, int] | None:
        """Return RGB color at full HSV value, with brightness reported separately."""
        hs = self.hs
        if hs is None:
            return None
        hue, saturation = hs
        red, green, blue = hsv_to_rgb(hue / 360.0, saturation / 100.0, 1.0)
        return int(red * 255 + 0.5), int(green * 255 + 0.5), int(blue * 255 + 0.5)

    @property
    def provisioning_state_code(self) -> int | None:
        """Raw provisioning byte from the supported APK status layout.

        Retains the firmware value without guessing a named state.
        """
        if len(self.raw_response) < 19:
            return None
        return self.raw_response[19 if len(self.raw_response) == 20 else 18]

    @property
    def is_color_mode(self) -> bool | None:
        """Return the decoded color-mode flag."""
        return None if self.mode is None else bool(self.mode & 0x02)

    @property
    def color_cycle_active(self) -> bool | None:
        """Return the decoded color-cycle flag."""
        return None if self.mode is None else bool(self.mode & 0x04)

    @property
    def candle_active(self) -> bool | None:
        """Return the decoded candle-effect flag."""
        return None if self.mode is None else bool(self.mode & 0x10)


def parse_lamp_status(
    notification: ExtendedNotification, *, received_at: float | None = None
) -> LampStatus | None:
    """Decode the main lamp status in the da.d layout.

    Use StatusStore to resolve alternate layouts against registered devices.
    received_at is a finite monotonic timestamp or None (now).
    """
    payload = notification.payload
    if isinstance(payload, (bytes, bytearray, memoryview)):
        size = payload.nbytes if isinstance(payload, memoryview) else len(payload)
        if size != 19:
            return None
    frame = parse_status_variant(notification)
    if frame is None or (frame.zone_raw != 1 or not _is_supported_da_d_lamp(frame)):
        return None
    status = _lamp_status_from_frame(frame)
    if received_at is not None:
        status = replace(status, received_monotonic=_validate_received_at(received_at))
    return status


def _packet_light_model(product_code: bytes) -> bool | None:
    return _is_light_model(bytes((product_code[1] & ~0x10, product_code[0])))


def _is_supported_da_d_lamp(frame: MeshStatusFrame) -> bool:
    return (
        frame.layout == "da.d"
        and is_valid_unicast_mesh_id(frame.mesh_id)
        and frame.mac_tail_reversed != bytes(4)
        and frame.raw_response[6:8] != bytes(2)
        and _packet_light_model(frame.raw_response[6:8]) is True
    )


def _lamp_status_from_frame(
    frame: MeshStatusFrame, *, zone: int | None = None
) -> LampStatus:
    white_zone = zone == 1
    is_color = not white_zone and bool(frame.mode & 0x02)
    percent = frame.temperature_percent_raw if not is_color else None
    temperature = frame.white_temperature_mired
    if percent is not None and percent <= 100:
        temperature = percentage_to_value(percent, 153, 454)
    return LampStatus(
        mesh_id=frame.mesh_id,
        mac_tail_reversed=frame.mac_tail_reversed,
        product_code=None if frame.mac_embedded_full else frame.raw_response[6:8],
        mode=None if white_zone else frame.mode,
        is_on=bool(frame.mode & 0x01),
        brightness_raw=frame.brightness_raw,
        hs_raw=(frame.hue_raw, frame.saturation_raw) if is_color else None,
        white_temperature_mired=(
            temperature if not is_color and temperature is not None and 153 <= temperature <= 454
            else None
        ),
        source_opcode=frame.source_opcode,
        received_monotonic=frame.received_monotonic,
        raw_response=frame.raw_response,
        temperature_percent_raw=percent,
        zone=zone,
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
        device_models: Mapping[int, str] | None = None,
        on_change: Callable[[LampStatus], None] | None = None,
    ) -> None:
        if on_change is not None and not callable(on_change):
            raise TypeError("on_change must be callable or None")
        self._expected = {}
        for mesh_id, mac in devices.items():
            if not is_valid_unicast_mesh_id(mesh_id):
                raise ValueError("invalid unicast mesh ID")
            self._expected[mesh_id] = _mac_tail_reversed(mac)
        if len(set(self._expected.values())) != len(self._expected):
            raise ValueError("device MAC tails are not unique")
        self._device_macs = {mesh_id: mac.upper() for mesh_id, mac in devices.items()}
        self._device_models = dict(device_models) if device_models is not None else {}
        for mesh_id, model in self._device_models.items():
            if not is_valid_unicast_mesh_id(mesh_id) or mesh_id not in self._expected:
                raise ValueError("device_models requires a registered mesh ID")
            if not isinstance(model, str) or not model:
                raise ValueError("device model must be a nonempty APK model name")
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

    def _matches_identity(self, frame: MeshStatusFrame) -> bool:
        if frame.mac_embedded_full:
            return self._device_macs.get(frame.mesh_id) == frame.mac_address
        # The prefix shown on compact frames is reconstructed, not transmitted.
        return self._expected.get(frame.mesh_id) == frame.mac_tail_reversed

    def _match(self, notification: ExtendedNotification) -> LampStatus | None:
        frame = parse_status_variant(notification)
        if frame is None or not self._matches_identity(frame):
            return None
        return self._lamp_view(frame)

    def _lamp_view(
        self, frame: MeshStatusFrame, *, include_secondary: bool = False
    ) -> LampStatus | None:
        model = self._device_models.get(frame.mesh_id)
        if model is not None and lookup_model_properties(model) is None:
            model = None
        zone = None
        # APK h7.e.p() selects the main block for 1 and the second block otherwise.
        if model is not None:
            candidate = 0 if frame.zone_raw == 1 else 1
            if lookup_dual_zone_properties(model, candidate) is not None:
                zone = candidate
        if frame.zone_raw != 1 and not (include_secondary and zone == 1):
            return None
        if model is not None and not _is_light_model_name(model):
            return None
        if frame.layout == "da.d":
            if not _is_supported_da_d_lamp(frame):
                return None
        elif frame.layout == "da.b":
            if model is None:
                return None
        else:
            packet_model_is_light = _packet_light_model(frame.raw_response[6:8])
            if packet_model_is_light is False or (packet_model_is_light is None and model is None):
                return None
        return _lamp_status_from_frame(frame, zone=zone)

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
        return self._observe_lamp(self._match(notification))

    def _observe_lamp(self, state: LampStatus | None) -> tuple[LampStatus | None, bool]:
        if state is None:
            return None, False
        previous = self._states.get(state.mesh_id)
        unchanged = previous is not None and (
            previous.product_code,
            previous.mode,
            previous.brightness_raw,
            previous.hs_raw,
            previous.white_temperature_mired,
            previous.temperature_percent_raw,
        ) == (
            state.product_code,
            state.mode,
            state.brightness_raw,
            state.hs_raw,
            state.white_temperature_mired,
            state.temperature_percent_raw,
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
    """Decoded mesh status with the original zone_raw byte."""
    mesh_id: int
    zone_raw: int
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
        None if layout == "da.b" else _packet_light_model(p[5:7])
    )
    received_at = _validate_received_at(received_at)
    return MeshStatusFrame(
        mesh_id=int.from_bytes(p[:2], "little"),
        zone_raw=p[2],
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
