# Architecture

## Ownership

The flat package separates pure protocol functions from communication:

1. `_numeric`, `_validation`, model tables and `crypto` provide small rules.
2. `frames` provides envelopes, UUIDs and ATT transforms. `authentication`
   provides credentials, proof generation and session-key derivation.
3. `lighting`, `groups`, `power_cut`, `clock`, `schedule`, `presence`, `pir`,
   `provisioning`, `status` and `advertisements` own their exact wire layouts.
4. `transport` owns one GATT channel, operation serialization, deadlines and
   cleanup. Each channel has its own queue by default; callers may explicitly
   pass the same `GattQueue` to several channels to serialize their operations.
   Independent `AwoXMeshSession` connections do not share a global GATT lock.
   ESPHome-specific client/backend handling stays in the adapter.
5. `MeshConnection` owns the channel and active session key. One `connect()`
   performs one login attempt and receive activation, never provisioning.
6. `AwoXMeshSession` owns observations and bounded response receipts. `Lamp`
   and `MeshTarget` are thin targets with no connection or independent cache.

The same session exposes lighting, status and direct-device setup operations.

## Bluetooth receive activation

Before login, `MeshConnection` checks that Pair, Command and Notify are
present in the same AwoX GATT service instance. Missing characteristics stop
connection setup before the first Pair write.

The Android APK enables notifications on characteristic `1911` by writing
the CCCD descriptor `2902`. `ESPHomeNoCCCDTransport` subscribes through the
ESPHome API without a CCCD write. Custom GATT transports provide their own
subscription mechanism. After subscribing, `MeshConnection` writes `0x01`
to characteristic `1911` as part of receive activation.

## One write

The caller chooses a target or builds a pure Frame. The current connection is
captured; the connection serializes its writes, checks generation and encrypts
with its current key. GATT writes use `response=True`. A transport response confirms the GATT
write. A mesh reply or status readback is a separate observation. The library
does not replay the frame.

The frame's transition field requests a device fade; it is not a send delay.
Default 200 ms matches the APK. Dual-zone `00 02` and ordinary `02 00` are
different layouts and are not merged.

## Replies and observations

`frames.decode_notification` decrypts the receive envelope without claiming
message authentication. `on_notification` receives this raw envelope (including
0x37), with its opcode and unchanged payload; no domain-level completion is
inferred from `kind`. The session maintains passive identity-checked status
caches, while `read_`/`set_` use validated family decoders for their returns.
Optional APK response classifications are available through
`session.decode_apk_notification` for reference-data inspection. The live
notification callback uses a single raw receive decoder.

Receipt observation is armed at the actual write boundary. Waiting is explicit
and does not lock unrelated writes. Overlapping pending observation windows (including wildcard selectors and
0x80/0x82) are rejected locally; one notification completes at most one
receipt. Deadline checks use the receive timestamp even when timer callbacks are
late. A schedule pair also checks that timestamp against its shared deadline. Raw send-only writes remain possible, but cannot create causal
guarantees absent an on-air transaction identifier.

The application owns target selection, delays, retries and optional raw response
branches. The explicit low-level operations never initiate a follow-up write.
The optional `set_nightlight()` / `set_dawn_simulator()` convenience methods
implement the established 0x99-gated schedule pair. `provision()` implements
an APK-oriented direct-device setup sequence when deliberately invoked; it
writes optional groups without a mandatory positive 0x0C ACK, checks Pair07,
and observes 0x83. It does not scan devices, choose model groups, start a
wizard timer or retry. Reply locks serialize convenience calls that share a
reply selector. A schedule lock also guards a whole schedule operation on the
same destination, and a provisioning lock guards the direct setup sequence.

## Lifecycle

Only one independent `ESPHomeProxy` context can be active per process.
Several mesh sessions can share it, with separate GATT locks by default.
A queued convenience operation or a later schedule part raises
`ConnectionLost` if its original connection closes or is replaced before sending.

Only one owner may use a transport/channel. A dropped connection invalidates
old status, response windows and session-key use. Technical cleanup retains
ownership until it succeeds; an abandoned backend task cannot silently become
a new live session. Explicit reconnect is possible once cleanup is confirmed.
After a proxy loss, the ESPHome transport can finish local cleanup even if
the remote disconnect raises an API connection error. The BLE client and
backend must already report disconnection before the attempt and still report
it afterward. The wrapper must have released its scanner association. For a
general API connection error, the proxy API must also report disconnection.
Explicit reconnect remains the application's decision.

These protections do not add application-level retries.

A custom `GattTransport` must coordinate overlapping `connect()` and
`disconnect()` calls. After `disconnect()` returns successfully, an attempt
that overlapped it must be closed or invalidated so it cannot leave a physical
BLE link open. For example, the backend can invalidate the pending attempt and
dispose of any late connection it produces. `GattChannel` rejects the stale
connect result locally and can share an in-progress disconnect, so that
disconnect must also cover a link established while it is still running.

If an ESPHome API manager finishes starting after its context was closed, the
proxy stops that manager again. A failed late stop is logged and retained for
retry. Closing a newer context stops its own manager independently. To retry a
retained stop, explicitly call `await proxy.__aexit__()` on the same instance
after the newer context has closed. This cleanup wait is bounded to 15 seconds.
