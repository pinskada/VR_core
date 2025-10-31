# ruff: noqa: F401,F841
# pylint: disable=unused-import, unused-argument, unused-variable
# pyright: reportUnusedImport=false, reportUnusedVariable=false

"""Core engine for RPI."""

import os
import sys
import time
import logging
import signal
from typing import Dict, List

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.utilities.logger_setup import setup_logger

from vr_core.ports.queues import CommQueues
import vr_core.ports.signals as signals
import vr_core.ports.interfaces as interfaces

from vr_core.health_monitor import HealthMonitor

from vr_core.network.tcp_server import TCPServer
from vr_core.network.comm_router import CommRouter

from vr_core.raspberry_perif.esp32 import Esp32
from vr_core.raspberry_perif.imu import Imu
from vr_core.raspberry_perif.camera_manager import CameraManager

from vr_core.eye_tracker.tracker_control import TrackerControl
from vr_core.eye_tracker.tracker_sync import TrackerSync
from vr_core.eye_tracker.tracker_process import TrackerProcess
from vr_core.eye_tracker.frame_provider import FrameProvider

from vr_core.gaze.gaze_control import GazeControl
from vr_core.gaze.gaze_calib import GazeCalib
from vr_core.gaze.gaze_calc import GazeCalc


print("===== DEBUG INFO =====")
print("PYTHONPATH:", os.environ.get("PYTHONPATH"))
print("VIRTUAL_ENV:", os.environ.get("VIRTUAL_ENV"))
print("SYS PATH:", sys.path)
print("======================")


class Core:
    """
    Core engine for RPI.
    """

    def __init__(self, cfg: Config, argv: List[str] | None = None):
        print("Starting VR Core...")

        self.argv = argv or []
        self.cfg = cfg

        self.logger = setup_logger("Core")

        self.queues = CommQueues()
        self.config_signals = signals.ConfigSignals()
        self.comm_router_signals = signals.CommRouterSignals()
        self.tracker_signals = signals.TrackerSignals()
        self.eye_ready_signals = signals.EyeTrackerSignals()

        self.logger.info("All components initialized.")

        self.services: Dict[str, BaseService] = {}
        self._stop_requested = False


    # -------- build: construct everything & inject dependencies --------

    def build(self):
        """Build and start all core modules."""

        tcp_server = TCPServer(
            config=self.cfg,
            tcp_receive_q=self.queues.tcp_receive_q,
        )

        # config.tracker_config.use_test_video = True  # Use saved video instead of live camera
        # if not config.tracker_config.use_test_video:
        #     module_list.cam_manager = CameraManager()
        # time.sleep(0.5)
        # HealthMonitor()
        # time.sleep(0.5)
        # Gyroscope()
        # time.sleep(0.5)
        # ESP32(force_mock=True)
        # time.sleep(0.5)
        # #PreProcessor()
        # time.sleep(0.5)
        # CommandDispatcher()  # type: ignore # noqa: F841

        self.services = {}


    # ------------------------ lifecycle: start/stop ---------------------

    def start(self) -> None:
        """ Start services in dependency order, waiting for readiness on each."""

        self.logger.info("Starting services.")
        if not self.services:
            self.logger.warning("No services registered. "
                "Did you forget to call build() or wire them?")
            return

        # Order listed in build()
        start_order: List[str] = list(self.services.keys())
        self.logger.info("Starting services in order: %s", " → ".join(start_order))

        for name in start_order:
            svc = self.services[name]
            self.logger.info("→ start %s", name)
            svc.start()
            # Wait for the service to declare readiness
            if name == "TCPServer":
                timeout = self.cfg.tcp.connect_timeout
                if timeout == -1:
                    timeout = float("inf")
                if not svc.ready(timeout=timeout) and not self.config_signals.config_ready.is_set():
                    raise TimeoutError(f"Service '{name}' did not become ready in time")
            elif not svc.ready(timeout=5):
                raise TimeoutError(f"Service '{name}' did not become ready in time")

        self.logger.info("All services started and ready.")


    def stop(self):
        """Stop services in reverse order and join them."""
        if not self.services:
            return

        stop_order = list(reversed(self.services.keys()))
        self.logger.info("Stopping services in reverse order: %s", " ← ".join(stop_order))

        # Request stop
        for name in stop_order:
            try:
                self.logger.info("→ stop %s", name)
                self.services[name].stop()
            except (RuntimeError, ValueError, OSError) as e:
                # Common states: not started, already closed, socket already closed
                self.logger.warning("Benign stop error in %s: %s", name, e, exc_info=True)
            except Exception:  # pylint: disable=broad-except
                self.logger.exception("Unexpected error calling stop() on %s", name)

        # Join
        for name in stop_order:
            svc = self.services[name]
            try:
                svc.join(timeout=5)
            except (RuntimeError, ValueError) as e:
                self.logger.warning("Join error in %s: %s", name, e, exc_info=True)
            except Exception:  # pylint: disable=broad-except
                self.logger.exception("Unexpected exception joining %s", name)
            else:
                # No exception: verify thread actually stopped
                if getattr(svc, "alive", None):
                    try:
                        still_alive = svc.alive  # BaseService exposes this
                    except Exception:  # pylint: disable=broad-except
                        still_alive = False
                    if still_alive:
                        self.logger.error("%s did not stop within 5s (still alive).", name)

        self.logger.info("All services stopped.")


    def wait_forever(self):
        """Idle loop for the supervisor. Add supervision/restarts here later if needed."""
        self.logger.info("Waiting for services to stop...")
        while not self._stop_requested:
            time.sleep(0.5)


    # --------------------------- signal hooks --------------------------

    def install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""

        def _handler(signum, _frame):
            self.logger.info("Signal %s received, shutting down…", signum)
            self._stop_requested = True

        signal.signal(signal.SIGINT, _handler)
        try:
            signal.signal(signal.SIGTERM, _handler)
        except (AttributeError, OSError):
            # Not available on some platforms (e.g., Windows older Pythons)
            pass


# ------------------------------ Entrypoint -----------------------------

def main(argv: list[str] | None = None) -> int:
    """Main entrypoint for the VR Core application."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = Config()
    app = Core(cfg, argv)
    app.install_signal_handlers()

    try:
        app.build()
        app.start()
        app.wait_forever()
    except KeyboardInterrupt:
        logging.getLogger("core").info("KeyboardInterrupt")
    except Exception:  # pylint: disable=broad-except
        logging.getLogger("core").exception("Fatal error in Core")
        return 1
    finally:
        app.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
