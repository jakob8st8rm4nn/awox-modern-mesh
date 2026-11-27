"""AwoX Bluetooth framing and GATT UUIDs. No I/O or device policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from .crypto import aes_att_encryption, aes_att_decryption


def transform_extended_packet(
    packet: bytes | bytearray | memoryview,
    material: bytes,
    att_transform: AttTransform = aes_att_encryption,
) -> bytes:
    """g9.j.H: leave opcode and tail unchanged; transform padded first block."""
    if not isinstance(packet, (bytes, bytearray, memoryview)):
        raise TypeError("packet must be bytes, bytearray or memoryview")
    packet = bytes(packet)
    if not packet:
        raise ValueError("packet needs its leading byte")
    block = packet[1:17].ljust(16, b"\x00")
    result = att_transform(material, block)
    if len(result) != 16:
        raise ValueError("ATT transform must return 16 bytes")
    return packet[:1] + result + packet[17:]


AttTransform = Callable[[bytes, bytes], bytes]
SERVICE_UUID = "00010203-0405-0607-0809-0a0b0c0d1910"
NOTIFY_UUID = "00010203-0405-0607-0809-0a0b0c0d1911"
COMMAND_UUID = "00010203-0405-0607-0809-0a0b0c0d1912"
PAIR_UUID = "00010203-0405-0607-0809-0a0b0c0d1914"


def crc8(data: bytes) -> int:
    """Reflected CRC-8, table-free form using 0x6C (initial state zero)."""
    value = 0
    for byte in data:
        value ^= byte
        for _ in range(8):
            value = (value >> 1) ^ (0x6C if (value & 1) else 0)
    return value


def _encode_frame(flag: int, data: bytes) -> bytes:
    """Frame already validated wire data as flag, CRC, length and content."""
    body = bytes((len(data),)) + data
    return bytes((flag, crc8(body))) + body


def _control_frame(
    destination_wire: bytes, command_wire: bytes, payload: bytes
) -> bytes:
    """Shared control layout; both two-byte fields are in transmission order."""
    flag = 1 if destination_wire[0] == 0x80 else 0
    return _encode_frame(flag, destination_wire + b"\x01" + command_wire + payload)


@dataclass(frozen=True)
class DecodedFrame:
    """Decoded protocol frame fields; no device authenticity is implied."""
    flag: int
    body: bytes
    # Body includes the length byte, followed by opcode/address fields and payload.

    @property
    def length(self) -> int:
        """Length of the decoded frame payload."""
        return self.body[0]

    @property
    def data(self) -> bytes:
        """Decoded payload bytes."""
        return self.body[1:]


def seal_frame(session_key: bytes, flag: int, body: bytes) -> bytes:
    """Encrypt first 16 bytes incl. CRC; append remaining data without encryption.

    body = [length byte] + exactly `length` bytes. Length excludes CRC and itself.
    Output format: flag (plaintext) + AES-ATT(first 16 padded bytes) + tail.
    """
    if type(flag) is not int or flag not in (0, 1, 2):
        raise ValueError("unexpected frame type")
    if len(body) < 1 or len(body) - 1 != body[0]:
        raise ValueError("body length field does not match payload")
    return transform_extended_packet(_encode_frame(flag, body[1:]), session_key)


def open_frame(session_key: bytes, packet: bytes) -> DecodedFrame:
    """Decode and CRC-check a captured command packet; no source authentication."""
    if len(packet) < 17:
        raise ValueError("encrypted command frame shorter than 17 bytes")
    if len(packet) > 258:
        raise ValueError("packet size does not match declared frame length")
    flag = packet[0]
    if flag not in (0, 1, 2):
        raise ValueError("unexpected flag")
    clear = aes_att_decryption(session_key, packet[1:17]) + packet[17:]
    content_len = clear[1]
    # CRC + length + content occupy at least one padded AES block.
    expected_size = 1 + max(16, 2 + content_len)
    if len(packet) != expected_size:
        raise ValueError("packet size does not match declared frame length")
    body = clear[1 : 2 + content_len]
    if clear[0] != crc8(body):
        raise ValueError("CRC8 mismatch")
    return DecodedFrame(flag, body)


def build_query(session_key: bytes, opcode: int, payload: bytes = b"") -> bytes:
    """Example: 0A + FFFF is the observed, broadcast, READ-ONLY status request."""
    if type(opcode) is not int or not 0 <= opcode <= 255:
        raise ValueError("invalid opcode or payload length")
    payload = _frame_bytes(payload, "query payload", max_size=254)
    if len(payload) > 254:
        raise ValueError("invalid opcode or payload length")
    return transform_extended_packet(
        _encode_frame(2, bytes((opcode,)) + payload), session_key
    )


def build_control(
    session_key: bytes, mesh_id: int, opcode: tuple[int, int], payload: bytes = b""
) -> bytes:
    """Build a control command for a known, device-specific mesh id.

    Supply the opcode pair in WIRE order (e.g. power opcode 06 00).
    CAUTION: This API creates writes which may change the light state. There is
    intentionally no BLE transport in this module.
    """
    if type(mesh_id) is not int or not (0 <= mesh_id <= 0xFFFF):
        raise ValueError("invalid mesh id")
    if len(opcode) != 2 or any(type(x) is not int or not 0 <= x <= 255 for x in opcode):
        raise ValueError("opcode must be a pair of bytes")
    payload = _frame_bytes(payload, "control payload", max_size=250)
    if len(payload) > 250:
        raise ValueError("payload is too long")
    frame = _control_frame(
        mesh_id.to_bytes(2, "big"), bytes((opcode[0], opcode[1])), payload
    )
    return transform_extended_packet(frame, session_key)


def _frame_bytes(value, name: str, *, max_size: int | None = None) -> bytes:
    """Bound known outbound fields before copying; snapshot for final checks."""
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError(f"{name} must be bytes, bytearray or memoryview")
    if max_size is not None:
        size = value.nbytes if isinstance(value, memoryview) else len(value)
        if size > max_size:
            raise ValueError(f"{name} exceeds {max_size} bytes")
    return bytes(value)


def query_frame(payload: bytes) -> bytes:
    """g9.c.b: 02 || CRC8(length || payload) || length || payload."""
    payload = _frame_bytes(payload, "query payload", max_size=255)
    if len(payload) > 255:
        raise ValueError("query payload must fit the one-byte length")
    return _encode_frame(2, payload)


def control_frame(
    destination_le: bytes, command_le: bytes, payload: bytes = b""
) -> bytes:
    """g9.c.f with its ORIGINAL two-byte-array argument conventions.

    Address and command pairs are reversed by the original helper. Higher-level
    i9.x intentionally constructs its command pair differently from i9.u/z.
    """
    destination_le = _frame_bytes(destination_le, "destination", max_size=2)
    command_le = _frame_bytes(command_le, "command", max_size=2)
    payload = _frame_bytes(payload, "control payload", max_size=250)
    if len(destination_le) != 2 or len(command_le) != 2:
        raise ValueError("destination and command arrays must each have two bytes")
    if len(payload) > 250:
        raise ValueError("control payload exceeds one-byte length capacity")
    return _control_frame(destination_le[::-1], command_le[::-1], payload)


def encrypt_frame(session_key: bytes, frame: bytes) -> bytes:
    """g9.j.H: keep flag; ATT-encrypt padded bytes1:17; keep tail unchanged."""
    return transform_extended_packet(frame, session_key)


@dataclass(frozen=True)
class ExtendedCommand:
    # Provisioning commands can contain credentials or the network key.
    """Validated plaintext extended frame, ready for session encryption.

    Building this object does not perform Bluetooth I/O.
    """
    plaintext: bytes = field(repr=False)

    def __post_init__(self):
        object.__setattr__(
            self, "plaintext", _frame_bytes(self.plaintext, "plaintext", max_size=258)
        )
        if len(self.plaintext) < 3 or self.plaintext[0] not in (0, 1, 2):
            raise ValueError("expected an extended CRC/length frame")
        if self.plaintext[2] != len(self.plaintext) - 3:
            raise ValueError("extended frame length does not match")
        if self.plaintext[1] != crc8(self.plaintext[2:]):
            raise ValueError("extended frame CRC mismatch")

    def encrypt(self, session_key: bytes) -> bytes:
        """Encrypt the prepared command using the supplied session key."""
        return encrypt_frame(session_key, self.plaintext)


@dataclass(frozen=True)
class ExtendedNotification:
    """Decoded notification opcode, payload and interpreted value.

    The authenticated flag is False unless explicitly established upstream.
    """
    opcode: int
    kind: str
    value: object
    payload: bytes
    authenticated: bool = False


Frame = ExtendedCommand


def addressed_query(
    destination: int, opcode: int, suffix: bytes = b""
) -> ExtendedCommand:
    """Build one query with an explicit little-endian 16-bit destination."""
    address = _destination_bytes(destination)
    if type(opcode) is not int or not 0 <= opcode <= 255:
        raise ValueError("opcode must be an integer byte")
    suffix = _frame_bytes(suffix, "query suffix", max_size=252)
    return ExtendedCommand(
        query_frame(bytes((opcode,)) + address + suffix)
    )


def control(destination: int, command_le: bytes, payload: bytes) -> ExtendedCommand:
    """Build a control frame, preserving the APK's reversed argument convention."""
    return ExtendedCommand(
        control_frame(_destination_bytes(destination), command_le, payload)
    )


def decode_notification(session_key: bytes, packet: bytes) -> ExtendedNotification:
    """Decrypt a receive envelope; payload interpretation belongs to codecs.

    The protocol supplies no authenticated tag. Prefix and tail are plaintext.
    """
    packet = _frame_bytes(packet, "notification")
    if len(packet) < 17:
        raise ValueError("notification needs a prefix and 16-byte ATT block")
    opcode = packet[0]
    payload = aes_att_decryption(session_key, packet[1:17]) + packet[17:]
    kind = "mesh_status_raw" if opcode in (0x80, 0x82) else "raw"
    return ExtendedNotification(opcode, kind, payload, payload)


def _destination_bytes(destination: int) -> bytes:
    if type(destination) is not int or not 0 <= destination <= 0xFFFF:
        raise ValueError("destination must be a 16-bit integer")
    return destination.to_bytes(2, "little")
