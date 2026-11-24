"""Credentials and APK login primitives; no retries or provisioning."""

from __future__ import annotations

from dataclasses import dataclass, field
from .crypto import aes_att_encryption


@dataclass(frozen=True)
class Credentials:
    """User-supplied mesh credentials; excluded from the default repr."""

    name: str | bytes = field(repr=False)
    password: str | bytes = field(repr=False)

    def __post_init__(self) -> None:
        for label, value in (("name", self.name), ("password", self.password)):
            if not isinstance(value, (str, bytes)):
                raise ValueError(f"mesh {label} must be str or bytes")
            encoded = value.encode("utf-8") if isinstance(value, str) else value
            if len(encoded) > 16:
                raise ValueError(f"mesh {label} must fit 16 bytes (UTF-8 for strings)")


def _padded_credential(value: str | bytes) -> bytes:
    if not isinstance(value, (str, bytes)):
        raise TypeError("mesh credential must be str or bytes")
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    if len(encoded) > 16:
        raise ValueError("mesh credential must contain at most 16 UTF-8 bytes")
    return encoded.ljust(16, b"\0")


def _secret(name: str | bytes, password: str | bytes) -> bytes:
    return bytes(
        a ^ b for a, b in zip(_padded_credential(name), _padded_credential(password))
    )


def login_request(
    name: str | bytes, password: str | bytes, client_random: bytes
) -> bytes:
    """17-byte ATT login request (0C | random8 | encrypted proof8)."""
    if len(client_random) != 8:
        raise ValueError("client_random must be 8 bytes")
    proof = aes_att_encryption(client_random + bytes(8), _secret(name, password))
    return b"\x0c" + client_random + proof[:8]


def derive_session_key(
    name: str | bytes, password: str | bytes, client_random: bytes, response: bytes
) -> bytes:
    """Derive 16-byte session key after a success response, no tag authentication.

    In particular, 0x0D is interpreted as success and 0x0E as rejection.
    """
    if len(client_random) != 8:
        raise ValueError("client_random must be 8 bytes")
    if not response:
        raise ValueError("empty login response")
    if response[0] == 0x0E:
        raise ValueError("device rejected mesh credentials (0x0E)")
    if response[0] != 0x0D or len(response) < 9:
        raise ValueError("unexpected login response")
    return aes_att_encryption(_secret(name, password), client_random + response[1:9])


def network_update_packets(
    session_key: bytes, name: bytes, password: bytes
) -> tuple[bytes, bytes]:
    """g9.j.T: two Pair1914 packets (04/05), unlike legacy's three packets."""
    if any(len(value) != 16 for value in (session_key, name, password)):
        raise ValueError(
            "session and caller-provided credential blocks must be 16 bytes"
        )
    return (
        b"\x04" + aes_att_encryption(session_key, name),
        b"\x05" + aes_att_encryption(session_key, password),
    )
