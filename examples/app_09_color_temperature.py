"""Change warm white at 3000 K to cooler white at 200 mired (5000 K).

The script switches the lamp on, then demonstrates Kelvin and native mired
inputs two seconds apart. The temperature commands do not change power or
brightness themselves. Native temperature accepts 153..454 mired. The lamp
stays on; no status readback is performed.
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
            await lamp.set_color_temperature(3000)
            print("White temperature set to 3000 K (write completed).")

            await asyncio.sleep(2)

            # Alternative native mired input. 200 mired is 5000 K.
            await lamp.set_color_temperature_mired(200)
            print("White temperature set to 200 mired (write completed).")


if __name__ == "__main__":
    asyncio.run(main())
