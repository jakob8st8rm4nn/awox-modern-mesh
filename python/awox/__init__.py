"""AwoX Modern Mesh protocol building blocks. Importing performs no I/O."""

from .authentication import Credentials
from .frames import Frame, ExtendedCommand, ExtendedNotification
from .session import AwoXMeshSession, Receipt
from .targets import Lamp, MeshTarget
from .transport import GattQueue, ConnectionLost, DiscoveredDevice
from .esphome_proxy import ESPHomeProxy
from .advertisements import AdvertisementRecord, AdvertisementLightState
from .esphome_transport import ESPHomeNoCCCDTransport
from .status import (
    LampStatus,
    StatusStore,
    MeshStatusFrame,
    parse_lamp_status,
    parse_status_variant,
    status_query,
)
from .provisioning import ProvisioningSettings, ProvisioningResult, factory_credentials
from .groups import MeshGroupMembership, MeshGroupSetResponse
from .power_cut import (
    PowerCutConfiguration,
    PowerCutSetResponse,
    power_cut_white_scene,
    power_cut_color_scene,
)
from .light_settings import (
    LightSettings,
    decode_light_settings,
    routine_white_settings,
    routine_color_settings,
)
from .schedule import (
    SchedulePart,
    ScheduleRead,
    ScheduleWritePart,
    ScheduleSetResponse,
    ScheduleWriteResult,
)
from .presence import PresenceRead, PresenceWritePart, PresenceSetResponse
from .pir import PirSettings, SceneConfig
from .clock import Time29Ack
from .timezone_rule import (
    AndroidTransitionRule,
    apk_posix_offset,
    apk_transition_time,
    format_apk_transition,
    format_apk_fixed_timezone,
    format_apk_dst_timezone,
)
from .model_registry import AwoXModel, lookup_model, scanned_model_name
from .model_codes import lookup_models_by_code, registered_model_code
from .model_properties import lookup_model_properties

from .clock import build_time, build_time_with_timezone
from .crypto import aes_att_encryption, aes_att_decryption

from .presence import parse_presence_read, parse_presence_set
from .schedule import parse_schedule_read, parse_schedule_set
