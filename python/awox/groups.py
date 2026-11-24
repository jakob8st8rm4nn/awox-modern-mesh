"""APK group membership list codecs. No command sequencing."""

from __future__ import annotations
from dataclasses import dataclass

from .frames import ExtendedCommand, addressed_query


def get_mesh_groups(destination: int) -> ExtendedCommand:
    """APK i9.c.c / j9.c.c: read one device's group membership.

    Query data: 08 || device ID LE16 || 00 00 00. This only builds
    bytes; it does not create a UI group or send any Bluetooth command.
    """
    return addressed_query(destination, 0x08, bytes(3))


def set_mesh_groups(destination: int, group_addresses) -> ExtendedCommand:
    """APK i9.n.c / j9.n.c: replace a device's group-address list.

    Query data: 0C || device ID LE16 || count8 || group IDs BE16.
    Preserve caller order. This is the APK's *list* form, not its odd
    Boolean form (which ignores the Boolean value); no BLE I/O here.

    Python bounds the 1-byte query-frame length and refuses truncation;
    the APK's list encoder does not explicitly enforce that limit.
    """
    if not isinstance(group_addresses, (tuple, list)):
        raise TypeError("group addresses must be a list or tuple of integers")
    if type(group_addresses) in (tuple, list) and len(group_addresses) > 125:
        raise ValueError("group list exceeds the one-byte APK frame limit")
    addresses = bytearray()
    for index, addr in enumerate(group_addresses):
        if index == 125:
            raise ValueError("group list exceeds the one-byte APK frame limit")
        if type(addr) is not int or not 0 <= addr <= 65535:
            raise ValueError("each group address must be a 16-bit integer")
        addresses.extend(addr.to_bytes(2, "big"))
    suffix = bytes((len(addresses) // 2,)) + addresses
    return addressed_query(destination, 0x0C, suffix)


@dataclass(frozen=True)
class MeshGroupMembership:
    """One decoded 0x08 reply; not proof that the list matches a prior write.

    Device address is from reply bytes 1..2 (not cryptographic provenance).
    The unmodified decrypted response is preserved for further analysis.
    """

    mesh_id: int
    group_addresses: tuple[int, ...]
    raw_response: bytes


def parse_mesh_groups_get(decrypted_response: bytes) -> MeshGroupMembership:
    """APK DeviceSettingsActivity.onRead: count at byte 4, IDs LE16 at 5+.

    Do not confuse this 0x08 *response* layout with the 0x0C *request*
    layout, where group IDs are BE16. Ignore trailing uninterpreted bytes.
    """
    if not isinstance(decrypted_response, (bytes, bytearray)):
        raise TypeError("mesh-group reply must be bytes")
    response = bytes(decrypted_response)
    if len(response) < 5 or response[0] != 0x08:
        raise ValueError("expected full decrypted 0x08 reply")
    count = response[4]
    end = 5 + 2 * count
    if len(response) < end:
        raise ValueError("mesh-group reply truncated before listed groups")
    groups = tuple(
        int.from_bytes(response[i : i + 2], "little") for i in range(5, end, 2)
    )
    return MeshGroupMembership(
        int.from_bytes(response[1:3], "little"), groups, response
    )


@dataclass(frozen=True)
class MeshGroupSetResponse:
    """One 0x0C membership-write reply, not a verified saved group list.

    The reply contains a target address and a result byte. It does not
    include the resulting membership list or a request correlation token.
    """

    mesh_id: int
    status_code: int
    raw_response: bytes

    @property
    def success(self) -> bool:
        """True only for status code zero in the decoded 0x0C response."""
        return self.status_code == 0


def parse_mesh_groups_set_result(decrypted_response: bytes) -> MeshGroupSetResponse:
    """APK g9.j.e / h9.i.e: address LE16 and raw result at byte 3.

    This is a full decrypted 0x0C reply, not an outgoing 0x0C request.
    Only code 0 is a documented successful result; do not invent meanings
    for nonzero status values or claim that all group addresses are stored.
    """
    if not isinstance(decrypted_response, (bytes, bytearray)):
        raise TypeError("mesh-group write reply must be bytes")
    response = bytes(decrypted_response)
    if len(response) < 4 or response[0] != 0x0C:
        raise ValueError("expected full decrypted 0x0C reply with at least 4 bytes")
    return MeshGroupSetResponse(
        int.from_bytes(response[1:3], "little"), response[3], response
    )
