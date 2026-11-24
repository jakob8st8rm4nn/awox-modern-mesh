"""Standalone ESPHome API + connectable advertisement discovery.

Explicit async context manager; does NOT import Home Assistant or its runtime.
It uses bleak-esphome/habluetooth and does not perform Windows BLE scans.
Only one independent proxy context may be active per process.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import time
from dataclasses import replace
from types import MappingProxyType
from typing import Callable, Mapping

from ._validation import _valid_timeout
from .advertisements import AdvertisementRecord
from .esphome_transport import ESPHomeNoCCCDTransport
from .transport import DiscoveredDevice, _observe_task_result

_LOG = logging.getLogger(__name__)
_active_proxy = None


class ESPHomeProxy:
    """ESPHome Bluetooth proxy access and advertisement observation.

    Scanning and transport creation are separate from mesh authentication.
    """
    def __init__(
        self,
        host: str,
        api_key: str = "",
        *,
        discovery_timeout: float = 15.0,
        on_advertisement: Callable[[DiscoveredDevice], None] | None = None,
    ):
        if not isinstance(host, str) or not host.strip():
            raise ValueError("proxy host required")
        if not isinstance(api_key, str):
            raise TypeError("API key must be a string")
        if not _valid_timeout(discovery_timeout):
            raise ValueError("discovery timeout must be positive")
        self._host = host
        self._key = api_key
        self._discovery_timeout = discovery_timeout
        self._close_lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task | None = None
        self._cleanup_action = None
        self._late_stops: dict[asyncio.Lock, tuple[object, asyncio.Task]] = {}
        self._manager = None
        self._manager_stop_lock = asyncio.Lock()
        self._bluetooth = None
        self._bluetooth_setup: asyncio.Future[None] | None = None
        self._previous_bluetooth_manager = None
        self._backend_type = None
        self._client_type = None
        # Invalidate callbacks that were queued by a closed/replaced proxy.
        self._advertisement_epoch = 0
        # One cache owns each accepted record together with its RSSI/metadata.
        # Public advertisement views are derived from this same observation.
        self._latest_observations: dict[str, DiscoveredDevice] = {}
        self._advertisement_callbacks: dict[
            object, Callable[[DiscoveredDevice], None]
        ] = {}
        if on_advertisement is not None:
            self.on_advertisement(on_advertisement)
        self._unregister_per_address: dict[str, Callable[[], None]] = {}

    @property
    def advertisements(self) -> Mapping[str, AdvertisementRecord]:
        """Read-only snapshot by MAC; values are latest known advertisements.

        These records can be old. Consult ``received_monotonic``; a cache
        snapshot without an original backend timestamp may have it set to None.
        """
        return MappingProxyType(
            {
                address: observation.advertisement
                for address, observation in self._latest_observations.items()
            }
        )

    def get_advertisement(self, mac: str) -> AdvertisementRecord | None:
        """Return the last received/observed advertisement, without BLE I/O."""
        if not isinstance(mac, str) or not mac:
            raise ValueError("MAC address must be a nonempty string")
        observation = self._latest_observations.get(mac.upper())
        return observation.advertisement if observation is not None else None

    def on_advertisement(
        self, callback: Callable[[DiscoveredDevice], None]
    ) -> Callable[[], None]:
        """Subscribe to incoming proxy advertisement events, returns unsubscribe.

        Notifications are synchronous, do not initiate a GATT connection.
        When supported by habluetooth, repeats from the same address are
        received even if the advertising payload is unchanged. A callback
        failure is logged and never interrupts Bluetooth reception.
        Each unsubscribe affects only its own registration and is safe to
        call repeatedly, including after registering the same callback again.
        """
        if not callable(callback):
            raise TypeError("advertisement callback must be callable")
        token = object()
        self._advertisement_callbacks[token] = callback

        def unsubscribe():
            """Stop invoking this previously registered advertisement callback."""
            self._advertisement_callbacks.pop(token, None)

        return unsubscribe

    @staticmethod
    def _from_service_info(info) -> DiscoveredDevice | None:
        parsed = AdvertisementRecord.from_service_info(info)
        if parsed is None:
            return None
        return DiscoveredDevice(info.device, info.address, info.rssi, parsed)

    def _save_observation(self, observation: DiscoveredDevice) -> bool:
        address = observation.address.upper()
        previous_observation = self._latest_observations.get(address)
        previous = (
            previous_observation.advertisement
            if previous_observation is not None
            else None
        )
        fresh = observation.advertisement
        seen = fresh.received_monotonic
        if seen is not None and (
            type(seen) not in (int, float)
            or (type(seen) is float and not math.isfinite(seen))
        ):
            fresh = replace(fresh, received_monotonic=None)
            observation = replace(observation, advertisement=fresh)
        # A stale cache snapshot/event must not overwrite newer data or
        # be dispatched as a fresh observation to application callbacks.
        # Equal timestamps remain valid: repeated advertisements can carry
        # changed RSSI even when their packet content is unchanged.
        if (
            previous is not None
            and previous.received_monotonic is not None
            and (
                fresh.received_monotonic is None
                or fresh.received_monotonic < previous.received_monotonic
            )
        ):
            return False
        self._latest_observations[address] = observation
        return True

    def _handle_advertisement_event(self, info) -> None:
        observation = self._from_service_info(info)
        if observation is not None:
            self._publish_observation(observation)

    def _publish_observation(self, observation: DiscoveredDevice) -> None:
        """Cache and deliver one parsed event; never publish a stale record."""
        if not self._save_observation(observation):
            return
        observation = self._latest_observations[observation.address.upper()]
        for callback in tuple(self._advertisement_callbacks.values()):
            try:
                callback(observation)
            except (Exception, asyncio.CancelledError):
                _LOG.exception("AwoX on_advertisement callback failed")

    def _subscribe_address(self, address: str) -> None:
        address = address.upper()
        if address in self._unregister_per_address or self._bluetooth is None:
            return
        bluetooth = self._bluetooth
        register = getattr(bluetooth, "async_register_advertisement_callback", None)
        if register is not None:
            epoch = self._advertisement_epoch

            def receive(info):
                # Unregister cannot retract callbacks already queued by the
                # backend. Never let an older manager populate a new cache.
                if self._advertisement_epoch == epoch and self._bluetooth is bluetooth:
                    self._handle_advertisement_event(info)

            self._unregister_per_address[address] = register(receive, address)

    def _handle_changed_advertisement(self, info) -> None:
        """Handle new/changed devices from BluetoothManager's discovery hook.

        This hook exists on the standalone habluetooth.BluetoothManager, unlike
        Home Assistant's async_register_callback (which the base manager does
        not provide). For known addresses, the per-address subscriber handles
        every incoming packet to avoid duplicate notifications.
        """
        address = info.address.upper()
        if address in self._unregister_per_address:
            return
        observation = self._from_service_info(info)
        if observation is None:
            return
        self._publish_observation(observation)
        self._subscribe_address(address)

    def _start_advertisement_callbacks(self) -> None:
        """Seed existing ESPHome discoveries and register per-address listeners.

        Newly discovered addresses arrive via the manager's overridden
        _discover_service_info hook, not a Home Assistant-only callback API.
        """
        if self._bluetooth is None:
            return
        discover = getattr(self._bluetooth, "async_discovered_service_info", None)
        if discover is not None:
            for info in tuple(discover(False)):
                observation = self._from_service_info(info)
                if observation is not None:
                    self._save_observation(observation)
                    self._subscribe_address(info.address)

    def _stop_advertisement_callbacks(self) -> None:
        per_address, self._unregister_per_address = self._unregister_per_address, {}
        for cancel in tuple(per_address.values()):
            try:
                cancel()
            except Exception:
                _LOG.exception("AwoX advertisement unsubscribe failed")

    def _start_late_stop(self, manager, lock: asyncio.Lock) -> asyncio.Task:
        async def stop():
            async with lock:
                await manager.stop()

        task = asyncio.create_task(stop())
        self._late_stops[lock] = manager, task

        def finished(result):
            if result.cancelled():
                return  # Retain ownership for explicit cleanup.
            if result.exception() is None:
                self._late_stops.pop(lock)
            else:
                _LOG.error("AwoX late ESPHome API stop failed", exc_info=result.exception())

        task.add_done_callback(finished)
        return task

    async def __aenter__(self) -> "ESPHomeProxy":
        global _active_proxy
        if self._close_lock.locked():
            raise RuntimeError("ESPHomeProxy context is closing")
        if self._bluetooth is not None:
            raise RuntimeError("ESPHomeProxy context is already active")
        if _active_proxy is not None:
            raise RuntimeError("another ESPHomeProxy context is already active")
        from bleak_esphome import APIConnectionManager
        from bleak_esphome.backend.client import ESPHomeClient
        from habluetooth import HaBleakClientWrapper
        import habluetooth

        self._advertisement_epoch += 1
        epoch = self._advertisement_epoch
        owner = self

        class StandaloneBluetoothManager(habluetooth.BluetoothManager):
            def _discover_service_info(self, service_info):
                # The base manager calls this for newly seen / changed packets.
                # It has NO Home Assistant async_register_callback API, so
                # bridge the hook directly to our AwoX advertisement stream.
                # An old manager can still dispatch already-queued callbacks
                # after shutdown/reopen. Its events belong to the old cache.
                if owner._advertisement_epoch != epoch or owner._bluetooth is not self:
                    return
                try:
                    owner._handle_changed_advertisement(service_info)
                except Exception:
                    _LOG.exception("AwoX advertisement discovery handler failed")

        # habluetooth keeps its manager globally. Preserve an earlier owner
        # so this standalone context does not leave a stopped manager behind.
        try:
            previous = habluetooth.get_manager()
        except RuntimeError:  # no manager has been registered yet
            previous = None
        bluetooth = StandaloneBluetoothManager()
        self._previous_bluetooth_manager = previous
        self._bluetooth = bluetooth
        _active_proxy = self
        # If API startup is cancelled but later succeeds, its extra stop must
        # follow normal __aexit__ cleanup rather than race the first stop.
        late_start_cleanup_gate: asyncio.Future[None] | None = None
        try:
            habluetooth.set_manager(bluetooth)
            setup_finished = asyncio.get_running_loop().create_future()
            self._bluetooth_setup = setup_finished
            try:
                await bluetooth.async_setup()
            finally:
                setup_finished.set_result(None)
                self._bluetooth_setup = None
            # close() can run in a different task while startup is suspended.
            # Never construct/start a new API manager after that close.
            if self._advertisement_epoch != epoch or self._bluetooth is not bluetooth:
                raise RuntimeError("ESPHomeProxy context closed during Bluetooth setup")
            manager = APIConnectionManager(
                {"address": self._host, "noise_psk": self._key or None}
            )
            self._manager = manager
            # Keep the lock with this manager, including late startup cleanup.
            stop_lock = asyncio.Lock()
            self._manager_stop_lock = stop_lock
            # A foreign API startup may swallow CancelledError. asyncio.wait_for
            # can then report late success after its deadline, and caller
            # cancellation can leave startup running after our normal stop.
            # Keep that work in a separate task: cancellation and the 30-second
            # deadline remain authoritative without waiting for the backend.
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 30
            starting = asyncio.create_task(manager.start())
            try:
                done, _ = await asyncio.wait({starting}, timeout=30)
                if not done:
                    raise asyncio.TimeoutError("ESPHome API startup timed out")
                starting.result()
                if loop.time() >= deadline:
                    raise asyncio.TimeoutError("ESPHome API startup timed out")
            except BaseException:
                # __aexit__ stops the API manager immediately. If its start
                # nonetheless finishes later, stop the SAME manager once more.
                # Never touch self._manager: it may belong to a new context.
                late_start_cleanup_gate = asyncio.get_running_loop().create_future()

                def dispose_late_start(task: asyncio.Task) -> None:
                    if task.cancelled():
                        return
                    try:
                        task.result()
                    except BaseException:
                        return  # Observe a late backend failure.

                    async def stop_abandoned() -> None:
                        # A late success can arrive during the *first* stop.
                        # Never overlap two stops on the same API manager.
                        await late_start_cleanup_gate
                        self._start_late_stop(manager, stop_lock)

                    asyncio.create_task(stop_abandoned())

                starting.add_done_callback(dispose_late_start)
                starting.cancel()
                raise
            if self._advertisement_epoch != epoch or self._bluetooth is not bluetooth:
                # A concurrent exit may have stopped the manager *before*
                # start() finished. Stop again after its late completion.
                task = self._start_late_stop(manager, stop_lock)
                # Wait without transferring caller cancellation to the stop.
                await asyncio.wait({task}, timeout=15)
                raise RuntimeError("ESPHomeProxy context closed during API setup")
        except BaseException:
            # An older opening task must not tear down a NEW context started
            # with this proxy object after its prior one was closed.
            try:
                if self._advertisement_epoch == epoch and self._bluetooth is bluetooth:
                    try:
                        await self.__aexit__(None, None, None)
                    except BaseException:
                        pass  # preserve the original setup failure
            finally:
                if (
                    late_start_cleanup_gate is not None
                    and not late_start_cleanup_gate.done()
                ):
                    late_start_cleanup_gate.set_result(None)
            raise

        self._client_type = HaBleakClientWrapper
        self._backend_type = ESPHomeClient
        try:
            self._start_advertisement_callbacks()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def scan_mesh_devices(self, duration: float = 6.5) -> tuple[DiscoveredDevice, ...]:
        """Discover AwoX advertisements received by this ESPHome proxy.

        Uses the proxy's existing habluetooth discovery cache rather than a
        local BLE adapter, GATT connection or mesh login. Scan-only proxy
        advertisements are included (connectable=False). For an address also
        received as a live event, return its freshest accepted observation,
        not an older scanner-cache snapshot.
        """
        if not _valid_timeout(duration):
            raise ValueError("scan duration must be positive and finite")
        if self._manager is None or self._bluetooth is None:
            raise RuntimeError("enter ESPHomeProxy context first")

        # Pin this scan to one active context. A caller may close and reopen
        # the proxy while we sleep; mixing its two discovery caches would
        # return observations from a session that did not perform this scan.
        manager, bluetooth = self._manager, self._bluetooth
        deadline = time.monotonic() + duration
        while True:
            if self._manager is not manager or self._bluetooth is not bluetooth:
                raise RuntimeError("ESPHomeProxy context changed or closed during scan")
            # A snapshot is not an event stream. Never call on_advertisement
            # merely because the same cached entry was polled again.
            for info in bluetooth.async_discovered_service_info(False):
                if self._manager is not manager or self._bluetooth is not bluetooth:
                    raise RuntimeError(
                        "ESPHomeProxy context changed or closed during scan"
                    )
                observation = self._from_service_info(info)
                if observation is not None:
                    self._save_observation(observation)
                    self._subscribe_address(info.address)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            await asyncio.sleep(min(0.4, remaining))
        # The per-address event stream may observe a valid device which is
        # absent from the manager's latest snapshot. Include those live
        # observations, and prefer their newest accepted RSSI/metadata.
        if self._manager is not manager or self._bluetooth is not bluetooth:
            raise RuntimeError("ESPHomeProxy context changed or closed during scan")
        return tuple(self._latest_observations[address]
                     for address in sorted(self._latest_observations))

    async def create_transport(self, mac: str) -> ESPHomeNoCCCDTransport:
        """Look up a CONNECTABLE advertisement from this proxy, no OS scan."""
        if (
            self._manager is None
            or self._bluetooth is None
            or self._client_type is None
        ):
            raise RuntimeError("enter ESPHomeProxy context first")
        if not isinstance(mac, str) or not mac:
            raise ValueError("MAC address must be a nonempty string")
        mac = mac.upper()  # Same canonical form as get_advertisement/cache keys.
        manager, bluetooth = self._manager, self._bluetooth
        client_type, backend_type = self._client_type, self._backend_type
        deadline = time.monotonic() + self._discovery_timeout
        while True:
            if (
                self._manager is not manager
                or self._bluetooth is not bluetooth
                or self._client_type is not client_type
                or self._backend_type is not backend_type
            ):
                raise RuntimeError(
                    "ESPHomeProxy context changed or closed during transport lookup"
                )
            if time.monotonic() >= deadline:
                raise LookupError("no connectable proxy advertisement for given device")
            device = bluetooth.async_ble_device_from_address(mac, True)
            if (
                self._manager is not manager
                or self._bluetooth is not bluetooth
                or self._client_type is not client_type
                or self._backend_type is not backend_type
            ):
                raise RuntimeError(
                    "ESPHomeProxy context changed or closed during transport lookup"
                )
            if time.monotonic() >= deadline:
                raise LookupError("no connectable proxy advertisement for given device")
            if device is not None:
                return ESPHomeNoCCCDTransport(
                    device, client_factory=client_type, backend_type=backend_type
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LookupError("no connectable proxy advertisement for given device")
            await asyncio.sleep(min(0.4, remaining))

    async def __aexit__(self, *_args) -> None:
        # Pin queued exits to the context they were asked to close.
        bluetooth = self._bluetooth
        if bluetooth is None:
            tasks = {
                self._start_late_stop(manager, lock) if task.done() else task
                for lock, (manager, task) in tuple(self._late_stops.items())
                if not task.done() or task.cancelled() or task.exception() is not None
            }
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=15)
                if pending:
                    raise asyncio.TimeoutError("ESPHome late API cleanup exceeded 15 seconds")
                for task in done:
                    task.result()
            return
        async with self._close_lock:
            if self._bluetooth is not bluetooth:
                return
            if self._cleanup_action is None:
                import habluetooth

                # Stop receiving immediately; retain ownership until both
                # manager stops have actually completed successfully.
                self._advertisement_epoch += 1
                manager, self._manager = self._manager, None
                stop_lock = self._manager_stop_lock
                previous = self._previous_bluetooth_manager
                setup_finished = self._bluetooth_setup
                self._client_type = None
                self._backend_type = None
                bluetooth_stopped = False

                async def cleanup() -> None:
                    global _active_proxy
                    nonlocal manager, bluetooth_stopped
                    self._stop_advertisement_callbacks()
                    # Setup can install tracking after its adapter await.
                    if setup_finished is not None:
                        await asyncio.shield(setup_finished)
                    try:
                        if manager is not None:
                            async with stop_lock:
                                await manager.stop()
                            manager = None
                    finally:
                        if not bluetooth_stopped:
                            # Both sync and async habluetooth stops are supported.
                            stopped = bluetooth.async_stop()
                            if inspect.isawaitable(stopped):
                                await stopped
                            bluetooth_stopped = True
                    try:
                        current = habluetooth.get_manager()
                    except RuntimeError:
                        current = None
                    # Never overwrite a manager installed by another owner.
                    if current is bluetooth:
                        habluetooth.set_manager(previous)
                    self._bluetooth = None
                    self._previous_bluetooth_manager = None
                    self._latest_observations.clear()
                    self._cleanup_action = None
                    self._cleanup_task = None
                    if _active_proxy is self:
                        _active_proxy = None

                self._cleanup_action = cleanup
            task = self._cleanup_task
            if task is None or task.done():
                task = asyncio.create_task(self._cleanup_action())
                task.add_done_callback(_observe_task_result)
                self._cleanup_task = task
        # Caller cancellation and the deadline never discard unfinished
        # cleanup. Repeated closes share it; a failed task is retried only
        # by an explicit later close, skipping already completed steps.
        done, _ = await asyncio.wait({task}, timeout=15)
        if not done:
            raise asyncio.TimeoutError("ESPHome proxy cleanup exceeded 15 seconds")
        if task.cancelled():
            raise RuntimeError("ESPHome proxy cleanup was cancelled; outcome unknown")
        task.result()
