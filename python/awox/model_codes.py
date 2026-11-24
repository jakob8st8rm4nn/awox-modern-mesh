"""Exact 2-byte model codes from Android model Descriptor.i() in APK 1.14.10/1.14.11.

App MainApplication registers names->descriptor; a descriptor constructor
registers ByteUtils.bytesToInt(i()[0], i()[1]) in the numeric w9.a.t map.
The scanner separately clears bit 4 in the FIRST byte before numeric lookup.

The name and numeric maps are not a one-to-one relationship. This file is
pure reference data: it performs no scan and declares no device capabilities.
"""

from __future__ import annotations

from collections import defaultdict
from types import MappingProxyType
from .model_registry import AwoXModel, lookup_model

# Exact bytes returned by each registered descriptor's i() override.
# Maintained from two separately inspected original APKs (see evidence CSVs).
_NAME_TO_CODE = MappingProxyType(
    {
        "E2G-ZMB-RGB-TW": b"\x63\x96",
        "EBF-RGB-ZMB": b"\x60\xb0",
        "EBF-RGB-ZMB-CLB": b"\x60\xb1",
        "EBF-RGB-Zm": b"\x20\xb0",
        "EBF-RGB-Zm-CLP": b"\x20\xb2",
        "EDUAL-RGB2TW-2BT": b"\x63\x01",
        "EDUAL-RGBTW-TW": b"\x63\x00",
        "EDUAL2G-RGBTW-TW": b"\x63\x02",
        "EGLO-MAT-Dimmable": b"\x80\x98",
        "EGLO-MAT-RGB-TW": b"\x80\x96",
        "EGLO-MAT-TW": b"\x80\x97",
        "EGLO-ZM-Dimmable": b"\x20\x98",
        "EGLO-ZM-RGB-TW": b"\x20\x96",
        "EGLO-ZM-RGB-W": b"\x20\xc0",
        "EGLO-ZM-RGBTW-CLP": b"\x20\xa2",
        "EGLO-ZM-TW": b"\x20\x97",
        "EGLO-ZM-TW-CLP": b"\x20\xa4",
        "EGLO-ZMB-Dimmable": b"\x60\x98",
        "EGLO-ZMB-Dimmable-I2C": b"\x61\x98",
        "EGLO-ZMB-RGB-TW": b"\x60\x96",
        "EGLO-ZMB-RGB-W": b"\x60\xc0",
        "EGLO-ZMB-TW": b"\x60\x97",
        "EGLO-ZMB-TW-2BT": b"\x60\xc4",
        "EGLO-ZMB-TW-CLB": b"\x60\xa3",
        "EGLO-ZMB-TW-CLP": b"\x60\xa4",
        "EGLO-ZMB-TW-I2C": b"\x61\x97",
        "EMAT-RGB-TW-CLB": b"\x80\xa1",
        "EMAT-RGB-TW-CLP": b"\x80\xa2",
        "EMAT-RGB-TW-I2C": b"\x81\x96",
        "EMAT-RGB-W-I2C": b"\x81\xc0",
        "EMAT-TW-CLP": b"\x80\xa4",
        "EPIR-Zm": b"\x20\x58",
        "ERCU-3groups-Zm": b"\x20\x2c",
        "ERCU-WS-Zm": b"\x20\x2d",
        "ERCU-Zm": b"\x20\x28",
        "ESMLFzm-w6-Dimm": b"\x20\xa7",
        "ESMLFzm-w6-TW": b"\x20\xa6",
        "ESMLzm-TW-GU10": b"\x20\x3e",
        "ESMLzm-c13g": b"\x20\x5a",
        "ESMLzm-c5-E14": b"\x20\x3d",
        "ESMLzm-c5-GU10": b"\x20\x3c",
        "ESMLzm-c9": b"\x20\x23",
        "EZMB-RGB-TW-2BT": b"\x60\xc2",
        "EZMB-RGB-TW-CLB": b"\x60\xa1",
        "EZMB-RGB-TW-CLP": b"\x60\xa2",
        "EZMB-RGB-TW-I2C": b"\x61\x96",
        "EZMB-RGB-W-I2C": b"\x61\xc0",
        "GENLzm": b"\x20\x00",
    }
)


def _inverse():
    result: dict[bytes, list[AwoXModel]] = defaultdict(list)
    for name, code in _NAME_TO_CODE.items():
        model = lookup_model(name)
        assert model is not None, f"Unregistered descriptor name: {name}"
        result[code].append(model)
    return MappingProxyType({code: tuple(models) for code, models in result.items()})


_CODE_TO_MODELS = _inverse()


def registered_model_code(name: str) -> bytes | None:
    """Return a name-registered model's raw 2-byte Descriptor.i() code.

    This is not a read of device firmware or advertised capabilities.
    """
    return _NAME_TO_CODE.get(name) if isinstance(name, str) else None


def lookup_models_by_code(
    model_lookup_code: bytes | bytearray | memoryview,
) -> tuple[AwoXModel, ...]:
    """Find all registered names for a scanner-masked two-byte model code.

    Pass `AdvertisementRecord.model_lookup_code`, NOT `model_code`.
    Returns an empty tuple for invalid/unknown input. For aliases, returns
    all matching registered names; no arbitrary unique name is invented.
    Unknown codes can have separate fallback behavior in the Android APK,
    which this exact register intentionally does not simulate.
    """
    if not isinstance(model_lookup_code, (bytes, bytearray, memoryview)):
        return ()
    try:
        size = (
            model_lookup_code.nbytes
            if isinstance(model_lookup_code, memoryview)
            else len(model_lookup_code)
        )
        if size != 2:
            return ()
        code = bytes(model_lookup_code)
    except (ValueError, BufferError):
        return ()
    if len(code) != 2:
        return ()
    return _CODE_TO_MODELS.get(code, ())
