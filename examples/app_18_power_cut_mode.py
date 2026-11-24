"""Read power-cut behavior, write one selected mode, then read it back.

Choose "previous", "on" or "scene" below. The script writes the selected mode.
The "scene" mode requests one fixed white light state after a future power loss.
This example does not cut power or demonstrate immediate light changes.
It replaces persistent power-cut settings without restoring the original;
The "scene" mode replaces the custom power-cut scene, not a numbered scene slot.
"""

import asyncio
from awox import AwoXMeshSession, ESPHomeProxy, Credentials, power_cut_white_scene

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
LAMP_MAC = ""               # Target lamp Bluetooth MAC address
MESH_ID = 0                 # Target lamp mesh ID (for example 0x1234)
GATEWAY_MAC = LAMP_MAC      # BLE gateway in the same mesh; may differ from target


# Choose one behavior after power returns: "previous", "on" or "scene".
# "scene" uses 50% brightness and white-temperature 50% (304 mired).
POWER_CUT_MODE = "previous"  # Choose previous, on or scene


async def main():
    if not PROXY_HOST or not MESH_NAME or not LAMP_MAC or not MESH_ID:
        raise ValueError("Set PROXY_HOST, MESH_NAME, LAMP_MAC and MESH_ID in this example.")
    if POWER_CUT_MODE not in ("previous", "on", "scene"):
        raise ValueError('POWER_CUT_MODE must be "previous", "on" or "scene".')
    scene = power_cut_white_scene(50, 50) if POWER_CUT_MODE == "scene" else None
    credentials = Credentials(MESH_NAME, MESH_PASSWORD)
    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(
            lambda: proxy.create_transport(GATEWAY_MAC),
            credentials,
            {MESH_ID: LAMP_MAC},
        ) as mesh:
            lamp = mesh.lamp(MESH_ID)
            current = await lamp.read_power_cut_mode(timeout=15)
            print("Current power-cut settings:", current)
            if current is None:
                print("No power-cut response; nothing was written.")
                return
            print("Stored power-cut scene settings:", current.scene_settings)

            # One deliberate setting change, followed by a separate read.
            response = await lamp.set_power_cut_mode(POWER_CUT_MODE, scene=scene, timeout=15)
            print(f"Set power-cut {POWER_CUT_MODE.upper()} response:", response)
            readback = await lamp.read_power_cut_mode(timeout=15)
            print("Power-cut readback:", readback)


if __name__ == "__main__":
    asyncio.run(main())
