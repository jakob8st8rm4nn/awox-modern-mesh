"""Observe Candle, stop it, then observe and stop Color Cycle.

The script switches on a compatible lamp and observes each effect for 20
seconds. The lamp generates both effects; Python does not animate its colors.
Effect writes have no device confirmation. An interruption can leave an effect
active, and the previous color or effect is not restored. The lamp stays on.
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

            # 1. Candle effect. True starts it; False stops it.
            await lamp.set_candle_mode(True)
            print("Candle start command sent (not an effect acknowledgement).")
            await asyncio.sleep(20)
            await lamp.set_candle_mode(False)
            print("Candle stop command sent.")

            # 2. Color Cycle. The lamp produces the sequence itself.
            await lamp.set_color_cycle(True)
            print("Color Cycle start command sent.")
            await asyncio.sleep(20)
            await lamp.set_color_cycle(False)
            print("Color Cycle stop command sent.")


if __name__ == "__main__":
    asyncio.run(main())
