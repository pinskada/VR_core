"""A base class for long-running services with lifecycle management."""

from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from typing import Optional

log = logging.getLogger(__name__)


class BaseService(ABC):
    """
    A small framework for long-running modules (services).

    Lifecycle:
      - start()  : spawns the service thread and calls _on_start() then _run()
      - stop()   : requests shutdown (sets an Event); _run() should exit soon
      - join()   : waits for the service thread to finish
      - ready()  : blocks until the service declares itself ready
      - is_online(): quick health probe (non-blocking)

    Subclasses MUST implement:
      - _run(self): blocking loop; exit when self._stop.is_set()

    Subclasses MAY override:
      - _on_start(self): open resources, start worker threads; call self._ready.set()
                         when the service is actually operational.
      - _on_stop(self): close resources, join worker threads.
      - is_online(self): to add module-specific health checks (but keep it fast).
    """

    def __init__(self, name: str):
        self.name = name

        # Shutdown & readiness coordination
        self._ready = threading.Event()
        self._stop = threading.Event()
        self._service_stopped = threading.Event()

        # Main service thread (non-daemon so we can shut down cleanly)
        self._thread = threading.Thread(
            target=self._run_wrapper,
            name=f"{self.name}-svc",
            daemon=False,
        )

        # Optional flag for subclasses to mark fatal conditions
        self._fatal = False


    # ---------------- Public API ----------------

    def start(self) -> None:
        """Start the service thread."""
        if self._thread.is_alive():
            log.warning("[%s] start() called but thread already running", self.name)
            return
        self._thread.start()


    def stop(self) -> None:
        """Request the service to stop soon."""
        self._stop.set()


    def join(self, timeout: Optional[float] = None) -> None:
        """Wait for the service thread to exit."""
        self._thread.join(timeout=timeout)


    def ready(self, timeout: Optional[float] = None) -> bool:
        """
        Wait until the service is reported ready (True if ready before timeout).
        Subclasses should set self._ready.set() in _on_start() when truly operational.
        """
        return self._ready.wait(timeout=timeout)


    def is_online(self) -> bool:
        """
        Fast, non-blocking health probe used by monitors/supervisors.
        Default: thread is alive AND service declared ready AND not fatal.
        Subclasses can refine (e.g., check socket bound, worker thread alive).
        """
        return self._thread.is_alive() and self._ready.is_set() and not self._fatal


    # ---------------- Internals ----------------

    def _run_wrapper(self) -> None:
        """
        Orchestrates the subclass lifecycle inside the service thread:
          1) _on_start()
          2) ensure 'ready' is set (if subclass forgot)
          3) _run()          (blocking)
          4) _on_stop()      (cleanup, always attempted)
        """
        try:
            try:
                self._on_start()
            except Exception:  # pylint: disable=broad-except
                log.exception("[%s] error during _on_start()", self.name)
                # If startup fails, don't run; mark fatal and return.
                self._fatal = True
                return

            # If the subclass didn't explicitly declare readiness, assume it's ready now.
            if not self._ready.is_set():
                log.debug(
                    "[%s] _on_start() returned but service did not mark ready yet.",
                    self.name
                )

            # Enter the main loop
            try:
                self._run()
            except Exception:  # pylint: disable=broad-except
                self._fatal = True
                log.exception("[%s] crashed inside _run()", self.name)

        finally:
            # Best-effort cleanup; never raise from here.
            try:
                self._on_stop()
            except Exception:  # pylint: disable=broad-except
                log.exception("[%s] error during _on_stop()", self.name)
            finally:
                self._service_stopped.set()


    # ---------------- Hooks for subclasses ----------------

    def _on_start(self) -> None:
        """
        Open resources and start any worker threads/processes here.
        IMPORTANT: call self._ready.set() only when the service is truly operational
        (e.g., socket bound, first frame grabbed). Return quickly (no long loops).
        """


    @abstractmethod
    def _run(self) -> None:
        """
        The main blocking loop. Exit promptly when self._stop.is_set() is True.
        Typical pattern:
            while not self._stop.is_set():
                # do work or supervise children
                self._stop.wait(0.2)  # avoid busy-waiting
        """
        raise NotImplementedError


    def _on_stop(self) -> None:
        """
        Signal worker threads/processes to stop, close resources, and join them.
        Must be idempotent (safe to call even if _on_start failed partway).
        """


    # ---------------- Convenience properties ----------------

    @property
    def alive(self) -> bool:
        """Alias for _thread.is_alive()."""
        return self._thread.is_alive()


    @property
    def stop_requested(self) -> bool:
        """True if stop() has been called."""
        return self._stop.is_set()


    def stopped(self, timeout: Optional[float] = None) -> bool:
        """
        Block until the service has fully stopped and cleanup is done.
        Returns True if the service stopped before the timeout.
        """
        return self._service_stopped.wait(timeout=timeout)