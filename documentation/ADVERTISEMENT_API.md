# Advertisement and status decoding

`advertisements.AdvertisementRecord` parses manufacturer data and raw AD fields.
Layout selection follows model/firmware/address rules from the APK; the caller
does not manually select a parser family. The model tables cover 48 registered
Modern Mesh names, codes and descriptor-property lists from both APK versions.
Known lamp, ERCU, EPIR, compact and full-MAC layouts remain distinct.

Records retain raw data and available metadata when a packet is short or a
field has no established meaning. No inferred lux, temperature or control
capability is created for RCU/PIR devices. `mesh_address_unsigned` is the
explicit 16-bit representation of the APK scanner's signed address.

`ESPHomeProxy.on_advertisement(callback)` returns an unsubscribe function.
Callbacks include repeated accepted observations. Cache snapshots do not
generate synthetic new events. `received_monotonic` records observation age;
a snapshot may contain old records. Backend metadata can merge packets and is
not necessarily one original radio advertisement.

`status.parse_status_variant` exposes the APK da.b/da.c/da.d structures,
including raw provisioning/endpoint fields. `parse_lamp_status` is a separate,
conservative lamp-only view. StatusStore checks known IDs and MAC tails.
Remote/PIR frames remain inspectable without being published as lamp state.
These are decoders, not capability negotiation or authenticated statements.
