"""Explicit AwoX mesh operations through one connection with an accepted Mesh login.

The session never chooses a gateway, retries a command or inserts a send delay.
Explicit single-step operations leave continuation to the caller. Optional
high-level schedule and provisioning methods reproduce the documented APK
workflow when invoked; Receipt tracks only a bounded response window.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Awaitable, Callable, Mapping, TypeVar

from ._validation import _valid_timeout, _valid_mesh_destination
from .authentication import Credentials
from .connection import MeshConnection
from .frames import ExtendedCommand, ExtendedNotification, control
from . import lighting, groups, power_cut, schedule, presence, pir, provisioning, clock
from .status import (
    StatusStore, LampStatus, MeshStatusFrame,
    parse_status_variant, status_query,
)
from .transport import GattTransport, ConnectionLost, _observe_task_result
from .targets import Lamp, MeshTarget

_LOG = logging.getLogger(__name__)

_ReplyT = TypeVar("_ReplyT")


class _ScheduleDeadlineExpired(Exception):
    """A queued schedule operation expired before its GATT write started."""


@dataclass
class _ProvisioningAttempt:
    session: AwoXMeshSession
    connection: MeshConnection
    mesh_id: int | None = None


# Delegated tasks inherit the connection for their own provisioning attempt.
_provision_scope: ContextVar[_ProvisioningAttempt | None] = ContextVar(
    "_provision_scope", default=None
)


class Receipt:
    """A local observation window, not an on-air transaction identifier.

    Created before the actual write; retained until consumed, disconnected or
    expired. wait() never resends and never extends the original deadline.
    The result is the decoded notification, not proof of physical execution.
    """

    def __init__(
        self, session: AwoXMeshSession, opcode: int, target: int | None,
        routine: int | None, timeout: float, factory: bool = False,
        accept: Callable[[ExtendedNotification], bool] | None = None,
        *, lamp_status: bool = False,
    ) -> None:
        self._session = session
        self._opcode, self._target, self._routine = opcode, target, routine
        self._factory = factory
        self._timeout = timeout
        self._future = asyncio.get_running_loop().create_future()
        self._future.add_done_callback(
            lambda f: None if f.cancelled() else f.exception()
        )
        self._deadline = None
        self._timer = None
        self._invalidated = False
        self._accept = accept
        self._lamp_status = lamp_status
        self._received_at: float | None = None

    def _written(self):
        """Start the local reply deadline after the GATT write finishes."""
        self._deadline = asyncio.get_running_loop().time() + self._timeout
        self._timer = asyncio.get_running_loop().call_at(self._deadline, self._expire)

    def _expire(self):
        """Complete an unanswered local reply window with None and release it."""
        if not self._future.done():
            self._future.set_result(None)
        self._release()

    def _release(self):
        """Discard the local response window and cancel its timer."""
        self._session._receipts.discard(self)
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _matches(self, n: ExtendedNotification, raw_status: MeshStatusFrame | None) -> bool:
        """Match one notification, using the already matched raw status if present."""
        if n.opcode != self._opcode and not (self._opcode == 0x80 and n.opcode == 0x82):
            return False
        # Lamp reads validate the transmitted MAC tail in their own filter.
        if n.opcode in (0x80, 0x82) and raw_status is None and not self._lamp_status:
            return False
        if self._target is not None:
            address = int.from_bytes(n.payload[:2], "little")
            # A directly connected factory device at ID 0 can reply as FFFF.
            if address != self._target and not (
                self._factory
                and self._target == 0
                and n.opcode == 0x0C
                and address == 0xFFFF
            ):
                return False
        if self._routine is not None:
            # Read errors use FF, error, routine instead of the normal routine byte.
            is_read = n.opcode in (0x35, 0x3C)
            read_error = is_read and len(n.payload) > 2 and n.payload[2] == 0xFF
            offset = 2 if is_read and not read_error else 4
            if len(n.payload) <= offset:
                return False
            routine = (
                n.payload[offset] & 0x7F
                if is_read and not read_error
                else n.payload[offset]
            )
            if routine != self._routine:
                return False
        return True

    def _overlaps(self, other: Receipt) -> bool:
        """Whether one wire reply could satisfy both local selectors.

        0x80 also accepts 0x82. None is a wildcard for target/routine;
        the factory 0/FFFF exception overlaps an ordinary FFFF selector.
        This conservatively reserves ambiguous windows, never inventing a
        request ID missing from the wire protocol.
        """
        mine = {self._opcode, 0x82} if self._opcode == 0x80 else {self._opcode}
        theirs = {other._opcode, 0x82} if other._opcode == 0x80 else {other._opcode}
        if not mine.intersection(theirs):
            return False
        mine_targets = ({0, 0xFFFF} if self._factory else
                        {self._target} if self._target is not None else None)
        their_targets = ({0, 0xFFFF} if other._factory else
                         {other._target} if other._target is not None else None)
        if (mine_targets is not None and their_targets is not None
                and mine_targets.isdisjoint(their_targets)):
            return False
        return (self._routine is None or other._routine is None
                or self._routine == other._routine)

    async def wait(self, *, timeout: float | None = None) -> ExtendedNotification | None:
        """Return the captured notification or None within the remaining window.

        Use one waiter per receipt. A timeout or cancellation of an active
        wait ends response tracking for the receipt.
        """
        if timeout is not None and not _valid_timeout(timeout):
            raise ValueError("timeout must be positive and finite")
        if self._invalidated:
            raise ConnectionLost("receipt belongs to a closed connection")
        if self._deadline is None:
            raise RuntimeError("receipt is not ready until the write completes")
        now = asyncio.get_running_loop().time()
        deadline = self._deadline if timeout is None else min(self._deadline, now + timeout)
        remaining = deadline - now
        if remaining <= 0:
            self._expire()
            return None
        try:
            done, _ = await asyncio.wait({self._future}, timeout=remaining)
            if self._invalidated:
                raise ConnectionLost("receipt belongs to a closed connection")
            if not done:
                return None
            # A notification can run before an already-due wait timer.
            if self._received_at is not None and self._received_at >= deadline:
                return None
            return self._future.result()
        finally:
            self._release()


def _validate_zone(zone: int) -> None:
    if type(zone) is not int or zone not in (0, 1):
        raise ValueError("zone must be 0 or 1")


class AwoXMeshSession:
    """Explicit gateway session; construction has no I/O.

    devices maps known individual mesh IDs to MAC addresses for conservative
    status identity checks. It is optional for factory/provisioning operations.
    device_models optionally maps those IDs to APK model names for status
    layouts that do not identify the model.
    """

    def __init__(
        self,
        transport_factory: Callable[[], GattTransport | Awaitable[GattTransport]],
        credentials: Credentials,
        devices: Mapping[int, str] | None = None,
        *,
        device_models: Mapping[int, str] | None = None,
        on_status: Callable[[LampStatus], None] | None = None,
        on_mesh_status: Callable[[MeshStatusFrame], None] | None = None,
        on_notification: Callable[[ExtendedNotification], None] | None = None,
        on_disconnect: Callable[[], None] | None = None,
        status_max_age: float | None = None,
    ) -> None:
        if not callable(transport_factory):
            raise TypeError("transport_factory must be callable")
        if not isinstance(credentials, Credentials):
            raise TypeError("credentials must be Credentials")
        if status_max_age is not None and not _valid_timeout(status_max_age):
            raise ValueError("status_max_age must be positive and finite or None")
        for cb in (on_status, on_mesh_status, on_notification, on_disconnect):
            if cb is not None and not callable(cb):
                raise TypeError("callbacks must be callable or None")
        self._transport_factory, self._credentials = transport_factory, credentials
        self._devices = dict(devices or {})
        self._statuses = StatusStore(self._devices, device_models=device_models)
        self._mesh_statuses = {}
        self._secondary_zone_statuses: dict[int, LampStatus] = {}
        self._on_status, self._on_mesh_status = on_status, on_mesh_status
        self._on_notification, self._on_disconnect = on_notification, on_disconnect
        self._status_max_age = status_max_age
        self._connection = None
        self._cleanup_task = self._cleanup_owner = None
        self._ready = False
        self._lifecycle_lock = asyncio.Lock()
        self._connecting_task = None
        self._disconnect_serial = 0
        self._receipts: set[Receipt] = set()
        # Convenience operations with the same wire response identity must
        # serialize. Explicit send_and_track_reply() remains conflict-strict.
        self._reply_locks: dict[tuple[int, int | None, int | None], asyncio.Lock] = {}
        self._schedule_locks: dict[int, asyncio.Lock] = {}
        self._time29_lock = asyncio.Lock()
        self._provision_lock = asyncio.Lock()
        self._provision_attempt: _ProvisioningAttempt | None = None
        self.notifications_received = self.notifications_rejected = (
            self.callback_errors
        ) = 0
        self.last_quiet_result_code = self.last_dual_zone_result_code = None

    @property
    def connected(self) -> bool:
        """Whether the current session connection is available."""
        return (
            self._ready and self._connection is not None and self._connection.connected
        )

    def _clear_observations(self):
        self._statuses.clear()
        self._mesh_statuses.clear()
        self._secondary_zone_statuses.clear()
        self.last_quiet_result_code = self.last_dual_zone_result_code = None
        for receipt in tuple(self._receipts):
            receipt._invalidated = True
            if not receipt._future.done():
                receipt._future.set_exception(
                    ConnectionLost("connection closed during response window")
                )
            receipt._release()

    def _callback(self, callback, *args):
        if callback is not None:
            # Application callbacks can start independent operations on a new link.
            scope = _provision_scope.get()
            token = _provision_scope.set(None) if scope is not None and scope.session is self else None
            try:
                callback(*args)
            except (Exception, asyncio.CancelledError):
                self.callback_errors += 1
                _LOG.exception("AwoX callback failed")
            finally:
                if token is not None:
                    _provision_scope.reset(token)

    def _connection_lost(self):
        self._ready = False
        self._clear_observations()
        self._callback(self._on_disconnect)

    def _receive(self, notification: ExtendedNotification) -> None:
        self.notifications_received += 1
        try:
            received_at = asyncio.get_running_loop().time()
            is_status = notification.opcode in (0x80, 0x82)
            raw_status = parse_status_variant(notification, received_at=received_at) if is_status else None
            if raw_status is not None and not self._statuses._matches_identity(raw_status):
                raw_status = None
            for receipt in tuple(self._receipts):
                if receipt._future.done():
                    continue
                if receipt._deadline is not None and received_at >= receipt._deadline:
                    # Timer callbacks can be delayed by a busy event loop.
                    receipt._expire()
                    continue
                if not receipt._matches(notification, raw_status):
                    continue
                if receipt._accept is not None:
                    try:
                        if not receipt._accept(notification):
                            continue
                    except (ValueError, TypeError, IndexError):
                        # An addressed but malformed reply must not consume
                        # the waiting request. A later valid reply may arrive.
                        self.notifications_rejected += 1
                        continue
                receipt._received_at = received_at
                receipt._future.set_result(notification)
                # Local replies have no transaction IDs. Never let one
                # notification complete two simultaneously armed receipts.
                break
            if is_status:
                if raw_status is not None:
                    self._mesh_statuses[(raw_status.mesh_id, raw_status.zone_raw)] = raw_status
                    self._callback(self._on_mesh_status, raw_status)
                    state = self._statuses._lamp_view(raw_status, include_secondary=True)
                    if state is not None:
                        if state.zone == 1:
                            self._secondary_zone_statuses[state.mesh_id] = state
                        else:
                            self._statuses._observe_lamp(state)
                        self._callback(self._on_status, state)
            elif notification.opcode == 0x0B and len(notification.payload) >= 2:
                attempt = self._provision_attempt
                if attempt is not None and self._connection is attempt.connection:
                    attempt.mesh_id = int.from_bytes(notification.payload[:2], "little")
            elif notification.opcode == 0x40:
                value = notification.payload[5]
                self.last_quiet_result_code = value if value < 128 else value - 256
            elif notification.opcode == 0x52:
                value = notification.payload[0]
                self.last_dual_zone_result_code = value if value < 128 else value - 256
            self._callback(self._on_notification, notification)
        except (ValueError, TypeError, IndexError):
            self.notifications_rejected += 1

    @property
    def states(self) -> dict[int, LampStatus]:
        """Cached, age-filtered lamp states for the connected session."""
        if not self.connected:
            return {}
        return {k: v for k, v in self._statuses.states.items() if self._fresh(v)}

    @property
    def mesh_states(self) -> dict[tuple[int, int], MeshStatusFrame]:
        """Raw mesh status keyed by (mesh_id, zone_raw), independent of the lamp cache."""
        if not self.connected:
            return {}
        return {k: v for k, v in self._mesh_statuses.items() if self._fresh(v)}

    def _fresh(self, status):
        return (
            self._status_max_age is None
            or time.monotonic() - status.received_monotonic <= self._status_max_age
        )

    def get_status(self, mesh_id: int, zone: int | None = None) -> LampStatus | None:
        """Return a cached lamp status while connected, subject to the age filter.

        Omit zone for the main status, or select zone 0 or 1 for a Dual Zone lamp.
        Use read_status() for an active query.
        """
        if type(mesh_id) is not int:
            raise TypeError("mesh_id must be an integer")
        if zone is not None:
            _validate_zone(zone)
        if not self.connected:
            return None
        if zone == 1:
            status = self._secondary_zone_statuses.get(mesh_id)
        else:
            status = self._statuses.get(mesh_id)
        if status is None or (zone == 0 and status.zone != 0) or not self._fresh(status):
            return None
        return status

    def lamp(self, mesh_id: int) -> Lamp:
        """Return a target for an individually registered mesh ID.

        This does not create a second BLE connection.
        """
        if type(mesh_id) is not int or mesh_id not in self._devices:
            raise ValueError("mesh_id must identify a registered individual device")
        return Lamp(self, mesh_id)

    def group(self, destination: int) -> MeshTarget:
        """Explicit non-lamp target; address classification is caller-owned.

        The APK sets the control group flag only for 0x80xx addresses.
        This method neither normalizes nor validates group membership.
        """
        if type(destination) is not int or not 1 <= destination <= 0xFFFE:
            raise ValueError(
                "group destination must be 1..FFFE; use broadcast() for FFFF"
            )
        return MeshTarget(self, destination)

    def broadcast(self) -> MeshTarget:
        """Explicit FFFF write target; never aggregates received status."""
        return MeshTarget(self, 0xFFFF)

    def _current(self) -> MeshConnection:
        if not self.connected:
            raise ConnectionLost("session must be connected")
        scope = _provision_scope.get()
        if scope is not None and scope.session is self and scope.connection is not self._connection:
            raise ConnectionLost("provisioning belongs to a replaced connection")
        return self._connection

    async def send(self, frame: ExtendedCommand) -> None:
        """Send one caller-built frame without waiting for a device response."""
        if not isinstance(frame, ExtendedCommand):
            raise TypeError("frame must be a Frame/ExtendedCommand")
        await self._current().send_frame(frame)

    async def send_and_track_reply(
        self, frame: ExtendedCommand, opcode: int, *, target: int | None = None,
        routine: int | None = None, timeout: float = 15.0,
        factory: bool = False,
        _accept: Callable[[ExtendedNotification], bool] | None = None,
        _deadline: float | None = None,
        _lamp_status: bool = False,
    ) -> Receipt:
        """Send once and retain a bounded response window without awaiting it.

        target is the response address, not necessarily a command destination.
        factory=True only permits the proven ID0/FFFF group-write ACK case.
        Do not overlap indistinguishable requests: local receipts are not wire IDs.
        """
        if not isinstance(frame, ExtendedCommand):
            raise TypeError("frame must be a Frame/ExtendedCommand")
        if type(opcode) is not int or not 0 <= opcode <= 255:
            raise ValueError("opcode must be a byte")
        if target is not None and (
            type(target) is not int or not 0 <= target <= 0xFFFF
        ):
            raise ValueError("target must be a 16-bit address or None")
        if routine is not None and (
            type(routine) is not int or not 0 <= routine <= 255
        ):
            raise ValueError("routine must be a byte or None")
        if not _valid_timeout(timeout):
            raise ValueError("timeout must be positive and finite")
        if type(factory) is not bool or (factory and (opcode != 0x0C or target != 0)):
            raise ValueError(
                "factory exception is restricted to opcode 0x0C and target 0"
            )
        if _accept is not None and not callable(_accept):
            raise TypeError("_accept must be callable or None")
        connection = self._current()
        receipt = Receipt(
            self, opcode, target, routine, timeout, factory, _accept, lamp_status=_lamp_status
        )

        def arm():
            if self._connection is not connection:
                raise ConnectionLost("response window belongs to a replaced connection")
            if _deadline is not None and asyncio.get_running_loop().time() >= _deadline:
                raise _ScheduleDeadlineExpired
            for pending in self._receipts:
                if not pending._future.done() and pending._overlaps(receipt):
                    raise RuntimeError(
                        "an overlapping response operation is already pending"
                    )
            self._receipts.add(receipt)

        try:
            await connection.send_frame(frame, before_write=arm)
            receipt._written()
            return receipt
        except BaseException:
            receipt._release()
            raise

    def _reply_lock(
        self, opcode: int, target: int | None = None, routine: int | None = None
    ) -> asyncio.Lock:
        """Serialize convenience requests sharing the same response selector."""
        return self._reply_locks.setdefault((opcode, target, routine), asyncio.Lock())

    def _require_same_connection(self, owner: MeshConnection) -> None:
        if self._current() is not owner:
            raise ConnectionLost("queued operation belongs to a replaced connection")

    async def _read(
        self, frame: ExtendedCommand, opcode: int,
        decoder: Callable[[bytes], _ReplyT], *, target: int | None = None,
        routine: int | None = None, timeout: float = 15.0,
        _deadline: float | None = None,
        _on_written: Callable[[], None] | None = None,
        _owner: MeshConnection | None = None,
    ) -> _ReplyT | None:
        """Validate before consuming a reply, serialize only convenience calls.

        A global deadline (schedule operations) includes the GATT write itself;
        an answer captured during a slow write counts only if it arrived in time.
        Raw send_and_track_reply() intentionally keeps its collision policy.
        """
        if _deadline is None and not _valid_timeout(timeout):
            raise ValueError("timeout must be positive and finite")
        owner = self._current() if _owner is None else _owner
        async with self._reply_lock(opcode, target, routine):
            self._require_same_connection(owner)
            loop = asyncio.get_running_loop()
            if _deadline is not None:
                timeout = _deadline - loop.time()
                if timeout <= 0:
                    return None
            decoded: list[_ReplyT] = []

            def accept(notification: ExtendedNotification) -> bool:
                value = decoder(bytes((notification.opcode,)) + notification.payload)
                decoded[:] = [value]
                return True

            try:
                receipt = await self.send_and_track_reply(
                    frame, opcode, target=target, routine=routine,
                    timeout=timeout, _accept=accept, _deadline=_deadline,
                )
            except _ScheduleDeadlineExpired:
                return None
            if _on_written is not None:
                _on_written()
            if _deadline is not None:
                remaining = _deadline - loop.time()
                if remaining <= 0:
                    # A synchronous notification may arrive inside the GATT
                    # write. Preserve it only when it preceded the deadline.
                    timely = (
                        receipt._received_at is not None
                        and receipt._received_at < _deadline
                        and receipt._future.done()
                        and not receipt._future.cancelled()
                    )
                    try:
                        if timely:
                            receipt._future.result()  # propagate disconnect
                            return decoded[0]
                        return None
                    finally:
                        receipt._expire()
                notification = await receipt.wait(timeout=remaining)
                # The wait timer may run after the receive handler.
                if receipt._received_at is not None and receipt._received_at >= _deadline:
                    return None
            else:
                notification = await receipt.wait()
            return decoded[0] if notification is not None else None

    async def request_status(self, destination: int) -> None:
        """Write ONE 0x0A status request to an explicit mesh destination.

        Accepts lamp and group addresses or 0xFFFF for broadcast. This only
        confirms the GATT write; receive status notifications independently
        via ``get_status(mesh_id)`` or ``states``. There is no response wait,
        automatic retry or command replay after reconnect.
        """
        await self.send(status_query(destination))

    async def read_status(self, mesh_id: int, *, timeout: float = 15.0) -> LampStatus | None:
        """Send one addressed 0x0A request and wait for a new status observation.

        Returns LampStatus or None after timeout. Matching is based on
        the mesh ID and receive time, because status notifications have no
        request transaction ID. The passive cache age filter does not apply
        to a response received since this request. No retries or background queries.
        """
        if type(mesh_id) is not int or mesh_id not in self._devices:
            raise ValueError("status read requires a registered individual device")
        observed = None

        def accept_lamp_status(notification: ExtendedNotification) -> bool:
            nonlocal observed
            observed = self._statuses._match(notification)
            return observed is not None

        if not _valid_timeout(timeout):
            raise ValueError("timeout must be positive and finite")
        owner = self._current()
        async with self._reply_lock(0x80, mesh_id):
            self._require_same_connection(owner)
            receipt = await self.send_and_track_reply(
                status_query(mesh_id), 0x80, target=mesh_id, timeout=timeout,
                _accept=accept_lamp_status, _lamp_status=True,
            )
            return observed if await receipt.wait() is not None else None

    async def _write_control_destination(self, destination, command_le, payload):
        """Send a single control command to the explicitly supplied destination."""
        if not _valid_mesh_destination(destination):
            raise ValueError("destination must be a nonzero 16-bit address")
        await self.send(control(destination, command_le, payload))

    async def read_mesh_groups(self, destination: int, *, timeout: float = 15.0) -> groups.MeshGroupMembership | None:
        """Read the full current membership list, never replay across reconnects."""
        return await self._read(
            groups.get_mesh_groups(destination),
            0x08,
            groups.parse_mesh_groups_get,
            target=destination,
            timeout=timeout,
        )

    async def write_mesh_groups(self, destination: int, addresses: list[int] | tuple[int, ...]) -> None:
        """Replace group list once, without an acknowledgement wait."""
        await self.send(groups.set_mesh_groups(destination, addresses))

    async def set_mesh_groups(
        self, destination: int, addresses: list[int] | tuple[int, ...], *, timeout: float = 5.0
    ) -> groups.MeshGroupSetResponse | None:
        """Replace memberships and return the addressed 0x0C ACK, if observed."""
        return await self._read(
            groups.set_mesh_groups(destination, addresses),
            0x0C,
            groups.parse_mesh_groups_set_result,
            target=destination,
            timeout=timeout,
        )

    async def read_power_cut_mode(self, destination: int, *, timeout: float = 15.0) -> power_cut.PowerCutConfiguration | None:
        """Read a stored configuration on this *current* mesh connection.

        Never replay across reconnects. No response means None. The 0x43
        address field is checked, but is not authenticated device provenance.
        """
        return await self._read(
            power_cut.power_cut_get_mode(destination),
            0x43,
            power_cut.parse_power_cut_get_mode,
            target=destination,
            timeout=timeout,
        )

    async def write_power_cut_mode(self, destination: int, mode: str, scene: bytes | None = None) -> None:
        """Write one 0x42 mode without an ACK wait."""
        await self.send(power_cut.power_cut_set_mode(destination, mode, scene))

    async def set_power_cut_mode(
        self, destination: int, mode: str, scene: bytes | None = None, *, timeout: float = 5.0
    ) -> power_cut.PowerCutSetResponse | None:
        """Write 0x42 and return the decoded matching ACK, if observed."""
        return await self._read(
            power_cut.power_cut_set_mode(destination, mode, scene),
            0x42, power_cut.parse_power_cut_set, target=destination, timeout=timeout,
        )

    async def read_schedule_part(self, destination: int, routine_id: int, *, timeout: float = 15.0) -> schedule.SchedulePart | None:
        """Request one specified 0x35 routine and decode its response, if received."""
        return await self._read(
            schedule.schedule_get(destination, routine_id),
            0x35,
            schedule.parse_schedule_read,
            target=destination,
            routine=routine_id,
            timeout=timeout,
        )

    async def set_schedule_part(self, destination: int, part: schedule.ScheduleWritePart) -> None:
        """One raw 0x33 schedule write; the caller owns any follow-up."""
        await self.send(schedule.schedule_set(destination, part))

    def _schedule_lock(self, destination: int) -> asyncio.Lock:
        """Serialize high-level schedule operations for one destination."""
        return self._schedule_locks.setdefault(destination, asyncio.Lock())

    async def _read_schedule(
        self, destination: int, property_name: str, *, timeout: float = 15.0
    ) -> schedule.ScheduleRead | None:
        """Return a timer/program read or the APK's conditional 5/6, 7/8 pair.

        Paired reads share one total timeout; an error in the first part does
        not trigger the second request. No device state is changed.
        """
        if property_name not in schedule.SCHEDULE_SINGLE_READS and property_name not in schedule.SCHEDULE_PAIRS:
            raise ValueError("unknown schedule property")
        if not _valid_timeout(timeout):
            raise ValueError("timeout must be positive and finite")
        owner = self._current()
        async with self._schedule_lock(destination):
            self._require_same_connection(owner)
            deadline = asyncio.get_running_loop().time() + timeout

            async def one(routine_id):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return None
                return await self._read(
                    schedule.schedule_get(destination, routine_id),
                    0x35, schedule.parse_schedule_read,
                    target=destination, routine=routine_id,
                    timeout=remaining, _deadline=deadline, _owner=owner,
                )

            if property_name in schedule.SCHEDULE_SINGLE_READS:
                part = await one(schedule.SCHEDULE_SINGLE_READS[property_name])
                return (schedule.ScheduleRead(destination, property_name, part, None)
                        if part is not None else None)
            start_id, end_id = schedule.SCHEDULE_PAIRS[property_name]
            first = await one(start_id)
            if first is None:
                return None
            end = await one(end_id) if first.valid else None
            return schedule.ScheduleRead(destination, property_name, first, end)

    async def _set_schedule(
        self, destination: int, property_name: str, start,
        end=None, *, timeout: float = 15.0,
    ) -> schedule.ScheduleWriteResult:
        """Schedule write result: ACK 0x33; paired writes only on 0x99.

        Outgoing 5/7 and 6/8 parts use APK 0x10/0x11 markers. Neither
        GATT success nor a positive ACK proves that persistent settings work.
        """
        if property_name not in schedule.SCHEDULE_SINGLE_READS and property_name not in schedule.SCHEDULE_PAIRS:
            raise ValueError("unknown schedule property")
        if type(start) is not schedule.ScheduleWritePart:
            raise TypeError("start must be ScheduleWritePart")
        if not _valid_timeout(timeout, maximum=120):
            raise ValueError("timeout must be positive and at most 120 seconds")
        paired = property_name in schedule.SCHEDULE_PAIRS
        if paired:
            if type(end) is not schedule.ScheduleWritePart:
                raise TypeError("end must be ScheduleWritePart")
            if (start.routine_id, end.routine_id) != schedule.SCHEDULE_PAIRS[property_name]:
                raise ValueError("start/end routine IDs do not match property")
            start = schedule.ScheduleWritePart(start.settings[:9] + b"\x10")
            end = schedule.ScheduleWritePart(end.settings[:9] + b"\x11")
        elif start.routine_id != schedule.SCHEDULE_SINGLE_READS[property_name] or end is not None:
            raise ValueError("single schedule requires its routine and no end")
        owner = self._current()
        async with self._schedule_lock(destination):
            self._require_same_connection(owner)
            deadline = asyncio.get_running_loop().time() + timeout

            async def one(part, *, on_written=None):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return None
                return await self._read(
                    schedule.schedule_set(destination, part), 0x33,
                    schedule.parse_schedule_set, target=destination,
                    routine=part.routine_id, timeout=remaining,
                    _deadline=deadline, _on_written=on_written, _owner=owner,
                )

            first = await one(start)
            end_sent = False
            second = None

            def mark_end_sent():
                nonlocal end_sent
                end_sent = True

            if (paired and first is not None and first.requires_followup
                    and asyncio.get_running_loop().time() < deadline):
                second = await one(end, on_written=mark_end_sent)
            return schedule.ScheduleWriteResult(
                destination, property_name, first, second, end_sent
            )

    async def read_timer(self, destination: int, *, timeout: float = 15.0) -> schedule.ScheduleRead | None:
        """Read-only APK countdown timer (0x35, routine 2), once.

        Returns a single-part ScheduleRead, or None if no matching
        notification arrives. No schedule writes, retries or clock sync.
        """
        return await self._read_schedule(destination, "timer", timeout=timeout)

    async def read_program(self, destination: int, *, timeout: float = 15.0) -> schedule.ScheduleRead | None:
        """Read-only APK time program (0x35, routine 3), once.

        Returns one ScheduleRead, or None if no matched reply. A valid
        reply does not prove that every stored program slot was read.
        This does not create, activate, edit or synchronise a program.
        """
        return await self._read_schedule(destination, "program", timeout=timeout)

    async def read_nightlight(self, destination: int, *, timeout: float = 15.0) -> schedule.ScheduleRead | None:
        """Read-only APK 0x35 routines 5 and (if valid first reply) 6."""
        return await self._read_schedule(destination, "nightlight", timeout=timeout)

    async def read_dawn_simulator(self, destination: int, *, timeout: float = 15.0) -> schedule.ScheduleRead | None:
        """Read-only APK 0x35 routines 7 and (if valid first reply) 8."""
        return await self._read_schedule(destination, "dawn_simulator", timeout=timeout)

    async def set_timer(self, destination: int, settings: schedule.ScheduleWritePart, *, timeout: float = 15.0) -> schedule.ScheduleWriteResult:
        """Write exactly one APK 0x33 timer routine 2; possible persistent change.

        settings is a ScheduleWritePart (typically from a valid read).
        No automatic timer activation, backup, readback, retry or rollback.
        A positive 0x00 ACK does not prove persistence; check read_timer().
        """
        return await self._set_schedule(destination, "timer", settings, timeout=timeout)

    async def set_program(self, destination: int, settings: schedule.ScheduleWritePart, *, timeout: float = 15.0) -> schedule.ScheduleWriteResult:
        """Write exactly one APK 0x33 program routine 3, no hidden automation.

        settings must be a ScheduleWritePart (for example from a
        valid read_program result). A positive 0x00 ACK is not proof of
        persistence or execution. No retry, backup, readback, time sync,
        or automatic rollback is performed by the library.
        """
        return await self._set_schedule(destination, "program", settings, timeout=timeout)

    async def set_nightlight(self, destination: int, start: schedule.ScheduleWritePart, end: schedule.ScheduleWritePart, *, timeout: float = 15.0) -> schedule.ScheduleWriteResult:
        """Write APK routines 5/6; ONLY continue on the device's 0x99 reply.

        This is a persistent device change. No automatic backup/readback,
        time sync, retry, rollback, or claim of final execution.
        """
        return await self._set_schedule(destination, "nightlight", start, end, timeout=timeout)

    async def set_dawn_simulator(self, destination: int, start: schedule.ScheduleWritePart, end: schedule.ScheduleWritePart, *, timeout: float = 15.0) -> schedule.ScheduleWriteResult:
        """Write APK routines 7/8; MAY change persistent lamp automation."""
        return await self._set_schedule(destination, "dawn_simulator", start, end, timeout=timeout)

    async def read_presence_simulator(self, destination: int, *, timeout: float = 15.0) -> presence.PresenceRead | None:
        """Read-only APK 0x3C presence simulator, routine 1, once.

        Returns PresenceRead, or None when no matching reply arrives.
        No activation, scheduling, retries or clock synchronization.
        """
        return await self._read(
            presence.presence_get(destination),
            0x3C,
            presence.parse_presence_read,
            target=destination,
            routine=1,
            timeout=timeout,
        )

    async def write_presence_simulator(self, destination: int, settings: presence.PresenceWritePart) -> None:
        """Send one 0x3B presence configuration without awaiting a device ACK."""
        await self.send(presence.presence_set(destination, settings))

    async def set_presence_simulator(
        self, destination: int, settings: presence.PresenceWritePart, *, timeout: float = 15.0
    ) -> presence.PresenceSetResponse | None:
        """One original 0x3B configuration write; no automatic recovery.

        settings is PresenceWritePart, usually derived from an explicit
        read. A positive 0x00 ACK is not proof of stored values/execution.
        This call does not toggle, retry, read back or restore automatically.
        """
        return await self._read(
            presence.presence_set(destination, settings), 0x3B,
            presence.parse_presence_set, target=destination, routine=1,
            timeout=timeout,
        )

    async def read_pir_settings(self, destination: int, *, timeout: float = 15.0) -> pir.PirSettings | None:
        """0x12 addressed query; reply has no source address or request ID."""
        # No response target: serialize all 0x12 PIR reads across destinations.
        return await self._read(
            pir.pir_settings_get(destination), 0x12,
            lambda reply: pir.PirSettings.decode(reply[1:10]), timeout=timeout,
        )

    async def read_pir_luminosity_raw(self, destination: int, *, timeout: float = 15.0) -> int | None:
        """0x13 addressed query; returns raw 0..255 or None, not lux."""
        # A short reply raises IndexError in the decoder and is not consumed.
        return await self._read(
            pir.pir_luminosity_get(destination), 0x13,
            lambda reply: reply[1], timeout=timeout,
        )

    async def set_pir_settings(self, settings: pir.PirSettings) -> None:
        """Send one unaddressed 0x11 PIR configuration. No device ACK is awaited."""
        await self.send(pir.pir_settings_set(settings))

    async def set_quiet_mode(self, destination: int, *, action: int, enabled: bool, parameter: int = 30) -> None:
        """Send one quiet-mode command. A 0x40 notification is not a correlated ACK.

        The last observed raw result is stored separately by the session.
        """
        await self.send(
            lighting.quiet_mode(
                destination, action=action, enabled=enabled, parameter=parameter
            )
        )

    async def set_dual_zone_power(self, destination: int, zone: int, enabled: bool) -> None:
        """Write dual-zone power using a Boolean on/off value.

        Raw state 2 remains available from the lower-level encoder.
        """
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool; raw 0/1/2 is available in lighting.dual_zone_power")
        _validate_zone(zone)
        await self.send(lighting.dual_zone_power(destination, int(enabled), zone))

    async def set_dual_zone_brightness_percent(self, destination: int, zone: int, percent: int) -> None:
        """Write a dual-zone brightness percentage using the existing encoder."""
        _validate_zone(zone)
        await self.send(lighting.dual_zone_brightness(destination, zone, percent))

    async def set_dual_zone_brightness_raw(self, destination: int, zone: int, level: int) -> None:
        """Write a dual-zone brightness value in the encoder's native range."""
        _validate_zone(zone)
        await self.send(lighting.dual_zone_brightness_native(destination, zone, level))

    async def set_dual_zone_rgb(self, destination: int, zone: int, red: int, green: int, blue: int) -> None:
        """Convert RGB to the dual-zone native color representation and send once."""
        _validate_zone(zone)
        await self.send(lighting.dual_zone_color(destination, zone, red, green, blue))

    async def set_dual_zone_hs_raw(self, destination: int, zone: int, hue_raw: int, saturation_raw: int) -> None:
        """Send raw hue 0..254 and saturation 0..255 for a lamp zone."""
        _validate_zone(zone)
        await self.send(lighting.dual_zone_color_native(destination, zone, hue_raw, saturation_raw))

    async def set_dual_zone_hs(
        self, destination: int, zone: int, hue_degrees: float, saturation_percent: float
    ) -> None:
        """Send hue in degrees (0..360) and saturation in percent (0..100) for a zone."""
        hue, saturation = lighting.hsv_to_native(hue_degrees, saturation_percent / 100)
        await self.set_dual_zone_hs_raw(destination, zone, hue, saturation)

    async def set_dual_zone_color_temperature_kelvin(self, destination: int, zone: int, kelvin: int) -> None:
        """Convert Kelvin to mired and send one dual-zone temperature command."""
        await self.set_dual_zone_color_temperature_mired(
            destination, zone, lighting.mired_from_kelvin(kelvin)
        )

    async def set_dual_zone_color_temperature_mired(self, destination: int, zone: int, mired: int) -> None:
        """Send a dual-zone temperature command using a mired value directly."""
        _validate_zone(zone)
        await self.send(lighting.dual_zone_temperature_mired(destination, zone, mired))

    async def set_time(self, unix_milliseconds: int, offset_seconds: int) -> None:
        """Explicit one-shot APK 0x30 time write for this MESH SESSION.

        The on-wire command has no lamp address. Return None after the GATT
        write completes, not a device ACK or proof of clock accuracy. No clock
        read, retry, sync on connect, or 0x29 follow-up. No method is exposed
        on individual Lamp.
        """
        await self.send(clock.build_time(unix_milliseconds, offset_seconds))

    async def write_time_with_timezone(
        self, unix_milliseconds: int, posix_rule: str
    ) -> None:
        """Send one 0x29 time and timezone write without waiting for a device reply."""
        await self.send(clock.build_time_with_timezone(unix_milliseconds, posix_rule))

    async def set_time_with_timezone(
        self, unix_milliseconds: int, posix_rule: str, *, timeout: float = 5.0
    ) -> clock.Time29Ack | None:
        """Send 0x29 and wait for its result. The caller schedules any 0x30 write."""
        if not _valid_timeout(timeout, maximum=60):
            raise ValueError("timeout must be positive and at most 60 seconds")
        frame = clock.build_time_with_timezone(unix_milliseconds, posix_rule)
        owner = self._current()
        async with self._time29_lock:
            self._require_same_connection(owner)
            receipt = await self.send_and_track_reply(
                frame,
                0x29, timeout=timeout,
            )
            notification = await receipt.wait()
        return (clock.Time29Ack(notification.payload[2], notification.payload)
                if notification is not None else None)

    async def set_mesh_credentials(self, name: str | bytes, password: str | bytes) -> None:
        """Write the supplied mesh name and password to the current connection.

        This is a provisioning step, not a complete provisioning workflow.
        """
        await self._current().write_credentials(name, password)

    async def read_pair_response(self) -> bytes:
        """Read the current connection's Pair1914 response."""
        return await self._current().read_pair_response()

    async def set_network_parameters(self, settings: provisioning.ProvisioningSettings) -> None:
        """Send the network parameter frame from ProvisioningSettings."""
        if not isinstance(settings, provisioning.ProvisioningSettings):
            raise TypeError("settings must be ProvisioningSettings")
        await self.send(settings.network_frame())

    async def set_network_key(self, key: bytes) -> None:
        """Send one encoded network-key frame."""
        await self.send(provisioning.build_network_key(key))

    async def provision(
        self, mesh_id: int, settings: provisioning.ProvisioningSettings, *,
        groups: list[int] | tuple[int, ...] | None = None,
        timeout: float = 20.0,
        provisioning_byte: int | None = None,
    ) -> provisioning.ProvisioningResult:
        """Direct-device provisioning: optional 0C write, Pair07, 03, 04, 83.

        Use a session connected directly to the *factory device*. The caller
        must supply its current login credentials and advertising metadata.
        Use this direct session exclusively for provisioning until the attempt ends.
        A known 0xA0 provisioning byte skips 03/04 as in the observed APK.
        An unobserved 0x83 yields completed=False; it is NOT safe to retry
        automatically. ``timeout`` (seconds, default 20; max 60) limits only
        the final 0x83 completion-reply window, NOT the complete provisioning
        attempt. Previous group, credential, Pair07 and network operations have
        separate transport/read deadlines. The direct connection closes after
        every attempted provisioning sequence, including errors. No pause,
        retry or rollback.
        This method uses the normal session transport and reply tracking.
        """
        if type(mesh_id) is not int or not 0 <= mesh_id <= 0xFFFF or 0x8000 <= mesh_id <= 0x80FF or mesh_id == 0xFFFF:
            raise ValueError("mesh_id must be a device ID (factory 0 allowed)")
        if not isinstance(settings, provisioning.ProvisioningSettings):
            raise TypeError("settings must be ProvisioningSettings")
        if not _valid_timeout(timeout, maximum=60):
            raise ValueError("timeout must be positive and <=60 seconds")
        if provisioning_byte is not None and (type(provisioning_byte) is not int or not 0 <= provisioning_byte <= 255):
            raise ValueError("provisioning_byte must be 0..255 or None")
        from .groups import set_mesh_groups as build_group_write
        group_frame = None if groups is None else build_group_write(mesh_id, groups)
        # All inputs are validated and frozen before a persistent write.
        settings.network_frame()
        key_frame = provisioning.build_network_key(settings.network_key)
        owner = self._current()
        async with self._provision_lock:
            if self._current() is not owner:
                raise ConnectionLost("provisioning belongs to a replaced connection")
            attempt = _ProvisioningAttempt(self, owner)
            self._provision_attempt = attempt
            token = _provision_scope.set(attempt)
            try:
                if group_frame is not None:
                    # The documented APK wizard does not require a positive
                    # 0x0C acknowledgement before continuing setup. Callers
                    # needing the result can use set_mesh_groups() separately.
                    await self.send(group_frame)
                await self.set_mesh_credentials(
                    settings.credentials.name, settings.credentials.password
                )
                pair = await self.read_pair_response()
                if not pair or pair[0] != 0x07:
                    raise RuntimeError("credential update did not return Pair07; outcome unknown")
                if provisioning_byte == 0xA0:
                    self._current()
                    return provisioning.ProvisioningResult(False, attempt.mesh_id)
                await self.set_network_parameters(settings)
                confirmed = False

                def accept_completion(_notification: ExtendedNotification) -> bool:
                    nonlocal confirmed
                    confirmed = True
                    return True

                receipt = await self.send_and_track_reply(
                    key_frame, 0x83, timeout=timeout, _accept=accept_completion,
                )
                try:
                    completed = await receipt.wait()
                except ConnectionLost:
                    # The key write succeeded and its reply was captured before link loss.
                    if not confirmed:
                        raise
                    return provisioning.ProvisioningResult(True, attempt.mesh_id)
                return provisioning.ProvisioningResult(completed is not None, attempt.mesh_id)
            finally:
                self._provision_attempt = None
                try:
                    # The original connection may have changed credentials during setup.
                    if self._connection is owner:
                        await self.disconnect()
                finally:
                    _provision_scope.reset(token)

    async def remove_from_mesh(self, destination: int) -> None:
        """One explicit kick-out of a registered device; no retry or readback.

        The device can disconnect or change its address/credentials. Remove
        stale registration in the calling application after verification.
        """
        await self.send(provisioning.remove_from_mesh(destination))

    def _start_connection_cleanup(
        self, connection: MeshConnection | GattTransport
    ) -> asyncio.Task:
        # Keep ownership after a caller timeout/cancellation. A new transport
        # must not start until this old connection has actually finished closing.
        self._cleanup_owner = connection
        task = asyncio.create_task(connection.disconnect())
        task.add_done_callback(_observe_task_result)
        self._cleanup_task = task
        return task

    def _check_connection_cleanup(self) -> None:
        task = self._cleanup_task
        if task is None:
            return
        if not task.done():
            raise ConnectionLost("previous connection cleanup is still pending")
        if task.cancelled() or task.exception() is not None:
            raise ConnectionLost(
                "previous connection cleanup failed; call disconnect() explicitly"
            )
        self._cleanup_task = None
        self._cleanup_owner = None

    async def connect(self, *, timeout: float = 30.0) -> None:
        """Perform a single BLE/session/login attempt; propagate actual failures.

        On failure (including cancellation) close the partially created connection
        or the returned transport if connection construction failed.
        No automatic reconnect, retry or command replay occurs. A backend
        that ignores cancellation may finish later; its abandoned connection
        is cleaned up separately without becoming the active session.
        An unresolved previous connection cleanup blocks new attempts. After a
        cleanup error, call disconnect() explicitly to retry only the cleanup.
        """
        if not _valid_timeout(timeout):
            raise ValueError("timeout must be positive and finite")
        loop = asyncio.get_running_loop()
        requested_serial = self._disconnect_serial
        async with self._lifecycle_lock:
            if requested_serial != self._disconnect_serial:
                raise ConnectionLost("connection attempt superseded by disconnect")
            if self.connected:
                return
            self._check_connection_cleanup()
            self._clear_observations()
            # Account for stale-connection cleanup as part of an in-progress
            # public connect. disconnect() must be able to cancel this phase
            # too, not only the later transport/login initialization.
            connecting = asyncio.current_task()
            self._connecting_task = connecting
            deadline = loop.time() + timeout
            try:
                # A physically dropped connection is closed before the next
                # *explicit* connect() call, never automatically recovered.
                if self._connection is not None:
                    old, self._connection = self._connection, None
                    self._ready = False
                    cleanup = self._start_connection_cleanup(old)
                    try:
                        remaining = max(0.0, deadline - loop.time())
                        done, _ = await asyncio.wait({cleanup}, timeout=remaining)
                        if not done:
                            raise asyncio.TimeoutError(
                                "previous session cleanup exceeded connect timeout"
                            )
                        cleanup.result()
                        self._check_connection_cleanup()
                    except BaseException:
                        # Retain the task and connection even if cancellation is
                        # ignored or cleanup ends unsuccessfully. A later
                        # connect must not bypass the unresolved old owner.
                        cleanup.cancel()
                        raise

                connection = None
                transport = None
                abandoned = False

                async def initialize() -> MeshConnection:
                    nonlocal connection, transport
                    candidate = self._transport_factory()
                    transport = (
                        await candidate if inspect.isawaitable(candidate) else candidate
                    )

                    def notify(notification):
                        if (
                            not abandoned
                            and requested_serial == self._disconnect_serial
                            and (
                                (self._connection is connection and self._ready)
                                or (
                                    self._connecting_task is connecting
                                    and loop.time() < deadline
                                )
                            )
                        ):
                            self._receive(notification)

                    connection = MeshConnection(
                        transport, self._credentials, on_notification=notify
                    )

                    def lost():
                        if self._connection is connection and self._ready:
                            self._connection_lost()

                    connection.set_disconnect_observer(lost)
                    # Construct the owner even for a late factory result so
                    # existing cleanup can release its transport without login.
                    if abandoned or requested_serial != self._disconnect_serial:
                        raise ConnectionLost(
                            "connection attempt abandoned before connection setup"
                        )
                    if loop.time() >= deadline:
                        raise asyncio.TimeoutError("connection setup timeout exhausted")
                    await connection.connect()
                    if not connection.connected:
                        raise ConnectionLost(
                            "AwoX mesh disconnected during initialization"
                        )
                    return connection

                # wait_for() can return *success* after its timeout when a
                # third-party coroutine suppresses CancelledError. Keeping
                # setup in a separate task makes caller cancellation and the
                # deadline authoritative without publishing a stale connection.
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise asyncio.TimeoutError(
                        "connection setup timeout exhausted during cleanup"
                    )
                setup = asyncio.create_task(initialize())
                try:
                    done, _ = await asyncio.wait({setup}, timeout=remaining)
                    if not done:
                        raise asyncio.TimeoutError("connection setup timeout exhausted")
                    connection = setup.result()
                    if loop.time() >= deadline:
                        raise asyncio.TimeoutError("connection setup timeout exhausted")
                    if requested_serial != self._disconnect_serial:
                        raise ConnectionLost(
                            "connection attempt superseded by disconnect"
                        )
                    self._connection = connection
                    self._ready = True
                except BaseException:
                    abandoned = True  # Mark before cancellation can be swallowed.
                    self._clear_observations()

                    # The abandoned first setup owns resources too. Reuse
                    # the connection cleanup guard until setup AND close finish.
                    async def finish_abandoned_setup() -> None:
                        try:
                            await setup
                        except BaseException:
                            pass  # The caller keeps the original setup failure.
                        # Until connection construction succeeds, the session owns
                        # the returned transport and must close it directly.
                        owner = connection if connection is not None else transport
                        self._cleanup_owner = owner
                        if owner is not None:
                            await owner.disconnect()

                    self._cleanup_owner = connection
                    self._cleanup_task = asyncio.create_task(finish_abandoned_setup())
                    self._cleanup_task.add_done_callback(_observe_task_result)
                    setup.cancel()
                    self._ready = False
                    # One cleanup path for failed, cancelled and late setups.
                    # Give cooperative cleanup its existing bounded grace;
                    # retain ownership if it has to finish in the background.
                    await asyncio.wait({self._cleanup_task}, timeout=0.05)
                    raise
            finally:
                if self._connecting_task is connecting:
                    self._connecting_task = None

    async def disconnect(self) -> None:
        """Interrupt any in-progress connect, then close the current session.

        No automatic reconnection or retry. Earlier queued connect() calls
        are superseded rather than silently starting after this disconnect.
        An already pending cleanup keeps running without a parallel close;
        new connect() calls remain blocked until it completes successfully.
        """
        scope = _provision_scope.get()
        scoped_close = scope is not None and scope.session is self
        connecting = None
        if not scoped_close:
            self._disconnect_serial += 1
            self._clear_observations()
            connecting = self._connecting_task
            if connecting is not None and connecting is not asyncio.current_task():
                connecting.cancel()  # Let connect() run its existing cleanup.
        async with self._lifecycle_lock:
            if scope is not None and scoped_close:
                if self._connection is not scope.connection:
                    return
                self._disconnect_serial += 1
                self._clear_observations()
            connection, self._connection = self._connection, None
            self._ready = False
            if connection is not None:
                cleanup = self._start_connection_cleanup(connection)
            else:
                cleanup = self._cleanup_task
                if cleanup is None:
                    return
                # Interrupting connect() must still return promptly. Its old
                # cleanup remains guarded, including a cancellation it accepted.
                # Do not overlap or automatically retry a pending disconnect.
                if connecting is not None or not cleanup.done():
                    return
                if cleanup.cancelled() or cleanup.exception() is not None:
                    cleanup = self._start_connection_cleanup(self._cleanup_owner)
            # Cancelling this waiter cannot discard ownership of old resources.
            await asyncio.shield(cleanup)
            self._check_connection_cleanup()

    async def __aenter__(self) -> AwoXMeshSession:
        await self.connect()
        return self

    async def __aexit__(self, *_args) -> None:
        await self.disconnect()


def decode_apk_notification(session_key: bytes, packet: bytes) -> ExtendedNotification:
    """Optional APK-reference interpretation for offline protocol inspection.

    Live ``on_notification`` receives the decrypted raw envelope from
    ``frames.decode_notification``; use the feature-family parsers for the
    documented public ``read_``/``set_`` return values. This reference helper
    does not change the live callback or perform Bluetooth I/O.

    g9.j.e: inverse ATT block, plaintext prefix/tail, selected proven responses.

    There is no outgoing CRC/length envelope in this receive decoder. The native
    receiver does not validate a tag/CRC here. Variant status payloads remain
    raw at this layer; status.parse_status_variant applies APK da.b/da.c/da.d.
    """
    from .frames import decode_notification as decode_envelope

    notification = decode_envelope(session_key, packet)
    opcode, payload = notification.opcode, notification.payload
    kind, value = "unknown", payload
    if opcode in (0x80, 0x82):
        kind = "mesh_status_raw"
    elif opcode == 0x0B:
        kind, value = "mesh_address", int.from_bytes(payload[:2], "little")
    elif opcode == 0x83:
        kind, value = "provisioning_done", True
    elif opcode == 0x08:
        # APK get_mesh_groups listener receives the decrypted response;
        # the Settings UI parses count and little-endian member addresses.
        kind, value = "get_mesh_groups", bytes((opcode,)) + payload
    elif opcode == 0x0C:
        kind, value = "mesh_groups_result", (
            int.from_bytes(payload[:2], "little"),
            payload[2],
        )
    elif opcode == 0x12:
        kind, value = "pir_settings", pir.PirSettings.decode(payload[:9])
    elif opcode == 0x13:
        kind, value = "pir_current_luminosity", payload[0]
    elif opcode == 0x35:
        kind, value = "schedule_read", bytes((opcode,)) + payload
    elif opcode == 0x37:
        # APK g9.j.e explicitly returns without interpreting this message.
        kind = "known_ignored"
    elif opcode == 0x3C:
        kind, value = "presence_read", bytes((opcode,)) + payload
    elif opcode == 0x3B:
        kind, value = "presence_set", bytes((opcode,)) + payload
    elif opcode == 0x33:
        kind, value = "schedule_set", bytes((opcode,)) + payload
    elif opcode == 0x29:
        kind, value = "time_with_timezone_result", payload[2]
    elif opcode in (0x42, 0x43):
        # g9.j.e (APK 1.14.11) dispatches the *entire* decrypted byte array
        # through the corresponding property listener, not a parsed mode.
        # For 0x42, byte 3 of that array (payload[2]) is inspected as a
        # status code, but the listener still receives the original array.
        kind = "power_cut_set_mode" if opcode == 0x42 else "power_cut_get_mode"
        value = bytes((opcode,)) + payload
    elif opcode == 0x40:
        # APK examines response byte r6 (payload[5]); 0 and 0x98 do not
        # log an error. This is NOT proof that the device applied Quiet Mode.
        kind, value = "quiet_mode_result", (
            payload[5] if payload[5] < 128 else payload[5] - 256
        )
    elif opcode == 0x52:
        kind, value = "dual_zone_command_status", (
            payload[0] if payload[0] < 128 else payload[0] - 256
        )
    return ExtendedNotification(opcode, kind, value, payload)
