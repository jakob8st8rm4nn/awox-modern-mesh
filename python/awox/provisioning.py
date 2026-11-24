"""Explicit provisioning codecs. The caller owns the entire setup sequence."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import re
from .frames import ExtendedCommand, addressed_query, query_frame
from .authentication import Credentials, _padded_credential, network_update_packets
from .model_codes import lookup_models_by_code


def _uint(value: int, maximum: int, name: str) -> int:
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError(f"{name} must be an integer in 0..{maximum}")
    return value


def factory_credentials(
    mac: str, model_code: bytes, firmware: str, *, name: str = "unpaired"
) -> Credentials:
    """APK h9.a.b/c and g9.g: explicit factory/default credential selection.

    Supply the scanner's model_lookup_code and actual advertised firmware.
    The name defaults to 'unpaired'; pass the observed current name for
    models that advertise a different factory login name. The caller selects
    the device and supplies the metadata.
    """
    if not isinstance(mac, str) or not re.fullmatch(
        r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", mac
    ):
        raise ValueError("mac must contain six colon-separated hex bytes")
    if (
        not isinstance(model_code, bytes)
        or len(model_code) != 2
        or not lookup_models_by_code(model_code)
    ):
        raise ValueError("model_code must be a registered Modern Mesh lookup code")
    if not isinstance(firmware, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+", firmware, re.ASCII
    ):
        raise ValueError("firmware must be an advertised major.minor.patch version")
    version = tuple(int(part) for part in firmware.split("."))
    if any(part > 255 for part in version):
        raise ValueError("advertised firmware components must fit bytes")
    threshold = {
        0x20: (3, 0, 0),
        0x60: (2, 0, 0),
        0x61: (2, 0, 0),
        0x63: (2, 0, 0),
        0x80: (1, 0, 0),
        0x81: (1, 0, 0),
    }.get(model_code[0])
    password = b"1234"
    if threshold is not None and version >= threshold:
        # Public constant from APK g9.g.<clinit>, not an account/network key.
        material = (
            bytes.fromhex(mac.replace(":", ""))
            + bytes.fromhex("56e850edcfdd8b99")
            + bytes(2)
        )
        password = hashlib.sha256(material).digest()[:16]
    return Credentials(name, password)


def build_provision_network(
    channel: int,
    network_id: bytes,
    extended_network_id: bytes,
    *,
    group_address: int = 0,
    reserved: int = 0,
) -> ExtendedCommand:
    """APK i9.j: 03 + 1/2/8/2/2 bytes + final allocation-zero, no target ID."""
    _uint(channel, 255, "channel")
    _uint(group_address, 65535, "group_address")
    _uint(reserved, 65535, "reserved")
    if not isinstance(network_id, bytes) or len(network_id) != 2:
        raise ValueError("network_id must be two bytes")
    if not isinstance(extended_network_id, bytes) or len(extended_network_id) != 8:
        raise ValueError("extended_network_id must be eight bytes")
    return ExtendedCommand(
        query_frame(
            b"\x03"
            + bytes((channel,))
            + network_id
            + extended_network_id
            + group_address.to_bytes(2, "little")
            + reserved.to_bytes(2, "little")
            + b"\0"
        )
    )


def build_network_key(network_key: bytes) -> ExtendedCommand:
    """APK i9.o: 04 + exactly 16 key bytes + allocation-zero, no target ID."""
    if not isinstance(network_key, bytes) or len(network_key) != 16:
        raise ValueError("network_key must be exactly 16 bytes")
    return ExtendedCommand(query_frame(b"\x04" + network_key + b"\0"))


@dataclass(frozen=True)
class ProvisioningSettings:
    """Persistent mesh data supplied by the caller, never generated implicitly.

    channel=20 and the padded-name ID mapping follow g9.j.c. group_address
    is the explicit APK S field; supply the appropriate value for the device.
    The common lamp/three-button-remote setup uses zero. Not a capability test.
    """

    credentials: Credentials = field(repr=False)
    network_key: bytes = field(repr=False)
    channel: int = 20
    group_address: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.credentials, Credentials):
            raise TypeError("credentials must be Credentials")
        build_network_key(self.network_key)
        self.network_frame()

    def network_frame(self) -> ExtendedCommand:
        """Build the network parameter frame from these explicit settings."""
        name = _padded_credential(self.credentials.name)
        return build_provision_network(
            self.channel,
            name[:2],
            name[:6][::-1] + b"\xc1\xa4",
            group_address=self.group_address,
        )


@dataclass(frozen=True)
class ProvisioningResult:
    """Observed 0x83 and optional 0x0B, not proof of working radio/button paths."""

    completed: bool
    mesh_id: int | None


def remove_from_mesh(destination: int) -> ExtendedCommand:
    """APK i9.g.c: explicit kick-out query, not a proven full factory reset."""
    if not _valid_unicast_mesh_id(destination):
        raise ValueError("device address must be a confirmed individual device ID")
    return addressed_query(destination, 0x01)


from ._validation import _valid_unicast_mesh_id
