"""App-derived AwoX model-name register, without Bluetooth side effects.

Both APK versions 1.14.10 and 1.14.11 have the same effective name-to-
modern-model register (48 entries). The names are EXACT keys from MainApplication's
model registration, not inferred from marketing patterns or GATT UUIDs.

This module looks up exact app-registered names. The separate raw descriptor
codes and scanner-masked model-code lookup are implemented in model_codes.py.
The app also has fallback descriptors; unknown means UNKNOWN here.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal


@dataclass(frozen=True)
class AwoXModel:
    """Model name and transport family confirmed by the Android registry.

    This is intentionally NOT a capability/feature declaration. In particular
    `modern` does not imply RGB, tunable white, PIR or OTA support.
    """

    name: str
    protocol: Literal["modern"]


_MODELS = (
    "E2G-ZMB-RGB-TW",
    "EBF-RGB-ZMB",
    "EBF-RGB-ZMB-CLB",
    "EBF-RGB-Zm",
    "EBF-RGB-Zm-CLP",
    "EDUAL-RGB2TW-2BT",
    "EDUAL-RGBTW-TW",
    "EDUAL2G-RGBTW-TW",
    "EGLO-MAT-Dimmable",
    "EGLO-MAT-RGB-TW",
    "EGLO-MAT-TW",
    "EGLO-ZM-Dimmable",
    "EGLO-ZM-RGB-TW",
    "EGLO-ZM-RGB-W",
    "EGLO-ZM-RGBTW-CLP",
    "EGLO-ZM-TW",
    "EGLO-ZM-TW-CLP",
    "EGLO-ZMB-Dimmable",
    "EGLO-ZMB-Dimmable-I2C",
    "EGLO-ZMB-RGB-TW",
    "EGLO-ZMB-RGB-W",
    "EGLO-ZMB-TW",
    "EGLO-ZMB-TW-2BT",
    "EGLO-ZMB-TW-CLB",
    "EGLO-ZMB-TW-CLP",
    "EGLO-ZMB-TW-I2C",
    "EMAT-RGB-TW-CLB",
    "EMAT-RGB-TW-CLP",
    "EMAT-RGB-TW-I2C",
    "EMAT-RGB-W-I2C",
    "EMAT-TW-CLP",
    "EPIR-Zm",
    "ERCU-3groups-Zm",
    "ERCU-WS-Zm",
    "ERCU-Zm",
    "ESMLFzm-w6-Dimm",
    "ESMLFzm-w6-TW",
    "ESMLzm-TW-GU10",
    "ESMLzm-c13g",
    "ESMLzm-c5-E14",
    "ESMLzm-c5-GU10",
    "ESMLzm-c9",
    "EZMB-RGB-TW-2BT",
    "EZMB-RGB-TW-CLB",
    "EZMB-RGB-TW-CLP",
    "EZMB-RGB-TW-I2C",
    "EZMB-RGB-W-I2C",
    "GENLzm",
)

# Immutable internal mapping. Constructed once, no I/O and no dependencies.
_MODELS = MappingProxyType({name: AwoXModel(name, "modern") for name in _MODELS})


def lookup_model(name: str) -> AwoXModel | None:
    """Return an EXACT app-registered model or None if unknown.

    Never infer protocol from the shared 1910 GATT service, advertisement
    device name, or suffixes like RGB/TW. The APK has separate fallback rules.
    """
    return _MODELS.get(name) if isinstance(name, str) else None


def scanned_model_name(model_name: str, firmware: str) -> str:
    """Apply the two documented 2.5.0 scanner-name aliases, otherwise unchanged.

    This is only the name rewrite in n7.f.b.run, not a compatibility check.
    The caller must have identified the device's *model* name and firmware
    using the correct scan/App path. A BLE display name is not necessarily a
    model name. No firmware version ordering or broad suffix rewrite is used.
    """
    if firmware == "2.5.0" and model_name in ("EBF-RGB-Zm-CLP", "EGLO-ZM-TW-CLP"):
        return model_name[:-4]
    return model_name
