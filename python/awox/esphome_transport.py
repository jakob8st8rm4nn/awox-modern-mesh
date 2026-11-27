"""Opt-in ESPHome-specific Bleak transport for 1911 without a CCCD.

The ESPHome backend private API is intentionally isolated here. Fail closed
if its ABI changes or if the actual selected backend isn't ESPHome. This is
not a portable Bleak notification implementation.
"""

from __future__ import annotations

import asyncio
import weakref
from typing import Callable

from ._validation import _valid_timeout
from .frames import NOTIFY_UUID, SERVICE_UUID
from .transport import (
    CCCD_UUID,
    ConnectionLost,
    DisconnectCallback,
    MissingCharacteristic,
    _notification_bytes,
)


def _notify_cleanup(value):
    if (
        not isinstance(value, (tuple, list))
        or len(value) != 2
        or not all(callable(item) for item in value)
    ):
        raise RuntimeError(
            "ESPHome backend subscription result must contain two cleanup callables"
        )
    return tuple(value)


from .frames import PAIR_UUID, COMMAND_UUID
from .transport import _read_bytes


class _ESPHomeBleakTransportBase:
    """Internal GATT operations through a client supplied by ESPHomeProxy.

    The library never constructs a local BleakClient or starts an OS BLE scan.
    Public callers should use ESPHomeProxy.create_transport(), which supplies a
    proxy-owned BLEDevice and client factory. The ESPHome adapter verifies
    the connected backend.
    """

    def __init__(self, device, *, client_factory=None) -> None:
        self.device = device
        self._factory = client_factory
        self._client = None
        self._characteristics = {}
        # Establishing a proxy-owned BLE client can complete after a close or
        # after a replacement connection. An epoch prevents that old result
        # from overwriting the active client (or leaking an orphaned link).
        self._connect_epoch = 0
        # Retain clients until teardown is complete, even after replacement.
        # Identity comparisons avoid backend equality semantics.
        self._cleanup_clients = []
        self._cleanup_lock = asyncio.Lock()

    async def _close_client(self, client) -> None:
        if not any(item is client for item in self._cleanup_clients):
            self._cleanup_clients.append(client)
        async with self._cleanup_lock:
            if not any(item is client for item in self._cleanup_clients):
                return  # Another explicit cleanup already closed this client.
            backend = getattr(client, "_backend", None)
            backend_type = getattr(self, "_backend_type", None)
            already_down = (
                backend_type is not None
                and isinstance(backend, backend_type)
                and getattr(backend, "is_connected", None) is False
                and getattr(client, "is_connected", None) is False
            )
            try:
                await client.disconnect()
            except Exception as exc:
                if (
                    not already_down
                    or getattr(backend, "is_connected", None) is not False
                    or getattr(client, "is_connected", None) is not False
                    or getattr(client, "_connected_scanner", None) is not None
                ):
                    raise
                try:
                    from aioesphomeapi.core import APIConnectionError, ConnectionNotEstablishedAPIError
                except ImportError:
                    raise exc from None
                # bleak-esphome can still attempt a remote disconnect after
                # its proxy-loss callback has already closed the local link.
                api_error = exc if isinstance(exc, APIConnectionError) else exc.__cause__
                api_client = getattr(backend, "_client", None)
                if not (
                    isinstance(api_error, ConnectionNotEstablishedAPIError)
                    or (
                        isinstance(api_error, APIConnectionError)
                        and getattr(api_client, "is_connected", None) is False
                    )
                ):
                    raise
            self._cleanup_clients[:] = [
                item for item in self._cleanup_clients if item is not client
            ]

    async def _retry_client_cleanup(self) -> None:
        for client in tuple(self._cleanup_clients):
            if any(item is client for item in self._cleanup_clients):
                await self._close_client(client)

    async def connect(self, disconnected: DisconnectCallback) -> None:
        """Connect one ESPHome-backed BLE client, with disconnect observation."""
        if self._cleanup_lock.locked():
            raise ConnectionLost("previous ESPHome BLE client cleanup is still pending")
        self._connect_epoch += 1
        epoch = self._connect_epoch
        previous, self._client = self._client, None
        self._characteristics.clear()
        if previous is not None:
            try:
                await self._close_client(previous)
            except BaseException:
                # Retain an unconfirmed old client for explicit cleanup, but
                # never overwrite a newer connection's ownership.
                if epoch == self._connect_epoch and self._client is None:
                    self._client = previous
                raise
            if epoch != self._connect_epoch:
                raise ConnectionLost("ESPHome BLE connection replaced during cleanup")
        await self._retry_client_cleanup()
        if epoch != self._connect_epoch:
            raise ConnectionLost("ESPHome BLE connection replaced during cleanup")
        if self._factory is None:
            raise RuntimeError(
                "ESPHome client factory is required; use ESPHomeProxy.create_transport()"
            )
        if not getattr(self.device, "address", None):
            raise ValueError("a proxy-discovered BLEDevice with address is required")

        def on_disconnect(_client):
            if epoch == self._connect_epoch:
                disconnected(0)

        client = await self._open_client(on_disconnect)
        if epoch != self._connect_epoch:
            # Disconnect this old result without touching a newer client.
            # Some backends finish connecting even after the caller has
            # already closed the transport or replaced its connection.
            if client is not self._client:
                try:
                    await self._close_client(client)
                except Exception:
                    pass  # Retained for later explicit cleanup; preserve context loss.
            raise ConnectionLost(
                "ESPHome BLE connection completed after close or replacement"
            )
        self._client = client

    async def _open_client(self, disconnected_callback):
        """Exactly one client.connect() call, with failed-client ownership retained."""
        client = self._factory(
            self.device,
            disconnected_callback=disconnected_callback,
            pair=False,
            _is_retry_client=True,
        )
        # The wrapper flag only disables its retry-connector advisory. No retry
        # connector is called: this adapter makes precisely one connect attempt.
        if not any(item is client for item in self._cleanup_clients):
            self._cleanup_clients.append(client)
        await client.connect()
        self._cleanup_clients = [
            item for item in self._cleanup_clients if item is not client
        ]
        return client

    async def discover_services(self) -> dict[str, frozenset[str]]:
        """Discover services on the connected ESPHome-backed client."""
        if self._client is None or not self._client.is_connected:
            raise ConnectionLost("transport is not connected")
        self._characteristics.clear()
        services = {}
        for service in self._client.services:
            chars = frozenset(c.uuid.lower() for c in service.characteristics)
            uuid = service.uuid.lower()
            # Retain an actual AwoX instance with all three session characteristics.
            # Never merge characteristics from separate instances.
            # Duplicate characteristic UUIDs remain blocked by _resolve().
            if (
                uuid != SERVICE_UUID
                or uuid not in services
                or {PAIR_UUID, COMMAND_UUID, NOTIFY_UUID}.issubset(chars)
            ):
                services[uuid] = chars
            for characteristic in service.characteristics:
                uuid = characteristic.uuid.lower()
                if uuid in self._characteristics:
                    # Ambiguous UUIDs require a service-aware backend, not an
                    # arbitrary choice of a characteristic handle.
                    self._characteristics[uuid] = None
                else:
                    self._characteristics[uuid] = characteristic
        return services

    def _resolve(self, uuid):
        if self._client is None or not self._client.is_connected:
            raise ConnectionLost("transport is not connected")
        characteristic = self._characteristics.get(uuid.lower())
        if characteristic is None:
            raise MissingCharacteristic(f"characteristic missing or ambiguous: {uuid}")
        return characteristic

    async def disconnect(self) -> None:
        # Invalidate an in-progress connection attempt before awaiting any
        # backend shutdown. A late completion must not reopen this transport.
        """Close the current ESPHome-backed BLE client."""
        self._connect_epoch += 1
        epoch = self._connect_epoch
        client, self._client = self._client, None
        self._characteristics.clear()
        if client is not None:
            try:
                await self._close_client(client)
            except BaseException:
                if epoch == self._connect_epoch and self._client is None:
                    self._client = client
                raise

        try:
            await self._retry_client_cleanup()
        except Exception:
            if client is None:
                raise
            # The current client closed successfully. Retain failed older
            # clients for a later explicit close or before another connect.

    async def read(self, characteristic: str) -> bytes:
        """Read one characteristic from the connected backend."""
        resolved = self._resolve(characteristic)
        return _read_bytes(await self._client.read_gatt_char(resolved))

    async def write(
        self, characteristic: str, data: bytes, response: bool = True
    ) -> None:
        """Write one characteristic through the connected backend."""
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("GATT write data must be bytes-like")
        resolved = self._resolve(characteristic)
        await self._client.write_gatt_char(resolved, bytes(data), response=response)

    async def request_mtu(self, mtu: int) -> int:
        """Request the MTU on the connected backend."""
        raise NotImplementedError(
            "Bleak has no portable public explicit MTU-request API; frame sizes vary by command"
        )


class ESPHomeNoCCCDTransport(_ESPHomeBleakTransportBase):
    """ESPHome-only GATT transport with CCCD-free Modern 1911 notifications.

    Requires an ESPHome-aware client_factory (HaBleakClientWrapper, after
    independent proxy discovery). No transport or network setup on import.
    """

    def __init__(
        self,
        device,
        *,
        client_factory=None,
        backend_type=None,
        subscribe_timeout: float = 12.0,
    ) -> None:
        super().__init__(device, client_factory=client_factory)
        if not _valid_timeout(subscribe_timeout):
            raise ValueError("subscribe_timeout must be positive")
        self._backend_type = backend_type
        self._subscribe_timeout = subscribe_timeout
        self._active_notify = None
        self._notify_owner = None
        self._notify_epoch = 0
        # A late unsubscribe and a replacement subscribe must not overlap
        # on the same ESPHome handle. stop_notify() invalidates a pending
        # subscribe before waiting for this lock and returns if none is active.
        # Same backend/handle must serialize late cleanup and replacement;
        # a reconnect uses a *different* backend and must not wait for the
        # old backend's potentially non-cooperative subscribe.
        self._notify_serial_locks = weakref.WeakValueDictionary()

    async def connect(self, disconnected):
        """Connect the ESPHome transport without requiring local CCCD writes."""
        if self._backend_type is None:
            raise RuntimeError(
                "ESPHome backend type is required; use ESPHomeProxy.create_transport()"
            )
        # A physical link loss does not necessarily invoke disconnect() on
        # this adapter. A new BLE client has no subscription, even if the
        # previous client's 1911 handle was active. Also reject callbacks
        # queued by that older registration.
        self._notify_epoch += 1
        self._active_notify = None
        self._notify_owner = None

        def on_link_lost(status):
            # The base transport only invokes this for the active client
            # epoch, so an old client's late callback cannot clear a new
            # subscription.
            self._notify_epoch += 1
            self._active_notify = None
            self._notify_owner = None
            disconnected(status)

        await super().connect(on_link_lost)
        try:
            self._checked_backend()
        except RuntimeError:
            try:
                await self.disconnect()
            finally:
                raise RuntimeError("non-ESPHome BLE backend refused")

    def _notify_characteristic(self):
        char = self._resolve(NOTIFY_UUID)
        matches = [
            c
            for service in self._client.services
            if service.uuid.lower() == SERVICE_UUID
            for c in service.characteristics
            if c.uuid.lower() == NOTIFY_UUID
        ]
        if len(matches) != 1 or matches[0] is not char:
            raise MissingCharacteristic("ambiguous or missing 1911 in service 1910")
        if "notify" not in char.properties:
            raise ValueError("1911 does not support notifications")
        descriptors = {d.uuid.lower() for d in char.descriptors}
        if CCCD_UUID in descriptors:
            raise ValueError(
                "1911 has a CCCD; use normal Bleak notify, not this adapter"
            )
        return char

    def _checked_backend(self):
        if self._backend_type is None:
            raise RuntimeError(
                "ESPHome backend type is required; use ESPHomeProxy.create_transport()"
            )
        backend = getattr(self._client, "_backend", None)
        if not isinstance(backend, self._backend_type):
            raise RuntimeError("non-ESPHome BLE backend refused")
        return backend

    def _require_esphome_backend(self):
        backend = self._checked_backend()
        api = getattr(
            getattr(backend, "_client", None), "bluetooth_gatt_start_notify", None
        )
        registry = getattr(backend, "_notify_cancels", None)
        address = getattr(backend, "_address_as_int", None)
        if (
            not callable(api)
            or not isinstance(registry, dict)
            or not isinstance(address, int)
        ):
            raise RuntimeError("ESPHome backend private subscription interface changed")
        return backend, api, registry, address

    def _notify_lock(self, client):
        registry = getattr(getattr(client, "_backend", None), "_notify_cancels", None)
        key = id(registry)
        lock = self._notify_serial_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._notify_serial_locks[key] = lock
        return lock

    async def start_notify(
        self, characteristic: str, callback: Callable[[bytes], None]
    ) -> None:
        """Subscribe through the ESPHome notification path."""
        if not callable(callback):
            raise TypeError("notification callback must be callable")
        client = self._client
        lock = self._notify_lock(client)
        async with lock:
            if self._client is not client:
                raise ConnectionLost(
                    "ESPHome backend changed during notification setup"
                )
            await self._start_notify_locked(characteristic, callback, lock)

    async def _start_notify_locked(
        self, characteristic: str, callback: Callable[[bytes], None], lock: asyncio.Lock
    ) -> None:
        if characteristic.lower() != NOTIFY_UUID:
            raise ValueError("ESPHomeNoCCCDTransport supports 1911 notifications only")
        if self._active_notify is not None:
            raise RuntimeError("1911 is already subscribed")
        char = self._notify_characteristic()
        client = self._client
        _, api, registry, address = self._require_esphome_backend()
        if char.handle in registry:
            raise RuntimeError("1911 already registered in backend")
        loop = asyncio.get_running_loop()
        self._notify_epoch += 1
        epoch = self._notify_epoch

        def receive(_handle, value):
            packet = _notification_bytes(value)
            if packet is None:
                return

            def deliver():
                if epoch == self._notify_epoch and self._active_notify == char.handle:
                    callback(packet)

            try:
                loop.call_soon_threadsafe(deliver)
            except RuntimeError:
                pass  # Event loop has already closed; do not resurrect callbacks.

        # Using the underlying ESPHome API avoids Bleak's CCCD-writing path.
        # Some async backends suppress CancelledError while finishing an
        # in-progress subscription. Shield the backend task so cancellation of
        # this caller still takes effect immediately. If the backend finishes
        # *after* that cancellation/timeout, dispose its late callback instead
        # of treating the result as an active 1911 subscription.
        subscription = asyncio.create_task(
            api(address, char.handle, receive, timeout=self._subscribe_timeout)
        )

        def dispose_late(task: asyncio.Task) -> None:
            if task.cancelled():
                return
            try:
                late_cancel = task.result()
            except Exception:
                return  # Observe the backend failure after caller cancellation.
            try:
                stop, remove_callback = _notify_cleanup(late_cancel)
            except RuntimeError:
                return

            # Check ownership at the moment of stopping, not before
            # scheduling another task. A new registration uses the same lock
            # until its backend handle has been published.
            async def clean_late() -> None:
                async with lock:
                    try:
                        remove_callback()
                    except Exception:
                        pass
                    if char.handle not in registry:
                        try:
                            await stop()
                        except Exception:
                            pass

            asyncio.create_task(clean_late())

        try:
            cancel = await asyncio.wait_for(
                asyncio.shield(subscription), self._subscribe_timeout + 2
            )
        except BaseException:
            if epoch == self._notify_epoch:
                self._notify_epoch += 1
            subscription.add_done_callback(dispose_late)
            subscription.cancel()
            raise
        cancel = _notify_cleanup(cancel)
        if (
            epoch != self._notify_epoch
            or self._client is not client
            or not client.is_connected
        ):
            # The API may complete after stop_notify()/disconnect() has
            # invalidated this subscription. Remove its local callback and
            # (unless someone else owns the handle) stop the late subscription
            # instead of reviving _active_notify in an obsolete connection.
            stop, remove_callback = cancel
            try:
                remove_callback()
            finally:
                if char.handle not in registry:
                    try:
                        await stop()
                    except Exception:
                        pass  # preserve the context-loss error
            raise ConnectionLost(
                "ESPHome notification subscription closed during setup"
            )
        if char.handle in registry:
            # Remove only our new callback. Stopping notifications by handle
            # here would also stop the competing owner's subscription.
            _, remove_callback = cancel
            remove_callback()
            raise RuntimeError("1911 subscription registry changed concurrently")
        registry[char.handle] = cancel
        self._active_notify = char.handle
        self._notify_owner = cancel

    async def stop_notify(self, characteristic: str) -> None:
        """Stop the current ESPHome notification subscription."""
        if characteristic.lower() != NOTIFY_UUID:
            raise ValueError("ESPHomeNoCCCDTransport supports 1911 notifications only")
        # Invalidate delivery immediately, even while a subscribe/stop owns the lock.
        self._notify_epoch += 1
        if self._active_notify is None:
            return
        client = self._client
        async with self._notify_lock(client):
            if self._client is not client or self._active_notify is None:
                return
            handle = self._active_notify
            registry = getattr(
                getattr(client, "_backend", None), "_notify_cancels", None
            )
            cleanup = self._notify_owner
            if not isinstance(registry, dict) or registry.get(handle) is not cleanup:
                self._active_notify = self._notify_owner = None
                return
            try:
                if client is not None and client.is_connected:
                    await client.stop_notify(self._resolve(NOTIFY_UUID))
            except BaseException:
                # ESPHome pops this entry before awaiting its stop callable.
                # Restore our ownership for an explicit retry, never overwrite
                # another registration or a replacement client's state.
                if (
                    self._client is client
                    and client.is_connected
                    and self._active_notify == handle
                    and cleanup is not None
                    and handle not in registry
                ):
                    registry[handle] = cleanup
                raise
            else:
                if self._client is client and self._active_notify == handle:
                    self._active_notify = self._notify_owner = None

    async def disconnect(self) -> None:
        """Stop notifications and disconnect the ESPHome-backed transport."""
        self._notify_epoch += 1  # stale callbacks must not update new sessions
        self._active_notify = None
        self._notify_owner = None
        await super().disconnect()
