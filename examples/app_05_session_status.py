"""Observe status/disconnect callbacks and an age-filtered in-memory cache.

Sends one initial read_status query, then prints the cache every two seconds;
these later prints do not send status polls. Expiry is visible only if no new
status arrives. A live session does not prove that every mesh lamp is reachable.
No light settings are changed and no automatic reconnect is attempted.
The separate on_mesh_status callback also reports APK status layouts and
raw zone bytes for registered devices.
"""

import asyncio
from awox import AwoXMeshSession, ESPHomeProxy, Credentials, LampStatus, MeshStatusFrame

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
LAMP_MAC = ""               # Target lamp Bluetooth MAC address
MESH_ID = 0                 # Target lamp mesh ID (for example 0x1234)
LAMP_MODEL = ""             # APK model name; required for full-MAC da.b status
GATEWAY_MAC = LAMP_MAC      # BLE gateway in the same mesh; may differ from target

STATUS_MAX_AGE = 10.0       # Seconds without a fresh status observation
OBSERVE_SECONDS = 16        # Expiry is visible only if no new statuses arrive
PRINT_INTERVAL_SECONDS = 2  # Cache-print interval; no status queries are sent


def on_status(status: LampStatus) -> None:
    """Synchronous callback for every valid status, including repeats."""
    print(
        f"on_status: mesh_id=0x{status.mesh_id:04X}, "
        f"is_on={status.is_on}, brightness_raw={status.brightness_raw}"
    )


def on_mesh_status(frame: MeshStatusFrame) -> None:
    """Observe all three APK status layouts for a registered MAC/mesh ID."""
    print(
        f"on_mesh_status: mesh_id=0x{frame.mesh_id:04X}, "
        f"zone_raw={frame.zone_raw}, layout={frame.layout}, "
        f"MAC={frame.mac_address}, embedded_full_MAC={frame.mac_embedded_full}, "
        f"mode=0x{frame.mode:02X}, temperature_mired={frame.white_temperature_mired}, "
        f"temperature_percent_raw={frame.temperature_percent_raw}"
    )


def on_disconnect() -> None:
    """Called if an established mesh connection is unexpectedly lost."""
    print("on_disconnect: mesh connection lost")


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
            on_status=on_status,
            on_mesh_status=on_mesh_status,
            on_disconnect=on_disconnect,
            status_max_age=STATUS_MAX_AGE,
        ) as mesh:
            print("Connected:", mesh.connected)

            # Request one observation. Later iterations only display the cache.
            print("Initial status:", await mesh.lamp(MESH_ID).read_status(timeout=15))
            print("Watching for status updates without further requests...")
            for elapsed in range(PRINT_INTERVAL_SECONDS, OBSERVE_SECONDS + 1, PRINT_INTERVAL_SECONDS):
                await asyncio.sleep(PRINT_INTERVAL_SECONDS)
                print(f"After {elapsed}s: connected={mesh.connected}")
                print("Cached states (fresh only):", mesh.states)
                print("Cached raw status frames (fresh only):", mesh.mesh_states)

            # After STATUS_MAX_AGE seconds without any fresh observation,
            # the entry vanishes from mesh.states, without a callback.
            print("Note: cache expiry itself does not invoke on_status.")


if __name__ == "__main__":
    asyncio.run(main())
