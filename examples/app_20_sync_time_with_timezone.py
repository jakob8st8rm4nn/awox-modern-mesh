"""Send the APK's explicit timezone/time command pair (0x29/0x30).

These commands have no individual lamp address and may affect the mesh.
Supply a valid POSIX rule matching the computer timezone used for the UTC
offset. Local validation checks the wire format only.
This example demonstrates the APK branch for MTU 43 or higher. The App sends
only 0x30 below that threshold. This example requires sufficient MTU and
does not perform an automatic fallback. Both commands use the same timestamp. 0x30
starts about 250 ms after 0x29 starts, without waiting for its reply. Backend
queues can alter the actual write spacing. A 0x29 reply reports 0 for success
or a nonzero result code. None means no reply. The App can retry a negative
0x29 result. This example sends each command once.
"""

import asyncio
from datetime import datetime
from awox import AwoXMeshSession, ESPHomeProxy, Credentials
from awox.clock import build_time, build_time_with_timezone

# Edit the settings in your local copy; keep credentials private.
PROXY_HOST = ""             # ESPHome Bluetooth proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key (empty if not used)
MESH_NAME = ""              # AwoX mesh name
MESH_PASSWORD = ""          # AwoX mesh password
GATEWAY_MAC = ""           # Bluetooth MAC of a device in this mesh
# The rule below is for Central Europe; change it for another timezone.
# It must match the computer timezone used for the UTC offset.
POSIX_TIMEZONE_RULE = "CET-1CEST,M3.5.0,M10.5.0/3"  # POSIX rule for the local timezone


def checked_local_time() -> tuple[int, int]:
    local_time = datetime.now().astimezone()
    timestamp_ms = int(local_time.timestamp() * 1000)
    utc_offset = local_time.utcoffset()
    if utc_offset is None:
        raise RuntimeError("No UTC offset available for the local timezone")
    offset = int(utc_offset.total_seconds())

    build_time_with_timezone(timestamp_ms, POSIX_TIMEZONE_RULE)
    build_time(timestamp_ms, offset)
    return timestamp_ms, offset


async def main():
    if not PROXY_HOST or not MESH_NAME or not GATEWAY_MAC:
        raise ValueError("Set PROXY_HOST, MESH_NAME and GATEWAY_MAC in this example.")
    credentials = Credentials(MESH_NAME, MESH_PASSWORD)

    # Reject local encoding errors before any Bluetooth I/O.
    checked_local_time()

    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        async with AwoXMeshSession(
            lambda: proxy.create_transport(GATEWAY_MAC),
            credentials,
        ) as mesh:
            timestamp_ms, offset = checked_local_time()

            # Schedule the second command after 250 ms; backend queues may delay it.
            # Do not wait for the 0x29 ACK before sending 0x30.
            time29 = asyncio.create_task(mesh.set_time_with_timezone(
                timestamp_ms, POSIX_TIMEZONE_RULE, timeout=15,
            ))
            try:
                await asyncio.sleep(0.25)
                await mesh.set_time(timestamp_ms, offset)
            except BaseException:
                # Do not leave the 0x29 task running if the second write fails.
                time29.cancel()
                await asyncio.gather(time29, return_exceptions=True)
                raise
            print("0x30 clock command sent (no device ACK).")
            print("0x29 time/timezone response:", await time29)


if __name__ == "__main__":
    asyncio.run(main())
