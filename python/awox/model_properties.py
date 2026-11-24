"""Exact app-descriptor property lists from APK 1.14.10 and 1.14.11.

Data only: not a hardware negotiation, live device report, UI capability gate,
or assertion that the Python library implements every named property.
Do not infer properties from a model name or Bluetooth/GATT identifiers.
"""

from __future__ import annotations
from types import MappingProxyType
from .model_codes import lookup_models_by_code

_PROFILES = (
    (
        "power_state",
        "light_mode",
        "white_brightness",
        "white_temperature",
        "color_brightness",
        "color",
        "mesh_network",
        "mesh_groups",
        "mesh_address",
        "mesh_ota",
        "power_loss_recovery",
        "scenes",
        "time",
        "timer",
        "nightlight",
        "dawn_simulator",
        "presence_simulator",
        "program",
        "set_candle_mode",
        "color_sequence_colors",
        "power_cut_set_mode",
        "power_cut_get_mode",
    ),
    (
        "power_state",
        "light_mode",
        "white_brightness",
        "white_temperature",
        "color_brightness",
        "color",
        "mesh_network",
        "mesh_groups",
        "mesh_address",
        "mesh_ota",
        "power_loss_recovery",
        "scenes",
        "time",
        "timer",
        "nightlight",
        "dawn_simulator",
        "presence_simulator",
        "program",
        "set_candle_mode",
        "color_sequence_colors",
        "power_cut_set_mode",
        "power_cut_get_mode",
        "dual_zone_power_state",
        "dual_zone_brightness",
        "dual_zone_color",
        "dual_zone_temperature",
    ),
    (
        "power_state",
        "white_brightness",
        "mesh_network",
        "mesh_groups",
        "mesh_address",
        "mesh_ota",
        "color_current sequence_sequence_id",
        "power_loss_recovery",
        "scenes",
        "time",
        "timer",
        "nightlight",
        "dawn_simulator",
        "program",
        "presence_simulator",
        "set_candle_mode",
        "power_cut_set_mode",
        "power_cut_get_mode",
    ),
    (
        "power_state",
        "white_brightness",
        "white_temperature",
        "mesh_network",
        "mesh_groups",
        "mesh_address",
        "mesh_ota",
        "color_current sequence_sequence_id",
        "power_loss_recovery",
        "scenes",
        "time",
        "timer",
        "nightlight",
        "dawn_simulator",
        "program",
        "presence_simulator",
        "set_candle_mode",
        "power_cut_set_mode",
        "power_cut_get_mode",
    ),
    (
        "power_state",
        "light_mode",
        "white_brightness",
        "color_brightness",
        "color",
        "mesh_network",
        "mesh_groups",
        "mesh_address",
        "mesh_ota",
        "power_loss_recovery",
        "scenes",
        "time",
        "timer",
        "nightlight",
        "dawn_simulator",
        "presence_simulator",
        "program",
        "set_candle_mode",
        "color_sequence_colors",
        "power_cut_set_mode",
        "power_cut_get_mode",
    ),
    (
        "mesh_network",
        "mesh_groups",
        "mesh_ota",
        "pir_settings",
        "pir_settings_set",
        "pir_current_luminosity",
    ),
    (
        "mesh_network",
        "mesh_groups",
        "mesh_ota",
        "rcu_3_buttons",
    ),
    (
        "mesh_network",
        "mesh_groups",
        "mesh_ota",
    ),
)
_NAME_TO_PROFILE = MappingProxyType(
    {
        "E2G-ZMB-RGB-TW": 0,
        "EBF-RGB-ZMB": 0,
        "EBF-RGB-ZMB-CLB": 0,
        "EBF-RGB-Zm": 0,
        "EBF-RGB-Zm-CLP": 0,
        "EDUAL-RGB2TW-2BT": 1,
        "EDUAL-RGBTW-TW": 1,
        "EDUAL2G-RGBTW-TW": 1,
        "EGLO-MAT-Dimmable": 2,
        "EGLO-MAT-RGB-TW": 0,
        "EGLO-MAT-TW": 3,
        "EGLO-ZM-Dimmable": 2,
        "EGLO-ZM-RGB-TW": 0,
        "EGLO-ZM-RGB-W": 4,
        "EGLO-ZM-RGBTW-CLP": 0,
        "EGLO-ZM-TW": 3,
        "EGLO-ZM-TW-CLP": 3,
        "EGLO-ZMB-Dimmable": 2,
        "EGLO-ZMB-Dimmable-I2C": 2,
        "EGLO-ZMB-RGB-TW": 0,
        "EGLO-ZMB-RGB-W": 4,
        "EGLO-ZMB-TW": 3,
        "EGLO-ZMB-TW-2BT": 3,
        "EGLO-ZMB-TW-CLB": 3,
        "EGLO-ZMB-TW-CLP": 3,
        "EGLO-ZMB-TW-I2C": 3,
        "EMAT-RGB-TW-CLB": 0,
        "EMAT-RGB-TW-CLP": 0,
        "EMAT-RGB-TW-I2C": 0,
        "EMAT-RGB-W-I2C": 4,
        "EMAT-TW-CLP": 3,
        "EPIR-Zm": 5,
        "ERCU-3groups-Zm": 6,
        "ERCU-WS-Zm": 7,
        "ERCU-Zm": 7,
        "ESMLFzm-w6-Dimm": 2,
        "ESMLFzm-w6-TW": 3,
        "ESMLzm-TW-GU10": 3,
        "ESMLzm-c13g": 0,
        "ESMLzm-c5-E14": 0,
        "ESMLzm-c5-GU10": 0,
        "ESMLzm-c9": 0,
        "EZMB-RGB-TW-2BT": 0,
        "EZMB-RGB-TW-CLB": 0,
        "EZMB-RGB-TW-CLP": 0,
        "EZMB-RGB-TW-I2C": 0,
        "EZMB-RGB-W-I2C": 4,
        "GENLzm": 0,
    }
)


def lookup_model_properties(name: str) -> tuple[str, ...] | None:
    """Return registered descriptor properties in original order, or None.

    A property is listed by the Android model descriptor, not necessarily
    a verified physical device feature or a currently implemented command.
    The tuple preserves duplicate property entries seen in the APK.
    """
    if not isinstance(name, str):
        return None
    profile = _NAME_TO_PROFILE.get(name)
    return _PROFILES[profile] if profile is not None else None


def _is_light_model(model_lookup_code: bytes) -> bool | None:
    """APK v9.b.q(): registered lighting properties, not a name heuristic.

    None means unknown or conflicting descriptors. Do not apply the APK's
    generic-lamp fallback to an unidentified device's state bytes.
    """
    models = lookup_models_by_code(model_lookup_code)
    classifications = {
        bool(
            {
                "white_brightness",
                "white_temperature",
                "color_brightness",
                "color",
            }.intersection(lookup_model_properties(model.name) or ())
        )
        for model in models
    }
    return classifications.pop() if len(classifications) == 1 else None
