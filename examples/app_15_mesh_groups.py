"""Assign one lamp to a group, then switch the group on, blue and off.

WARNING: set_mesh_groups REPLACES the lamp's complete stored group list;
it can remove existing App memberships. Choose GROUP_DESTINATION deliberately.
The previous list is printed, not restored. Other existing group members
receive the same group commands. A GATT write is not a per-member ACK.
No broadcast or scene write is performed.
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

GROUP_DESTINATION = 0x8000  # Choose an actual group address from your mesh.


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
            existing = await lamp.read_mesh_groups(timeout=15)
            print("Current mesh groups:", existing)
            if existing is None:
                print("No group response; nothing was written.")
                return

            # Replace all memberships with this one group. To retain others,
            # include every desired address in the tuple; () clears the list.
            response = await lamp.set_mesh_groups((GROUP_DESTINATION,), timeout=15)
            print("Set mesh groups response:", response)
            readback = await lamp.read_mesh_groups(timeout=15)
            print("Mesh groups after writing:", readback)
            if readback is None or GROUP_DESTINATION not in readback.group_addresses:
                print("Requested membership not observed; group control skipped.")
                return

            group = mesh.group(GROUP_DESTINATION)
            await group.set_power(True)
            print("Group ON command sent.")
            await asyncio.sleep(2)

            await group.set_rgb(0, 0, 255)
            print("Group blue command sent.")
            await asyncio.sleep(2)

            await group.set_power(False)
            print("Group OFF command sent.")
            # group exposes the same light methods as a lamp. For all-device
            # control use mesh.broadcast(); this example sends no broadcast.


if __name__ == "__main__":
    asyncio.run(main())
