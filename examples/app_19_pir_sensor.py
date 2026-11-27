"""Read PIR configuration/light level, then write one chosen configuration.

Connect directly to a compatible PIR sensor. By default, NIGHT is disabled white and MOTION
is enabled green. The commented MOTION alternative selects a sequence instead;
choose one configuration, not two consecutive writes. These are stored sensor
actions, not immediate lamp colors.
Luminosity is raw 0..255, not lux; native setting ranges are noted below.

WARNING: The final write replaces PIR settings. Its 0x11 packet has no target
address and no proven per-device acknowledgment. The two reads are addressed,
but their replies do not identify the sender. The example stops without
writing if the first settings read times out. Review PIR_SETTINGS_TO_WRITE
before running; its values are an explicit configuration, not a backup.
"""

import asyncio
from awox import AwoXMeshSession, ESPHomeProxy, Credentials, PirSettings, SceneConfig

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
LAMP_MAC = ""               # Target PIR device MAC address
MESH_ID = 0                 # Target PIR mesh address (e.g. 0x1234)

# Deliberate example values, not discovered defaults or a backup of the device.
# Light action mode 0 = white (brightness and temperature in percent).
# Mode 1 = HSV (hue 0..<360 degrees, saturation 0..1, brightness in percent).
# Mode 2 selects a sequence preset; see SceneConfig in the command reference.
# motion_enabled and nightlight_enabled select the two actions independently.
MOTION_ACTION = SceneConfig(mode=1, brightness=80, hue=120.0, saturation=1.0)  # Motion-triggered light action
# Alternative: replace MOTION_ACTION above with this sequence configuration.
# MOTION_ACTION = SceneConfig(mode=2, brightness=80, sequence_preset=1,
#                            sequence_fade_duration=500)
# Fade is quantized in 100 raw units; no physical time unit is assumed.

PIR_SETTINGS_TO_WRITE = PirSettings(  # Entire replacement PIR configuration
    nightlight=SceneConfig(mode=0, brightness=30, temperature=25),
    motion=MOTION_ACTION,
    sensitivity=5,          # Native index 0..15.
    timeout=30,              # Native byte; do not assume this means seconds.
    motion_enabled=True,
    nightlight_enabled=False,
    luminosity_threshold=2,  # Index 0..7, not a lux threshold.
)


async def main():
    if not PROXY_HOST or not MESH_NAME or not LAMP_MAC or not MESH_ID:
        raise ValueError("Set PROXY_HOST, MESH_NAME, LAMP_MAC and MESH_ID in this example.")
    credentials = Credentials(MESH_NAME, MESH_PASSWORD)

    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(
            lambda: proxy.create_transport(LAMP_MAC),
            credentials,
            {MESH_ID: LAMP_MAC},
        ) as mesh:
            # These reads are addressed, but the replies have no source ID.
            settings = await mesh.read_pir_settings(MESH_ID, timeout=15)
            if settings is None:
                print("PIR settings: no matching reply within 15 seconds; nothing was written.")
                return
            print("PIR settings:", settings)
            print("  NIGHT light action:", settings.nightlight)
            print("  MOTION light action:", settings.motion)
            print("  Sensitivity (raw):", settings.sensitivity)
            print("  Timeout (raw):", settings.timeout)
            print("  Motion enabled:", settings.motion_enabled)
            print("  Nightlight enabled:", settings.nightlight_enabled)
            print("  Luminosity threshold index:", settings.luminosity_threshold)
            print("  Reserved flags (raw):", f"0x{settings.reserved_flags_raw:02X}")

            # A raw light-level byte or None; no conversion to lux is known.
            luminosity = await mesh.read_pir_luminosity_raw(MESH_ID, timeout=15)
            print("Ambient light (raw 0..255, not lux):", luminosity)

            # CAUTION: 0x11 does NOT encode MESH_ID or a target address.
            await mesh.set_pir_settings(PIR_SETTINGS_TO_WRITE)
            print("One addressless PIR settings write sent (no device ACK).")


if __name__ == "__main__":
    asyncio.run(main())
