"""Small shared checks for mesh addresses and local timing inputs; no I/O."""

import math


def _valid_timeout(value, *, maximum=None) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return (
            math.isfinite(value) and value > 0 and (maximum is None or value <= maximum)
        )
    except OverflowError:
        return False  # Python integers need not fit the float used by timers.


def _validate_received_at(value):
    """Accept None or a finite numeric monotonic timestamp, including zero."""
    if value is None:
        return None
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("received_at must be a finite number or None")
    return value


def is_valid_unicast_mesh_id(value: object) -> bool:
    """Return whether value is an individual mesh device ID."""
    return type(value) is int and 1 <= value <= 0xFFFE and not 0x8000 <= value <= 0x80FF


def _valid_mesh_destination(value) -> bool:
    """Explicit nonzero destination, including groups and broadcast."""
    return type(value) is int and 1 <= value <= 0xFFFF
