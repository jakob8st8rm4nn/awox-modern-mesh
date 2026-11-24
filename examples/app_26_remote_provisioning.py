"""Enroll a factory ERCU-Zm, ERCU-3groups-Zm or ERCU-WS-Zm remote.

Activate smartphone mode (Bluetooth pairing mode) according to the remote's
manual when prompted. Supply the existing mesh credentials/key. Choose three
ordered button groups for ERCU-3groups-Zm, or one group for the other models.
This replaces persistent remote settings; it does not add lamps to the groups
or update App/cloud records. The received name is used for the current login;
MESH_NAME is the desired network name written during setup. Verify the
controls physically afterward.

The three-group model writes its list before network setup; the other models
carry their single group in the network parameters. The group-list write
does not require a positive ACK before network setup.
All three models use the one-second wizard pause before network setup. On
the three-group model the pause follows the group-list write.
"""

import asyncio
from awox import (AwoXMeshSession, AdvertisementRecord, Credentials,
                  DiscoveredDevice, ESPHomeProxy, ProvisioningSettings,
                  factory_credentials, registered_model_code)

# Edit your local copy; never commit real credentials or device identifiers.
PROXY_HOST = ""             # ESPHome proxy IP address or hostname
PROXY_KEY = ""              # ESPHome API encryption key, if required
MESH_NAME = ""              # Existing mesh to join
MESH_PASSWORD = ""          # Existing mesh password
NETWORK_KEY_HEX = ""        # Existing 16-byte network key as 32 hex characters
REMOTE_MAC = ""             # Factory remote's Bluetooth address
BUTTON_GROUPS = (0x8000, 0x8001, 0x8002)  # ERCU-3groups-Zm: three groups, in button order.
# For ERCU-Zm or ERCU-WS-Zm, use one group instead, e.g. BUTTON_GROUPS = (0x8000,).


async def main():
    if not PROXY_HOST or not MESH_NAME or not REMOTE_MAC or not NETWORK_KEY_HEX:
        raise ValueError("Set PROXY_HOST, MESH_NAME, REMOTE_MAC and NETWORK_KEY_HEX.")
    if (not isinstance(BUTTON_GROUPS, (tuple, list)) or len(BUTTON_GROUPS) not in (1, 3)
            or any(type(group) is not int or not 1 <= group < 0xFFFF for group in BUTTON_GROUPS)):
        raise ValueError("Choose one or three distinct nonzero BUTTON_GROUPS, excluding broadcast.")
    if len(set(BUTTON_GROUPS)) != len(BUTTON_GROUPS):
        raise ValueError("Choose distinct BUTTON_GROUPS.")

    settings = ProvisioningSettings(
        Credentials(MESH_NAME, MESH_PASSWORD), bytes.fromhex(NETWORK_KEY_HEX),
        group_address=BUTTON_GROUPS[0] if len(BUTTON_GROUPS) == 1 else 0,
    )
    group_counts = {
        registered_model_code('ERCU-Zm'): 1,
        registered_model_code('ERCU-3groups-Zm'): 3,
        registered_model_code('ERCU-WS-Zm'): 1,
    }
    # A mutable collection is updated by the later advertisement callback.
    # This also lets Pylance see that a matching record may arrive asynchronously.
    matching_records: dict[str, AdvertisementRecord] = {}

    def remember_device(device: DiscoveredDevice) -> None:
        if device.address.upper() != REMOTE_MAC.upper():
            return
        candidate = device.advertisement
        if (candidate.firmware and candidate.mesh_address is not None
                and candidate.model_lookup_code in group_counts
                and candidate.local_name and candidate.local_name.strip()):
            # Short advertisements must not replace complete setup metadata.
            matching_records[REMOTE_MAC.upper()] = candidate

    async with ESPHomeProxy(PROXY_HOST, PROXY_KEY) as proxy:
        unsubscribe = proxy.on_advertisement(remember_device)
        try:
            await asyncio.to_thread(
                input, "Activate smartphone mode (Bluetooth pairing mode) as described in your remote's manual, then press Enter: "
            )
            print("Watching remote advertisements for 15 seconds...")
            await asyncio.sleep(15)
        finally:
            unsubscribe()
        record = matching_records.get(REMOTE_MAC.upper())
        if record is None:
            print("No complete supported ERCU advertisement with a name; nothing was written.")
            return
        # Keep the checked fields explicit so editors can narrow the types.
        if record.mesh_address is None or record.model_lookup_code is None:
            print("Incomplete remote identity; nothing was written.")
            return
        remote_name = record.local_name
        if remote_name is None or not remote_name.strip():
            print("Remote name missing; factory login cannot be prepared. Nothing was written.")
            return
        required_groups = group_counts[record.model_lookup_code]
        if len(BUTTON_GROUPS) != required_groups:
            raise ValueError(f"This remote requires {required_groups} BUTTON_GROUPS entries.")
        current_id = record.mesh_address & 0xFFFF

        # Authenticate with the current received name, not the new MESH_NAME.
        current = factory_credentials(
            REMOTE_MAC, record.model_lookup_code, record.firmware, name=remote_name,
        )
        # Connect directly to the remote; do not use another mesh gateway.
        async with AwoXMeshSession(
            lambda: proxy.create_transport(REMOTE_MAC), current,
        ) as setup:
            # Only the three-group model writes a separate ordered group list.
            if required_groups == 3:
                await setup.write_mesh_groups(current_id, BUTTON_GROUPS)
            # All models wait before starting the network setup.
            await asyncio.sleep(1)
            result = await setup.provision(
                current_id, settings, timeout=20,
                provisioning_byte=record.provisioning_byte,
            )
        if record.provisioning_byte == 0xA0:
            print("0xA0 provisioning branch: network parameters and key were skipped. Verify device operation separately.")
            return

        if not result.completed:
            print("No provisioning completion received; outcome unknown. Do not automatically retry.")
            return
        print("Provisioning completion observed; new ID:",
              f"0x{result.mesh_id:04X}" if result.mesh_id is not None else "not reported")
        print("Check buttons physically. Lamps must belong to the configured groups.")
        # Completion does not prove that every physical control works.


if __name__ == '__main__':
    asyncio.run(main())
