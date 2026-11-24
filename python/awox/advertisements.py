"""Offline AdvertisingPacket/scan observations reconstructed from APK 1.14.11.

Sources: n7.a.a/b/c, c0.i1.n/s, n7.f.<init>/a/c, n7.f.b.run and
g7.a.onScanResult. No Bluetooth operations or inferred device-model catalogue.
"""

import math
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Mapping
from .model_properties import _is_light_model

AWOX_VENDOR = b"\x60\x01"
APPLE_VENDOR = b"\x4c\x00"
MANUFACTURER_DATA = 0xFF
COMPLETE_LOCAL_NAME = 0x09
COMPLETE_UUID128_LIST = 0x07


def _advertisement_bytes(value) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("advertisement data must be bytes, bytearray or memoryview")
    return bytes(value)


def parse_advertising_record(record: bytes) -> dict[int, bytes]:
    """n7.a.c: AD type -> payload, preserving the app's duplicate policy.

    Types are unsigned in this Python API (Java used signed Byte map keys).
    Zero ends parsing. A length >=128 ends parsing because the original reads
    a signed byte. A truncated field advances one byte and attempts to resume,
    matching the original's bounded malformed-record handling. No telemetry.
    """
    record = _advertisement_bytes(record)
    fields: dict[int, bytes] = {}
    offset = 0
    while offset < len(record):
        length = record[offset]
        if length == 0 or length >= 128:
            break
        end = offset + length
        if end < len(record):
            ad_type = record[offset + 1]
            value = record[offset + 2 : end + 1]
            previous = fields.get(ad_type)
            if (
                ad_type != MANUFACTURER_DATA
                or previous is None
                or len(previous) <= len(value)
            ):
                fields[ad_type] = value
            offset = end
        offset += 1
    return fields


def normalize_manufacturer_data(data: bytes) -> bytes | None:
    """n7.a.a(FF): normalize the app's >=29-byte manufacturer layout.

    At 29 bytes or longer, non-AwoX vendor data is rejected. Shorter data is
    returned unchanged, including other vendors, exactly as in this helper.
    Therefore this operation alone does not identify an AwoX device.
    """
    data = _advertisement_bytes(data)
    if len(data) < 29:
        return data
    if data[:2] != AWOX_VENDOR:
        return None
    return data[:2] + data[4:8] + b"\xc1\xa4" + data[2:4] + data[8:11] + data[13:29]


def advertising_field(record: bytes, ad_type: int) -> bytes | None:
    """n7.a.a: supported field selectors 09,07,FF; other selectors return None."""
    if ad_type not in (COMPLETE_LOCAL_NAME, COMPLETE_UUID128_LIST, MANUFACTURER_DATA):
        return None
    value = parse_advertising_record(record).get(ad_type)
    if value is None:
        return None
    if ad_type == MANUFACTURER_DATA:
        return normalize_manufacturer_data(value)
    return value


def manufacturer_mesh_address(record: bytes) -> int:
    """n7.a.b: signed Java short from RAW manufacturer offsets 11:13, else 0.

    This does not vendor-filter or use the normalized manufacturer layout.
    Callers requiring an unsigned destination can use result & 0xFFFF.
    """
    data = parse_advertising_record(record).get(MANUFACTURER_DATA, b"")
    return int.from_bytes(data[11:13], "little", signed=True) if len(data) > 12 else 0


def _mac_bytes(address: str | None) -> bytes | None:
    """Use the same sender identity for consistency checks and layout choice."""
    if not isinstance(address, str):
        return None
    compact = address.strip().replace(":", "").replace("-", "").replace(".", "")
    if len(compact) != 12:
        return None
    try:
        mac = bytes.fromhex(compact)
    except ValueError:
        return None
    return mac if len(mac) == 6 else None


def _verified_advertisement_mac_suffix(
    manufacturer: bytes, address: str | None
) -> bool:
    """Match known 96 20 manufacturer offsets 4:8 to the BLE sender's MAC tail.

    This is packet consistency validation, not authentication. The caller
    checks the confirmed layout before invoking this helper.
    """
    mac = _mac_bytes(address)
    return mac is not None and manufacturer[4:8] == mac[2:][::-1]


def manufacturer_firmware(data: bytes) -> str:
    """c0.i1.n: dotted unsigned bytes 10:13 of the supplied AwoX data, else ''."""
    if len(data) < 13 or data[:2] != AWOX_VENDOR:
        return ""
    return ".".join(str(value) for value in data[10:13])


@dataclass(frozen=True)
class AdvertisementLightState:
    """APK n7.k/n7.l light bytes for registered Modern Mesh lamps.

    Values describe a *broadcast advertisement*, not a verified GATT status.
    Mode-inapplicable fields and the 0xFFFF temperature sentinel are None.
    """

    flags: int
    is_on: bool
    color_mode: bool
    color_cycle: bool
    candle_mode: bool
    brightness_raw: int
    brightness_percent: float
    white_temperature_mired: int | None
    hue_raw: int | None
    saturation_raw: int | None
    hue_degrees: float | None
    saturation_percent: float | None
    temperature_percent_raw: int | None = None


def _advertisement_light_state(
    data: bytes, *, mired_layout: bool
) -> AdvertisementLightState:
    """Decode the selected n7.k (6 bytes) or n7.l (5 bytes) state block."""
    flags, brightness = data[0], data[1]
    color_mode = bool(flags & 0x02)
    mired = int.from_bytes(data[2:4], "little") if mired_layout else None
    hue, saturation = data[4:6] if mired_layout else data[3:5]
    # Same clamped 2..254 range as the APK; this convenience value remains
    # continuous rather than reproducing the UI's integer rounding.
    percentage = 100.0 * (min(254, max(2, brightness)) - 2) / 252
    return AdvertisementLightState(
        flags=flags,
        is_on=bool(flags & 0x01),
        color_mode=color_mode,
        color_cycle=bool(flags & 0x04),
        candle_mode=bool(flags & 0x10),
        brightness_raw=brightness,
        brightness_percent=percentage,
        white_temperature_mired=None if color_mode or mired == 0xFFFF else mired,
        temperature_percent_raw=(
            data[2] if not mired_layout and not color_mode else None
        ),
        hue_raw=hue if color_mode else None,
        saturation_raw=saturation if color_mode else None,
        hue_degrees=(hue * 360.0 / 254) if color_mode and hue != 0xFF else None,
        saturation_percent=(min(254, saturation) * 100.0 / 254) if color_mode else None,
    )


def _empty_mapping() -> Mapping:
    return MappingProxyType({})


@dataclass(frozen=True)
class AdvertisementRecord:
    """AwoX advertisement interpretation plus available proxy metadata.

    ``fields`` retains the original selected source (AD structures when raw,
    else the selected manufacturer field); ``raw_advertisement`` is a genuine
    packet only when the ESPHome firmware provided one. Additional proxy fields
    may be merged from multiple packets and must not be treated as a packet.
    """

    fields: Mapping[int, bytes]
    manufacturer: bytes | None
    normalized_manufacturer: bytes | None
    local_name: str | None
    model_code: bytes | None
    model_lookup_code: bytes | None
    firmware: str
    mesh_address: int | None
    hardware_version: str | None = None
    provisioning_byte: int | None = None
    light_state: AdvertisementLightState | None = None
    raw_advertisement: bytes | None = None
    raw_fields: Mapping[int, bytes] = field(default_factory=_empty_mapping)
    manufacturer_data: Mapping[int, bytes] = field(default_factory=_empty_mapping)
    service_data: Mapping[str, bytes] = field(default_factory=_empty_mapping)
    service_uuids: tuple[str, ...] = ()
    received_monotonic: float | None = None
    source: str | None = None
    connectable: bool | None = None

    @property
    def awox_vendor(self) -> bool:
        """Whether the selected advertisement data carries the AwoX manufacturer prefix."""
        return self.manufacturer is not None and self.manufacturer[:2] == AWOX_VENDOR

    @property
    def apple_vendor(self) -> bool:
        """Whether the selected advertisement data carries the Apple manufacturer prefix."""
        return self.manufacturer is not None and self.manufacturer[:2] == APPLE_VENDOR

    @property
    def mesh_address_unsigned(self) -> int | None:
        """Unsigned mesh ID, or None when the advertisement has no mesh address."""
        return None if self.mesh_address is None else self.mesh_address & 0xFFFF

    @classmethod
    def from_bytes(
        cls, record: bytes, *, name_encoding: str = "utf-8", address: str | None = None
    ) -> "AdvertisementRecord":
        """Decode AD fields; supply the BLE address for full-MAC lamp layouts.

        Without an address, the existing A4:C1 manufacturer layout is used.
        The proxy and ScanObservation supply the address automatically.
        """
        raw = _advertisement_bytes(record)
        fields = parse_advertising_record(raw)
        name = fields.get(COMPLETE_LOCAL_NAME)
        decoded = cls._from_fields(
            fields,
            name.decode(name_encoding, errors="replace") if name is not None else None,
            address=address,
        )
        return replace(
            decoded, raw_advertisement=raw, raw_fields=MappingProxyType(dict(fields))
        )

    @classmethod
    def from_manufacturer_data(
        cls,
        company_id: int,
        payload: bytes,
        *,
        local_name: str | None = None,
        address: str | None = None,
    ) -> "AdvertisementRecord":
        """Adapt one Bleak-style company ID/payload, without inventing a ScanRecord."""
        if type(company_id) is not int:
            raise TypeError("company_id must be an integer")
        if not 0 <= company_id <= 0xFFFF:
            raise ValueError("company_id must fit an unsigned 16-bit value")
        return cls._from_fields(
            {
                MANUFACTURER_DATA: company_id.to_bytes(2, "little")
                + _advertisement_bytes(payload)
            },
            local_name,
            address=address,
        )

    @classmethod
    def from_service_info(
        cls, info: object, *, received_monotonic: float | None = None
    ) -> "AdvertisementRecord | None":
        """Preserve all available ESPHome/habluetooth data in one snapshot.

        Structured manufacturer data is normally preferred when available.
        If raw AD data explicitly contains only the 8-byte short AwoX format,
        use that observation instead of a potentially merged long-format cache
        value. Raw AD bytes are *also* retained, never fabricated. Service
        data/name fields may come from a merged scanner cache, not this packet.
        Returns None when no acceptable AwoX observation is available.
        Records with an unknown model layout can retain their raw data.
        """
        manufacturers = {}
        for company, payload in (
            getattr(info, "manufacturer_data", None) or {}
        ).items():
            if type(company) is int and 0 <= company <= 0xFFFF:
                try:
                    manufacturers[company] = _advertisement_bytes(payload)
                except (TypeError, ValueError):
                    continue
        raw = getattr(info, "raw", None)
        try:
            raw = _advertisement_bytes(raw) if raw is not None else None
        except (TypeError, ValueError):
            raw = None
        raw_fields = parse_advertising_record(raw) if raw else {}
        address = getattr(info, "address", None)
        local_name = getattr(info, "name", None)
        raw_name = raw_fields.get(COMPLETE_LOCAL_NAME)
        raw_name = (
            raw_name.decode("utf-8", errors="replace") if raw_name is not None else None
        )
        parsed = None
        # In some proxy backends manufacturer_data is a merged discovery cache.
        # A raw AD record containing *only* a short 8-byte AwoX identity is
        # stronger evidence for this event than cached long manufacturer data.
        # Never synthesize a short packet from the cached manufacturer fields.
        raw_manufacturer = raw_fields.get(MANUFACTURER_DATA)
        if (
            raw_manufacturer is not None
            and len(raw_manufacturer) == 8
            and raw_manufacturer[:2] == AWOX_VENDOR
        ):
            parsed = cls._from_fields(
                raw_fields, local_name or raw_name, address=address
            )
        # Only this company ID can produce an AwoX manufacturer record.
        company_id = int.from_bytes(AWOX_VENDOR, "little")
        payload = manufacturers.get(company_id)
        if parsed is None and payload is not None:
            candidate = cls.from_manufacturer_data(
                company_id,
                payload,
                local_name=local_name if local_name is not None else raw_name,
                address=address,
            )
            if candidate.model_code is not None:
                parsed = candidate
        if parsed is None and raw:
            candidate = cls._from_fields(
                raw_fields,
                raw_name if raw_name is not None else local_name,
                address=address,
            )
            if candidate.awox_vendor and candidate.model_code is not None:
                parsed = candidate
        if parsed is None:
            return None
        # Only the APK/recording-confirmed Connect.Z 96 20 layout embeds the
        # BLE sender's last four MAC bytes at offsets 4:8 (company ID included).
        # Reject mismatches at the ESPHome ingress, before cache/callback/scan.
        # Other possible AwoX layouts have no verified offset: do not guess.
        manufacturer = parsed.manufacturer
        if (
            manufacturer is not None
            and len(manufacturer) >= 8
            and manufacturer[:4] == b"\x60\x01\x96\x20"
            and not _verified_advertisement_mac_suffix(manufacturer, address)
        ):
            return None
        services = {}
        for uuid, data in (getattr(info, "service_data", None) or {}).items():
            try:
                services[str(uuid)] = _advertisement_bytes(data)
            except (TypeError, ValueError):
                continue
        # info.time is the scanner timestamp. Do not invent an observation time
        # for a cache snapshot when the backend does not supply a timestamp.
        seen = received_monotonic
        if seen is None:
            seen = getattr(info, "time", None)
        if type(seen) not in (int, float) or (
            type(seen) is float and not math.isfinite(seen)
        ):
            seen = None
        connectable = getattr(info, "connectable", None)
        if type(connectable) is not bool:
            connectable = None
        return replace(
            parsed,
            raw_advertisement=raw,
            raw_fields=MappingProxyType(raw_fields),
            manufacturer_data=MappingProxyType(manufacturers),
            service_data=MappingProxyType(services),
            service_uuids=tuple(
                str(v) for v in (getattr(info, "service_uuids", None) or ())
            ),
            received_monotonic=seen,
            source=getattr(info, "source", None),
            connectable=connectable,
        )

    @classmethod
    def _from_fields(
        cls,
        fields: dict[int, bytes],
        local_name: str | None,
        *,
        address: str | None = None,
    ) -> "AdvertisementRecord":
        fields = {int(k): _advertisement_bytes(v) for k, v in fields.items()}
        manufacturer = fields.get(MANUFACTURER_DATA)
        normalized = (
            normalize_manufacturer_data(manufacturer)
            if manufacturer is not None
            else None
        )
        is_awox = manufacturer is not None and manufacturer[:2] == AWOX_VENDOR
        long_layout = is_awox and len(manufacturer) >= 29
        # Both layouts carry the same model pair at raw offsets 2:4.
        # Normalization moves it to 8:10 without changing those bytes.
        model = manufacturer[2:4][::-1] if is_awox and len(manufacturer) >= 8 else None
        lookup = bytes((model[0] & ~0x10, model[1])) if model is not None else None
        light_model = _is_light_model(lookup) if lookup is not None else None
        # n7.h includes all six MAC bytes. Only select it with positive
        # sender/layout evidence, never by interpreting firmware as MAC bytes.
        full_mac = False
        if long_layout and light_model is True:
            sender = _mac_bytes(address)
            full_mac = (
                sender is not None
                and sender[:2] != b"\xa4\xc1"
                and manufacturer[4:10] == sender[::-1]
            )
        # Firmware and mesh ID are absent in the 8-byte short variant.
        firmware = (
            manufacturer_firmware(normalized)
            if long_layout
            else (
                ".".join(str(value) for value in manufacturer[8:11])
                if is_awox and len(manufacturer) >= 11
                else ""
            )
        )
        mesh_address = (
            int.from_bytes(manufacturer[11:13], "little", signed=True)
            if is_awox and len(manufacturer) >= 13
            else None
        )
        hardware = provisioning = light_state = None
        if long_layout and light_model is not None:
            if light_model:
                if full_mac:
                    # n7.h: full MAC adds two bytes before firmware and state.
                    firmware = ".".join(str(v) for v in manufacturer[10:13])
                    mesh_address = int.from_bytes(
                        manufacturer[13:15], "little", signed=True
                    )
                    state_start, hardware_start, provisioning_at = 15, 21, 23
                    mired_layout = True
                else:
                    # n7.i below 2.0.27; n7.j at and above the boundary.
                    mired_layout = tuple(manufacturer[8:11]) >= (2, 0, 27)
                    state_start = 13
                    hardware_start = 19 if mired_layout else 18
                    provisioning_at = hardware_start + 2
                light_state = _advertisement_light_state(
                    manufacturer[state_start:], mired_layout=mired_layout
                )
            else:
                # v9.b.y(): registered RCU and PIR descriptors; these bytes
                # describe hardware/provisioning, never a lamp state.
                hardware_start, provisioning_at = 13, 15
            major, minor = manufacturer[hardware_start : hardware_start + 2]
            if not light_model:
                # n7.f.d formats these control-device bytes as signed Java
                # bytes; n7.h/i/j explicitly use unsigned lamp HW values.
                major = major if major < 128 else major - 256
                minor = minor if minor < 128 else minor - 256
            hardware = f"{major}.{minor}"
            provisioning = manufacturer[provisioning_at]
        return cls(
            MappingProxyType(fields),
            manufacturer,
            normalized,
            local_name,
            model,
            lookup,
            firmware,
            mesh_address,
            hardware_version=hardware,
            provisioning_byte=provisioning,
            light_state=light_state,
        )


@dataclass(frozen=True)
class ScanTiming:
    """Static Android scan settings/timers; transport scheduling is separate."""

    scan_mode: int = 2
    number_of_matches: int = 1
    batch_seconds: float = 0.8
    window_seconds: float = 6.5
    restart_delay_seconds: float = 0.5


def android_scan_permissions_granted(
    sdk: int, *, scan: bool = False, connect: bool = False, fine_location: bool = False
) -> bool:
    """n7.f.a DEX branches: Android >=31 needs both SCAN and CONNECT."""
    return scan and connect if sdk >= 31 else fine_location


@dataclass(frozen=True)
class ScanObservation:
    """One observed Bluetooth advertisement with optional raw AD bytes."""
    address: str
    rssi: int
    record: bytes | None
    device_name: str | None = None

    def __post_init__(self) -> None:
        if self.record is not None:
            object.__setattr__(self, "record", _advertisement_bytes(self.record))

    def decode(self) -> AdvertisementRecord | None:
        """Decode this observation into an advertisement record."""
        if self.record is None:
            return None
        decoded = AdvertisementRecord.from_bytes(self.record, address=self.address)
        return (
            replace(decoded, local_name=self.device_name)
            if decoded.local_name is None and self.device_name is not None
            else decoded
        )


class ScanBuffer:
    """g7.a callback + n7.f.b batch behavior: latest observation per address.

    No clock, Bluetooth access or thread-safety guarantee. A transport can drain
    this buffer every ScanTiming.batch_seconds. Android's ConcurrentHashMap
    traversal has no guaranteed ordering; callers must not depend on order here.
    """

    def __init__(self) -> None:
        self._observations: dict[str, ScanObservation] = {}

    def add(self, observation: ScanObservation) -> None:
        """Store the latest observed data for one device address."""
        self._observations[observation.address.upper()] = observation

    def drain(self, *, scanning: bool = True) -> tuple[ScanObservation, ...]:
        """Return buffered observations and clear the buffer."""
        observations = tuple(self._observations.values()) if scanning else ()
        self._observations.clear()
        return observations
