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
from vr_core.gaze.gaze_preprocess import GazePreprocess


print("===== DEBUG INFO =====")
print("PYTHONPATH:", os.environ.get("PYTHONPATH"))
print("VIRTUAL_ENV:", os.environ.get("VIRTUAL_ENV"))
print("SYS PATH:", sys.path)
print("======================")


class Core:
    """
    Core engine for RPI.
    """

    def __init__(self, argv: List[str] | None = None):
        print("Starting VR Core...")

        self.argv = argv or []

        self.logger = setup_logger("Core")

        self.queues = CommQueues()
        self.config_signals = signals.ConfigSignals()
        self.comm_router_signals = signals.CommRouterSignals()
        self.tracker_data_signals = signals.TrackerDataSignals()
        self.tracker_signals = signals.TrackerSignals()
        self.eye_ready_signals = signals.EyeTrackerSignals()
        self.gaze_signals = signals.GazeSignals()
        self.imu_signals = signals.IMUSignals()
        self.test_signals = signals.TestModeSignals()

        self.logger.info("All components initialized.")

        self.services: Dict[str, BaseService | Config] = {}
        self._stop_requested = False


    # -------- build: construct everything & inject dependencies --------

    def build(self):
        """Build and start all core modules."""

        config = Config(
            config_ready_s=self.config_signals.config_ready_s
        )

        tcp_server = TCPServer(
            config=config,
            tcp_receive_q=self.queues.tcp_receive_q,
        )
        camera_manager = CameraManager(
            config=config,
        )
        esp32 = Esp32(
            esp_cmd_q=self.queues.esp_cmd_q,
            esp_mock_mode=self.test_signals.esp_mock_mode,
            config=config,
        )
        imu = Imu(
            comm_router_q=self.queues.comm_router_q,
            gyro_mag_q=self.queues.gyro_mag_q,
            imu_signals=self.imu_signals,
            config=config,
            imu_mock_mode=self.test_signals.imu_mock_mode,
        )
        tracker_sync = TrackerSync(
            tracker_data_s=self.tracker_data_signals,
            comm_router_q=self.queues.comm_router_q,
            ipd_q=self.queues.ipd_q,
            tracker_health_q=self.queues.tracker_health_q,
            tracker_response_l_q=self.queues.tracker_resp_l_q,
            tracker_response_r_q=self.queues.tracker_resp_r_q,
            config=config,
        )
        frame_provider = FrameProvider(
            i_camera_manager=camera_manager,
            comm_router_s=self.comm_router_signals,
            eye_tracker_s=self.eye_ready_signals,
            tracker_s=self.tracker_signals,
            tracker_cmd_l_q=self.queues.tracker_cmd_l_q,
            tracker_cmd_r_q=self.queues.tracker_cmd_r_q,
            config=config,
        )
        tracker_process = TrackerProcess(
            tracker_cmd_q_l=self.queues.tracker_cmd_l_q,
            tracker_cmd_q_r=self.queues.tracker_cmd_r_q,
            tracker_resp_q_l=self.queues.tracker_resp_l_q,
            tracker_resp_q_r=self.queues.tracker_resp_r_q,
            tracker_health_q=self.queues.tracker_health_q,
            eye_tracker_signals=self.eye_ready_signals,
            tracker_signals=self.tracker_signals,
            config=config,
        )
        tracker_control = TrackerControl(
            com_router_queue_q=self.queues.comm_router_q,
            tracker_cmd_l_q=self.queues.tracker_cmd_l_q,
            tracker_cmd_r_q=self.queues.tracker_cmd_r_q,
            comm_router_signals=self.comm_router_signals,
            tracker_data_signals=self.tracker_data_signals,
            tracker_signals=self.tracker_signals,
            i_tracker_process=tracker_process,
            config=config,
        )
        gaze_calib = GazeCalib(
            ipd_q=self.queues.ipd_q,
            comm_router_q=self.queues.comm_router_q,
            gaze_signals=self.gaze_signals,
            config=config,
        )
        gaze_calc = GazeCalc(
            ipd_q=self.queues.ipd_q,
            esp_cmd_q=self.queues.esp_cmd_q,
            comm_router_q=self.queues.comm_router_q,
            gyro_mag_q=self.queues.gyro_mag_q,
            gaze_signals=self.gaze_signals,
            config=config,
        )
        gaze_preprocess = GazePreprocess(
            tracker_data_q=self.queues.tracker_data_q,
            ipd_q=self.queues.ipd_q,
            comm_router_q=self.queues.comm_router_q,
            gaze_signals=self.gaze_signals,
            imu_send_to_gaze_signal=self.imu_signals.imu_send_to_gaze,
            config=config,
        )
        gaze_control = GazeControl(
            gaze_signals=self.gaze_signals,
            imu_send_to_gaze_signal=self.imu_signals.imu_send_over_tcp,
            i_gaze_calib=gaze_calib,
            config=config,
        )
        comm_router = CommRouter(
            i_tcp_server=tcp_server,
            i_gaze_control=gaze_control,
            i_tracker_control=tracker_control,
            com_router_queue_q=self.queues.comm_router_q,
            tcp_receive_q=self.queues.tcp_receive_q,
            esp_cmd_q=self.queues.esp_cmd_q,
            imu_signals=self.imu_signals,
            comm_router_signals=self.comm_router_signals,
            tracker_signals=self.tracker_signals,
            config_signals=self.config_signals,
            config=config,
        )

        self.services = {
            "CommRouter": comm_router,
            "TCPServer": tcp_server,
            "ConfigService": config,
            "CameraManager": camera_manager,
            "ESP32": esp32,
            "IMU": imu,
            "FrameProvider": frame_provider,
            "TrackerProcess": tracker_process,
            "TrackerSync": tracker_sync,
            "TrackerControl": tracker_control,
            "GazeCalib": gaze_calib,
            "GazeCalc": gaze_calc,
            "GazePreprocess": gaze_preprocess,
            "GazeControl": gaze_control,
        }


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

        # Wait for the service to declare readiness
        for name in start_order:
            svc = self.services[name]
            self.logger.info("→ start %s", name)

            if name == "TCPServer":
                # TCP server needs longer timeout since client may take time to connect
                timeout = 60
                #timeout = float("inf")

                if not svc.ready(timeout=timeout):
                    raise TimeoutError(f"Service '{name}' did not become ready in time")
            else:
                svc.start()
                if not svc.ready(timeout=5):
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
    app = Core(argv)
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
