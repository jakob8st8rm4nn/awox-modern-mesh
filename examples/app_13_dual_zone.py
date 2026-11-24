"""Switch one selected Dual-Zone zone on, set it red, then switch it off.

Use a compatible device and choose ZONE below. The command's zone value has
no established universal mapping to reported endpoint IDs. Commands do not
wait for a per-zone confirmation or restore the earlier state.
"""

import asyncio
from awox import AwoXMeshSession, ESPHomeProxy, Credentials, MeshStatusFrame

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
LAMP_MAC = ""               # Target Dual-Zone device MAC address
MESH_ID = 0                 # Target mesh address (e.g. 0x1234)
GATEWAY_MAC = LAMP_MAC      # BLE gateway in the same mesh; may differ from target

ZONE = 0                    # Raw APK zone byte; no endpoint mapping is assumed.


def on_mesh_status(frame: MeshStatusFrame) -> None:
    """Print any valid registered-device status, including alternate layouts."""
    print(
        f"Endpoint status: mesh_id=0x{frame.mesh_id:04X}, "
        f"endpoint={frame.endpoint}, layout={frame.layout}, "
        f"power={frame.is_on}, brightness_raw={frame.brightness_raw}, "
        f"temperature_mired={frame.white_temperature_mired}, "
        f"temperature_percent_raw={frame.temperature_percent_raw}, "
        f"MAC={frame.mac_address}"
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
            on_mesh_status=on_mesh_status,
        ) as mesh:
            # Select the same raw zone for all three commands.
            await mesh.set_dual_zone_power(MESH_ID, zone=ZONE, enabled=True)
            print(f"Zone {ZONE}: ON command sent.")
            await asyncio.sleep(2)

            await mesh.set_dual_zone_rgb(
                MESH_ID, zone=ZONE, red=255, green=0, blue=0,
            )
            print(f"Zone {ZONE}: red command sent.")
            await asyncio.sleep(2)

            await mesh.set_dual_zone_power(MESH_ID, zone=ZONE, enabled=False)
            print(f"Zone {ZONE}: OFF command sent.")
            # Brightness and temperature can be substituted for the color
            # command; raw power state 2 has no established toggle meaning.


if __name__ == "__main__":
    asyncio.run(main())
