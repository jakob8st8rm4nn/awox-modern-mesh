"""Increase brightness from 50% to native level 220 (about 86.5%).

The script switches the lamp on, then displays each level for observation.
Percentage values 0..100 map to the APK range 2..254; 0% is minimum
brightness, not OFF. Native input accepts 1..255. The lamp stays on and no
status readback is performed.
"""

import asyncio
from awox import AwoXMeshSession, ESPHomeProxy, Credentials

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
LAMP_MAC = ""               # Target lamp Bluetooth MAC address
MESH_ID = 0                 # Target lamp mesh ID (for example 0x1234)
GATEWAY_MAC = LAMP_MAC      # BLE gateway in the same mesh; may differ from target


async def main():
    if not PROXY_HOST or not MESH_NAME or not LAMP_MAC or not MESH_ID:
        raise ValueError("Set PROXY_HOST, MESH_NAME, LAMP_MAC and MESH_ID in this example.")
    credentials = Credentials(MESH_NAME, MESH_PASSWORD)
    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(
            lambda: proxy.create_transport(GATEWAY_MAC),
            credentials,
            {MESH_ID: LAMP_MAC},
        ) as mesh:
            lamp = mesh.lamp(MESH_ID)
            await lamp.set_power(True)  # Make the following change visible.
            print("Lamp ON command sent for observation.")
            # First use the percentage scale.
            await lamp.set_brightness_percent(50)
            print("Brightness set to 50% (write completed).")

            await asyncio.sleep(2)

            # Then use the native scale: 220 is brighter than the previous 50%.
            await lamp.set_brightness_raw(220)
            print("Native brightness set to 220 (write completed).")


if __name__ == "__main__":
    asyncio.run(main())
