"""Switch the RGB-capable zone on, set it red, then switch it off.

Set the model name to match your device. The callback prints any zone
status received during the example.
The example sends each command once and leaves the selected zone off.
"""

import asyncio
from awox import AwoXMeshSession, ESPHomeProxy, Credentials, LampStatus

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
LAMP_MAC = ""               # Target Dual-Zone device MAC address
MESH_ID = 0                 # Target mesh address (e.g. 0x1234)
GATEWAY_MAC = LAMP_MAC      # BLE gateway in the same mesh; may differ from target

MODEL_NAME = "EDUAL-RGBTW-TW"  # Set the APK model name for your device.
ZONE = 0                      # RGB-capable zone.


def on_status(status: LampStatus) -> None:
    """Print the state of the zone that reported."""
    print(
        f"Zone {status.zone}: power={status.is_on}, "
        f"brightness={status.brightness_percent}%"
    )


async def main():
    if not PROXY_HOST or not MESH_NAME or not LAMP_MAC or not MESH_ID:
        raise ValueError("Set PROXY_HOST, MESH_NAME, LAMP_MAC and MESH_ID in this example.")
    credentials = Credentials(MESH_NAME, MESH_PASSWORD)

    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(
            lambda: proxy.create_transport(GATEWAY_MAC),
            credentials,
            {MESH_ID: LAMP_MAC},
            device_models={MESH_ID: MODEL_NAME},
            on_status=on_status,
        ) as mesh:
            # Select the same zone for all three commands.
            await mesh.set_dual_zone_power(MESH_ID, zone=ZONE, enabled=True)
            print(f"Zone {ZONE}: ON command sent.")
            await asyncio.sleep(2)

            # Hue is in degrees and saturation is in percent.
            await mesh.set_dual_zone_hs(MESH_ID, zone=ZONE, hue_degrees=0, saturation_percent=100)
            print(f"Zone {ZONE}: red command sent.")
            await asyncio.sleep(2)

            await mesh.set_dual_zone_power(MESH_ID, zone=ZONE, enabled=False)
            print(f"Zone {ZONE}: OFF command sent.")
            # Brightness and temperature can be substituted for the color
            # command; raw power state 2 has no established toggle meaning.


if __name__ == "__main__":
    asyncio.run(main())
