"""Async transport boundary and serialized GATT operations, with no import-time I/O.

Queue semantics follow n7.d: one outstanding request, 30-second watchdog,
stale connection rejection, close on timeout. See documentation/ARCHITECTURE.md.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import IntEnum
from typing import Callable, Protocol

from .frames import SERVICE_UUID, PAIR_UUID, COMMAND_UUID
from ._validation import _valid_timeout

from .advertisements import AdvertisementRecord

CCCD_UUID = "00002902-0000-1000-8000-00805f9b34fb"


class CommunicationError(Exception):
    """Base error for unsuccessful local or remote communication."""
    status = -1


class ConnectionLost(CommunicationError):
    """Session/transport connection was lost or cannot be used."""
    pass


class GattOperationTimeout(CommunicationError):
    """A queued GATT operation exceeded its local deadline."""
    status = 257


class MissingCharacteristic(CommunicationError):
    """A required GATT characteristic is unavailable."""
    pass


class OperationKind(IntEnum):
    """Kinds of operations that the serialized GATT channel can execute."""
    WRITE = 0
    READ = 1
    ENABLE_NOTIFY = 2
    DISABLE_NOTIFY = 3
    MTU = 4


@dataclass(frozen=True)
class GattOperation:
    """A single queued GATT operation with its explicit parameters."""
    kind: OperationKind
    characteristic: str | None = None
    data: bytes = b""
    response: bool = True
    mtu: int = 23


NotificationCallback = Callable[[bytes], None]
DisconnectCallback = Callable[[int], None]


def _observe_task_result(task: asyncio.Task) -> None:
    """Retrieve a backend failure even if its caller has already timed out."""
    if not task.cancelled():
        task.exception()


def _read_bytes(value) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise TypeError("GATT read result must be bytes-like")
    return bytes(value)


def _notification_bytes(value) -> bytes | None:
    """Drop malformed event data; never fabricate bytes from a numeric value."""
    if not isinstance(value, (bytes, bytearray, memoryview)):
        return None
    try:
        return bytes(value)
    except (TypeError, ValueError):
        return None  # For example, a released memoryview has no readable data.


class GattTransport(Protocol):
    """Implementations resolve a single device; connect() includes no OS bonding."""

    async def connect(self, disconnected: DisconnectCallback) -> None:
        """Connect to the selected device and register a disconnect callback."""
        ...

    async def discover_services(self) -> dict[str, frozenset[str]]:
        """Return discovered service UUIDs and their characteristic UUIDs."""
        ...

    async def disconnect(self) -> None:
        """Disconnect the selected device, including any overlapping connect.

        On successful return the backend must have closed or invalidated the
        overlapping attempt so it cannot leave a physical link open.
        """
        ...

    async def read(self, characteristic: str) -> bytes:
        """Read bytes from the specified GATT characteristic."""
        ...

    async def write(self, characteristic: str, data: bytes, response: bool) -> None:
        """Write bytes using the selected GATT write response mode."""
        ...

    async def start_notify(
        self, characteristic: str, callback: NotificationCallback
    ) -> None:
        """Subscribe to notifications and forward received bytes to the callback."""
        ...

    async def stop_notify(self, characteristic: str) -> None:
        """Stop receiving notifications for the specified characteristic."""
        ...

    async def request_mtu(self, mtu: int) -> int:
        """Request an MTU and return the result if the backend supports it."""
        ...


class GattQueue:
    """Optional lock shared by channels when explicitly passed to each one.

    By default, each GattChannel creates its own queue. This class does not
    impose global serialization across independent sessions.
    """

    def __init__(self) -> None:
        self.lock = asyncio.Lock()


class GattChannel:
    """One stateful GATT channel with a per-channel or explicitly shared queue.

    Generation checks reject work from a replaced connection.
    """
    def __init__(
        self,
        transport: GattTransport,
        *,
        queue: GattQueue | None = None,
        operation_timeout: float = 30.0
    ) -> None:
        if not _valid_timeout(operation_timeout):
            raise ValueError("operation timeout must be positive")
        self.transport = transport
        self.queue = queue if queue is not None else GattQueue()
        self.operation_timeout = operation_timeout
        self.generation = 0
        self.active = False
        self._connecting_generation: int | None = None
        self._operation: asyncio.Task | None = None
        self._closing_task: asyncio.Task | None = None
        # Each notify registration has its own lifetime on this channel.
        # A still-queued callback must not survive stop/re-subscribe.
        self._notify_versions: dict[str, int] = {}

    def invalidate(self) -> None:
        """Invalidate the current channel generation and cancel its active operation."""
        self.generation += 1
        self.active = False
        if self._operation is not None:
            self._operation.cancel()

    async def connect(self, disconnected: DisconnectCallback) -> None:
        """Connect an inactive channel; reject duplicate attempts locally."""
        if not callable(disconnected):
            raise TypeError("disconnect callback must be callable")
        if self.active:
            raise ConnectionLost(
                "GATT channel is already connected; close it before reconnecting"
            )
        if self._connecting_generation is not None:
            raise ConnectionLost("GATT channel connection setup is already pending")
        if self._operation is not None and not self._operation.done():
            raise ConnectionLost(
                "previous GATT operation is still pending on this channel"
            )
        if self._closing_task is not None:
            if not self._closing_task.done():
                raise ConnectionLost("previous transport disconnect is still pending")
            if (
                self._closing_task.cancelled()
                or self._closing_task.exception() is not None
            ):
                raise ConnectionLost(
                    "previous transport disconnect did not complete successfully"
                )
        # Replacing a physical connection also cancels any WRITE/READ still
        # running on the previous one. Changing only the generation would
        # reject its result but could allow its backend I/O on the new link.
        self.invalidate()
        self._closing_task = None  # A new physical attempt needs its own cleanup.
        generation = self.generation
        self._connecting_generation = generation

        def on_disconnect(status=0):
            if generation == self.generation:
                self.invalidate()
                disconnected(status)

        try:
            await self.transport.connect(on_disconnect)
            if generation != self.generation:
                raise ConnectionLost("connection closed while connecting")
            self.active = True
        except BaseException:
            # Close/disconnect may already have invalidated this attempt.
            # Preserve that generation and clean up its late result below.
            if generation == self.generation:
                self.invalidate()
            raise
        finally:
            try:
                if generation != self.generation:
                    # A completed earlier disconnect cannot cover a late link.
                    # An ongoing disconnect is shared until it confirms closure.
                    if self._closing_task is not None and self._closing_task.done():
                        if (
                            not self._closing_task.cancelled()
                            and self._closing_task.exception() is None
                        ):
                            self._closing_task = None
                    try:
                        await self.close()
                    except Exception:
                        pass  # Preserve the connect error; retain failed cleanup.
            finally:
                self._connecting_generation = None

    async def close(self) -> None:
        """Invalidate immediately; bound cleanup without overlapping reconnect.

        A backend may ignore cancellation. Keep its task until it really ends,
        observe late failures, and refuse connect() until cleanup succeeds.
        The cleanup window is separate from an operation's watchdog window.
        A successful close is reused until another physical connect attempt;
        a late connect result requires cleanup after any earlier completed close.
        """
        self.invalidate()
        task = self._closing_task
        if task is None or (
            task.done() and (task.cancelled() or task.exception() is not None)
        ):
            task = asyncio.create_task(self.transport.disconnect())
            task.add_done_callback(_observe_task_result)
            self._closing_task = task
        # Cancelling one close() waiter must not cancel shared cleanup before
        # it even starts, or interrupt another close() waiting for the same task.
        done, _ = await asyncio.wait({task}, timeout=self.operation_timeout)
        if not done:
            task.cancel()
            raise asyncio.TimeoutError("transport disconnect exceeded cleanup timeout")
        if task.cancelled():
            raise ConnectionLost("transport disconnect was cancelled; outcome unknown")
        task.result()

    async def execute(
        self,
        operation: GattOperation,
        notification: NotificationCallback | None = None,
        *,
        before_write: Callable[[], None] | None = None
    ):
        # Reject malformed write hooks before entering the GATT queue. An
        # invalid caller callback must not be treated as a backend I/O failure
        # and must not close an otherwise healthy BLE connection.
        """Validate and execute one GATT operation under the shared queue."""
        if before_write is not None and not callable(before_write):
            raise TypeError("before_write callback must be callable")
        if not isinstance(operation, GattOperation):
            raise TypeError("operation must be GattOperation")
        # Local argument mistakes have not touched the radio and must not
        # later be mistaken for I/O failures that require disconnection.
        if type(operation.kind) is not OperationKind:
            raise ValueError("operation kind must be an OperationKind value")
        if operation.kind == OperationKind.MTU:
            if type(operation.mtu) is not int or not 23 <= operation.mtu <= 517:
                raise ValueError("MTU must be an integer in 23..517")
        else:
            if operation.characteristic is None:
                raise ValueError("characteristic is required")
            if (
                not isinstance(operation.characteristic, str)
                or not operation.characteristic
            ):
                raise ValueError("characteristic must be a nonempty UUID string")
        write_data = None
        if operation.kind == OperationKind.WRITE:
            if not isinstance(operation.data, (bytes, bytearray, memoryview)):
                raise TypeError("GATT write data must be bytes-like")
            if type(operation.response) is not bool:
                raise TypeError("GATT write response must be bool")
            write_data = bytes(operation.data)
        if operation.kind == OperationKind.ENABLE_NOTIFY:
            if notification is None:
                raise ValueError("notification callback is required")
            if not callable(notification):
                raise TypeError("notification callback must be callable")
        generation = self.generation
        async with self.queue.lock:
            if not self.active or generation != self.generation:
                raise ConnectionLost("GATT operation belongs to a closed connection")
            hook_failed = False
            hook_cancellation = None

            async def invoke():
                nonlocal hook_failed, hook_cancellation
                characteristic = operation.characteristic
                if operation.kind == OperationKind.MTU:
                    return await self.transport.request_mtu(operation.mtu)
                if operation.kind == OperationKind.READ:
                    return _read_bytes(await self.transport.read(characteristic))
                if operation.kind == OperationKind.WRITE:
                    # Activate an ACK waiter / timestamp only after both the
                    # controller lock and GATT queue have been acquired.
                    # There is no await between this marker and starting WRITE.
                    if before_write is not None:
                        try:
                            before_write()
                        except asyncio.CancelledError as error:
                            # Return normally from the worker: no BLE I/O
                            # began. Deliver this local cancellation in the
                            # caller, separately from cancellation of its wait.
                            hook_failed = True
                            hook_cancellation = error
                            return
                        except Exception:
                            hook_failed = True
                            raise
                    if not self.active or generation != self.generation:
                        raise ConnectionLost("connection changed before GATT write")
                    return await self.transport.write(
                        characteristic, write_data, operation.response
                    )
                if operation.kind == OperationKind.ENABLE_NOTIFY:
                    key = characteristic.lower()
                    version = self._notify_versions.get(key, 0) + 1
                    self._notify_versions[key] = version

                    def guarded(data):
                        if (
                            self.active
                            and generation == self.generation
                            and self._notify_versions.get(key) == version
                        ):
                            packet = _notification_bytes(data)
                            if packet is not None:
                                notification(packet)

                    return await self.transport.start_notify(characteristic, guarded)
                if operation.kind == OperationKind.DISABLE_NOTIFY:
                    key = characteristic.lower()
                    self._notify_versions[key] = self._notify_versions.get(key, 0) + 1
                    return await self.transport.stop_notify(characteristic)
                raise ValueError("unknown GATT operation")

            deadline = asyncio.get_running_loop().time() + self.operation_timeout
            task = asyncio.create_task(invoke())
            self._operation = task
            try:
                # wait() does not propagate child cancellation as cancellation
                # of this caller. This distinguishes an invalidated connection
                # from explicit caller cancellation, including simultaneous ones,
                # without relying on Task.cancelling() (Python >=3.11).
                done, _ = await asyncio.wait({task}, timeout=self.operation_timeout)
                if not done:
                    raise asyncio.TimeoutError()
                if task.cancelled():
                    raise ConnectionLost("connection invalidated during GATT operation")
                result = task.result()
                if (
                    hook_cancellation is None
                    and asyncio.get_running_loop().time() >= deadline
                ):
                    raise asyncio.TimeoutError()
                if not self.active or generation != self.generation:
                    raise ConnectionLost(
                        "connection changed before operation completed"
                    )
                if hook_cancellation is None:
                    return result
            except asyncio.TimeoutError as error:
                if hook_failed:
                    raise  # Local preparation failed before any Bluetooth I/O.
                if generation == self.generation:
                    try:
                        await self.close()
                    except Exception:
                        pass  # preserve the watchdog error even when cleanup fails
                raise GattOperationTimeout(
                    "GATT watchdog invalidated stalled channel"
                ) from error
            except asyncio.CancelledError:
                # Cancelled callers also invalidate in-flight work: a later BLE
                # completion must not be accepted as a subsequent request's reply.
                if self.active and generation == self.generation:
                    try:
                        await self.close()
                    except Exception:
                        pass
                raise
            except Exception as error:
                # A disconnect may invalidate this task before its waiter runs.
                # Never let cleanup of that old task close a new connection.
                # Only the portable MTU request is known to be unsupported
                # without touching GATT. Other backend failures still close.
                if (
                    generation == self.generation
                    and not hook_failed
                    and not (
                        operation.kind == OperationKind.MTU
                        and isinstance(error, NotImplementedError)
                    )
                ):
                    try:
                        await self.close()
                    except Exception:
                        pass  # preserve the original backend failure
                raise
            finally:
                # Cancellation can finish later and itself raise a backend
                # error. Observe that result without extending the deadline.
                def observe_completion(finished):
                    _observe_task_result(finished)
                    if self._operation is finished:
                        self._operation = None

                task.add_done_callback(observe_completion)
            if hook_cancellation is not None:
                # Outside the caller-cancellation handler, which must still
                # invalidate genuinely interrupted GATT work.
                raise hook_cancellation


@dataclass(frozen=True)
class DiscoveredDevice:
    """A scanned device address with optional advertisement metadata."""
    device: object
    address: str
    rssi: int
    advertisement: AdvertisementRecord
