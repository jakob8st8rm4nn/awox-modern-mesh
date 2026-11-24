"""Change RGB red to approximately blue using native hue/saturation.

The script switches the lamp on, displays red, then sends native hue 169 and
saturation 255. RGB uses the APK conversion; native ranges are hue 0..254 and
saturation 0..255. RGB black requests a color, not OFF. The lamp stays on;
no status readback is performed.
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
            # RGB values: 0..255 for each channel (red in this example).
            await lamp.set_rgb(255, 0, 0)
            print("RGB color set to red (write completed).")

            await asyncio.sleep(2)

            # Native hue: 0..254; saturation: 0..255. This uses explicit saturation 255.
            await lamp.set_color_native(169, 255)
            print("Native hue/saturation set to 169/255 (write completed).")


if __name__ == "__main__":
    asyncio.run(main())
