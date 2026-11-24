"""Send one group-list write and explicitly track its 0x0C reply.

Connect directly to the target lamp. Read its current group list first,
then write back those same values.
This avoids choosing new memberships, but still performs a persistent write.
The reply is only a result code, not proof that the saved list changed.
No automatic retry is attempted; use a test lamp and verify the readback.

For send-only operation, lamp.write_mesh_groups(groups) is available.
Do NOT call it as well: send_and_track_reply() already sends the frame once.
"""

import asyncio
from awox import AwoXMeshSession, ESPHomeProxy, Credentials
from awox.groups import set_mesh_groups, parse_mesh_groups_set_result

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
LAMP_MAC = ""               # Target lamp Bluetooth MAC address
MESH_ID = 0                 # Target lamp mesh ID (for example 0x1234)


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
            lamp = mesh.lamp(MESH_ID)
            original = await lamp.read_mesh_groups(timeout=15)
            if original is None:
                print("No group-list response; nothing was written.")
                return
            print("Groups before write:", original.group_addresses)

            # The builder creates a frame; send_and_track_reply sends it once.
            frame = set_mesh_groups(MESH_ID, original.group_addresses)
            receipt = await mesh.send_and_track_reply(
                frame, 0x0C, target=MESH_ID, timeout=5.0,
            )
            reply = await receipt.wait()
            if reply is None:
                print("No 0x0C reply within five seconds; write outcome unknown.")
                return

            raw = bytes((reply.opcode,)) + reply.payload
            result = parse_mesh_groups_set_result(raw)
            print("Group-write reply:", result, "success:", result.success)
            # Readback shows observed membership; the reply alone does not.
            readback = await lamp.read_mesh_groups(timeout=15)
            print("Groups after write:",
                  readback.group_addresses if readback is not None else "no response")


if __name__ == "__main__":
    asyncio.run(main())
