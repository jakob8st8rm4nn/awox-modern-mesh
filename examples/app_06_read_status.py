"""Compare a response-waiting status read, a send-only request and the cache.

Requires proxy settings and the target mesh-ID/MAC mapping. read_status returns
a newly received matching observation or None on reply timeout; transport errors
still raise. request_status sends once without waiting. The later cache print
may still show the earlier observation; it is not proof of a second reply.
No lighting or persistent configuration is changed. The status request
does not guarantee a reply.
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
LAMP_MODEL = ""             # APK model name; required for full-MAC da.b status
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
            device_models={MESH_ID: LAMP_MODEL} if LAMP_MODEL else None,
        ) as mesh:
            lamp = mesh.lamp(MESH_ID)
            # Wait for a matching observation. It can arrive during the query write.
            # There is no request ID proving that this query caused the reply.
            status = await lamp.read_status(timeout=15)
            print("Lamp status:", status)

            # Unlike read_status(), this only sends a request and does not wait.
            await lamp.request_status()
            print("Status request sent (no response wait).")

            await asyncio.sleep(2)
            # lamp.status reads the cache. It may still hold the earlier status.
            print("Cached status after request:", lamp.status)


if __name__ == "__main__":
    asyncio.run(main())
