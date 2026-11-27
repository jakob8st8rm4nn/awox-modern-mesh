"""One BLE channel with Mesh login. No retries or provisioning workflow."""

from __future__ import annotations

import asyncio
import secrets
from typing import Callable
from ._validation import _valid_timeout
from .authentication import Credentials, login_request, derive_session_key
from .frames import (
    COMMAND_UUID,
    PAIR_UUID,
    SERVICE_UUID,
    NOTIFY_UUID,
    decode_notification,
    ExtendedNotification,
)
from .transport import (
    ConnectionLost,
    GattChannel,
    GattOperation,
    GattTransport,
    MissingCharacteristic,
    OperationKind,
    _observe_task_result,
)


class MeshConnection:
    """One Modern-Mesh GATT login attempt, receive activation and explicit writes.

    `login_accepted` means the protocol response was 0x0D with at least 8 bytes
    of challenge data and the key was derived. It is NOT an authenticated ACK.
    """

    def __init__(
        self,
        transport: GattTransport,
        credentials: Credentials,
        *,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
        connect_timeout: float = 20.0,
        operation_timeout: float = 30.0,
        on_notification=None,
    ) -> None:
        if any(
            not _valid_timeout(timeout)
            for timeout in (connect_timeout, operation_timeout)
        ):
            raise ValueError("timeouts must be positive")
        if not isinstance(credentials, Credentials):
            raise TypeError("credentials must be Credentials")
        self.channel = GattChannel(transport, operation_timeout=operation_timeout)
        self._credentials = credentials
        self._on_notification = on_notification
        self._ready = False
        self._random_bytes = random_bytes
        self._connect_timeout = connect_timeout
        self._session_key: bytes | None = None
        self._disconnect_seen = False
        self._disconnect_observer: Callable[[], None] | None = None
        self._lock = asyncio.Lock()
        self._connecting_task: asyncio.Task | None = None
        self._connect_setup_pending = False
        self._disconnect_serial = 0
        self._setup_cleanup: asyncio.Task | None = None

    @property
    def login_accepted(self) -> bool:
        """Whether the device accepted the current Mesh login."""
        return self.channel.active and self._session_key is not None

    def set_disconnect_observer(self, callback: Callable[[], None] | None) -> None:
        """Internal notification for a physical link loss; no BLE activity."""
        self._disconnect_observer = callback

    def _on_disconnect(self, _status: int = 0) -> None:
        already_seen = self._disconnect_seen
        self._disconnect_seen = True
        self._ready = False
        self._session_key = None
        if not already_seen and self._disconnect_observer is not None:
            self._disconnect_observer()

    async def _await_setup(self, awaitable):
        """Bound setup even when a backend suppresses cancellation."""
        deadline = asyncio.get_running_loop().time() + self._connect_timeout
        task = asyncio.create_task(awaitable)
        try:
            done, _ = await asyncio.wait({task}, timeout=self._connect_timeout)
            if not done:
                raise asyncio.TimeoutError("mesh connection setup timed out")
            result = task.result()
            if asyncio.get_running_loop().time() >= deadline:
                raise asyncio.TimeoutError("mesh connection setup timed out")
            return result
        except BaseException:
            if task.done():
                # Caller cancellation can coincide with a completed backend
                # failure. Observe it without replacing the caller's exception.
                if not task.cancelled():
                    task.exception()
                raise  # No late backend work remains; connect() closes below.
            task.cancel()

            async def finish_cleanup():
                try:
                    await task
                except BaseException:
                    pass  # Observe late backend errors; preserve caller error.
                await self.channel.close()

            cleanup = asyncio.create_task(finish_cleanup())
            self._setup_cleanup = cleanup
            cleanup.add_done_callback(_observe_task_result)
            raise

    async def connect(self) -> None:
        """Establish the BLE link and perform one explicit mesh login attempt."""
        requested_serial = self._disconnect_serial
        async with self._lock:
            if requested_serial != self._disconnect_serial:
                raise ConnectionLost("mesh connection attempt superseded by disconnect")
            if self._setup_cleanup is not None:
                if not self._setup_cleanup.done():
                    raise ConnectionLost(
                        "previous connection setup cleanup is still pending"
                    )
                if (
                    self._setup_cleanup.cancelled()
                    or self._setup_cleanup.exception() is not None
                ):
                    raise ConnectionLost("previous connection setup cleanup failed")
            if self.login_accepted:
                return
            connecting = asyncio.current_task()
            self._connecting_task = connecting
            self._session_key = None
            self._disconnect_seen = False
            try:
                # Only the transport/service-discovery phase needs caller-task
                # cancellation. Once GATT operations start, channel.invalidate()
                # supplies the established ConnectionLost error semantics.
                self._connect_setup_pending = True
                try:
                    await self._await_setup(self.channel.connect(self._on_disconnect))
                    services = await self._await_setup(
                        self.channel.transport.discover_services()
                    )
                finally:
                    self._connect_setup_pending = False
                present = services.get(SERVICE_UUID, frozenset())
                if not {PAIR_UUID, COMMAND_UUID, NOTIFY_UUID}.issubset(present):
                    raise MissingCharacteristic(
                        "modern mesh pair/command/notify characteristics not found"
                    )
                random = self._random_bytes(8)
                if not isinstance(random, (bytes, bytearray, memoryview)):
                    raise TypeError("random_bytes must return a bytes-like buffer")
                size = random.nbytes if isinstance(random, memoryview) else len(random)
                if size != 8:
                    raise ValueError("client_random must be 8 bytes")
                random = bytes(random)
                request = login_request(
                    self._credentials.name, self._credentials.password, random
                )
                await self.channel.execute(
                    GattOperation(OperationKind.WRITE, PAIR_UUID, request, True)
                )
                response = await self.channel.execute(
                    GattOperation(OperationKind.READ, PAIR_UUID)
                )
                key = derive_session_key(
                    self._credentials.name, self._credentials.password, random, response
                )
                if not self.channel.active or self._disconnect_seen:
                    raise ConnectionLost("BLE connection lost during pairing")
                self._session_key = key
                await self.channel.execute(
                    GattOperation(OperationKind.ENABLE_NOTIFY, NOTIFY_UUID),
                    self._receive,
                )
                await self.channel.execute(
                    GattOperation(OperationKind.WRITE, NOTIFY_UUID, b"\x01", True)
                )
                if not self.login_accepted:
                    raise ConnectionLost(
                        "connection lost during notification activation"
                    )
                self._ready = True
            except BaseException:
                self._session_key = None
                try:
                    await self.channel.close()
                except Exception:
                    pass
                raise
            finally:
                if self._connecting_task is connecting:
                    self._connecting_task = None

    def decode_received(self, packet: bytes) -> ExtendedNotification:
        """Decode one notification for this active mesh session in memory.

        Decryption is not an authenticity proof; the caller must validate the
        notification kind, layout and individual-device identity.
        """
        if not self.login_accepted:
            raise ConnectionLost("modern mesh session is not active")
        return decode_notification(self._session_key, packet)

    async def _write_command_packet(
        self, packet: bytes, *, before_write: Callable[[], None] | None = None
    ) -> None:
        """Write once under the caller's session lock; preserve hook/error semantics."""
        try:
            operation = GattOperation(OperationKind.WRITE, COMMAND_UUID, packet, True)
            await self.channel.execute(operation, before_write=before_write)
        except BaseException:
            # Local before_write failures leave the GATT channel intact.
            if not self.channel.active:
                self._on_disconnect()
            raise

    async def disconnect(self) -> None:
        # Invalidate the generation *before* waiting for the session lock.
        # An in-flight status/control write holds _lock while awaiting GATT.
        # Waiting for _lock before invalidation would leave shutdown blocked
        # until the 30-second GATT watchdog (or indefinitely in a bad backend).
        # Invalidating cancels the pending operation without replaying a write.
        """Close this connection and invalidate the current login state."""
        self._disconnect_serial += 1
        self._ready = False
        self._session_key = None
        self.channel.invalidate()
        connecting = self._connecting_task
        if (
            connecting is not None
            and connecting is not asyncio.current_task()
            and self._connect_setup_pending
        ):
            connecting.cancel()
        async with self._lock:
            await self.channel.close()
            # A successful explicit close supersedes a completed setup
            # cleanup failure. Never release a still-running or cancelled
            # cleanup, whose abandoned backend may not have finished.
            if (
                self._setup_cleanup is not None
                and self._setup_cleanup.done()
                and not self._setup_cleanup.cancelled()
            ):
                self._setup_cleanup = None

    async def __aenter__(self) -> "MeshConnection":
        await self.connect()
        return self

    async def __aexit__(self, *_args) -> None:
        await self.disconnect()

    @property
    def connected(self) -> bool:
        """Whether the Mesh login was accepted and the connection is usable."""
        return self._ready and self.login_accepted

    def _receive(self, packet: bytes) -> None:
        if self.login_accepted and self._on_notification is not None:
            try:
                notification = self.decode_received(packet)
            except ValueError:
                return
            self._on_notification(notification)

    async def send_frame(self, frame, *, before_write=None) -> None:
        """Encrypt at send time and perform one response=True GATT write."""
        generation = self.channel.generation
        async with self._lock:
            if not self.connected or generation != self.channel.generation:
                raise ConnectionLost("frame belongs to an inactive connection")
            await self._write_command_packet(
                frame.encrypt(self._session_key), before_write=before_write
            )

    async def _pair_operation(self, operation):
        """Keep Pair read/write failures consistent with normal frame writes."""
        try:
            return await self.channel.execute(operation)
        except BaseException:
            if not self.channel.active:
                self._on_disconnect()
            raise

    async def write_credentials(self, name, password) -> None:
        """Pair04/05 packets only; reading Pair07 is a separate operation."""
        from .authentication import network_update_packets, _padded_credential

        # Validate before accessing the connection; do not change active login.
        name, password = _padded_credential(name), _padded_credential(password)
        generation = self.channel.generation
        async with self._lock:
            if not self.connected or generation != self.channel.generation:
                raise ConnectionLost(
                    "credentials write belongs to an inactive connection"
                )
            for packet in network_update_packets(self._session_key, name, password):
                await self._pair_operation(
                    GattOperation(OperationKind.WRITE, PAIR_UUID, packet, True)
                )

    async def read_pair_response(self) -> bytes:
        """Read the actual Pair characteristic, with no follow-up writes."""
        generation = self.channel.generation
        async with self._lock:
            if not self.connected or generation != self.channel.generation:
                raise ConnectionLost("pair read belongs to an inactive connection")
            return await self._pair_operation(
                GattOperation(OperationKind.READ, PAIR_UUID)
            )
