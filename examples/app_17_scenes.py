"""Overwrite native scene slot 1 with red, change to blue, then recall slot 1.

Sends ON and changes the current color. Saving permanently replaces any prior
contents of slot 1; there is no backup, ACK wait or automatic restore. Printed
messages describe completed writes, not verified scene storage. If all commands
take effect, the lamp ends red and slot 1 contains the newly saved scene.
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
            # Turn the lamp on so both test colors are visible.
            await lamp.set_power(True)
            await lamp.set_rgb(255, 0, 0)
            print("Red command sent.")
            await asyncio.sleep(2)

            # WARNING: Saving overwrites the current contents of scene slot 1.
            await lamp.save_scene(1)
            print("Scene slot 1 save command sent.")
            await asyncio.sleep(2)

            await lamp.set_rgb(0, 0, 255)
            print("Blue command sent.")
            await asyncio.sleep(2)

            # Request recall of slot 1; this does not confirm that saving succeeded.
            await lamp.recall_scene(1)
            print("Scene slot 1 recall command sent; expect red again.")


if __name__ == "__main__":
    asyncio.run(main())
