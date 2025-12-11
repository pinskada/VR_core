# ruff: noqa: ERA001
"""Core engine for RPI."""

import logging
import os
import signal
import sys
import time
from datetime import datetime
from threading import Event

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.eye_tracker.frame_provider import FrameProvider
from vr_core.eye_tracker.tracker_control import TrackerControl
from vr_core.eye_tracker.tracker_process import TrackerProcess
from vr_core.eye_tracker.tracker_sync import TrackerSync
from vr_core.gaze_v2.gaze_calib import GazeCalib
from vr_core.gaze_v2.gaze_control import GazeControl
from vr_core.gaze_v2.gaze_vector_extractor import GazeVectorExtractor
from vr_core.network.comm_router import CommRouter
from vr_core.network.tcp_server import TCPServer
from vr_core.ports import signals
from vr_core.ports.queues import CommQueues
from vr_core.raspberry_perif.camera_manager import CameraManager
from vr_core.raspberry_perif.esp32 import Esp32
from vr_core.raspberry_perif.imu import Imu
from vr_core.utilities.logger_setup import setup_logger
import vr_core.mock_modules.load_calib_json as ms


def _ensure_session_id() -> str:
    sid = os.environ.get("VR_SESSION_ID")
    if not sid:
        sid = datetime.now().strftime("%H-%M-%S")  # noqa: DTZ005
        os.environ["VR_SESSION_ID"] = sid
    return sid


class Core:
    """Core engine for RPI."""

    def __init__(self, argv: list[str] | None = None) -> None:
        """Initialize VR Core components."""
        #print("Starting VR Core...")

        self.argv = argv or []

        self.engine_timing: str = "None"
        self.processor_timing: str = "None"
        self.frame_provider_timing: bool = False
        self.capture_timing: bool = False

        self.tcp_mock_mode = False
        self.config_mock_mode = False
        self.esp_mock_mode_s = True
        self.imu_mock_mode_s = False
        self.camera_mock_mode = False
        self.fr_pr_test_video = False
        self.use_eyeloop_gui = True
        self.log_calibration = True

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

        _ = _ensure_session_id()
        self.logger.info("All components initialized.")

        self.services: dict[str, BaseService] = {}
        self._stop_requested = Event()

    # -------- build: construct everything & inject dependencies --------

    def build(self) -> None:
        """Build and start all core modules."""
        config = Config(
            config_ready_s=self.config_signals.config_ready_s,
            mock_mode=self.config_mock_mode,
        )

        tcp_server = TCPServer(
            config=config,
            tcp_receive_q=self.queues.tcp_receive_q,
            tcp_client_connected_s=self.comm_router_signals.tcp_client_connected_s,
            stop_requested_s=self._stop_requested,
            config_ready_s=self.config_signals.config_ready_s,
            mock_mode=self.tcp_mock_mode,
        )

        camera_manager = CameraManager(
            config=config,
            mock_mode=self.camera_mock_mode,
        )

        esp32 = Esp32(
            esp_cmd_q=self.queues.esp_cmd_q,
            esp_mock_mode_s=self.esp_mock_mode_s,
            config=config,
        )

        imu = Imu(
            comm_router_q=self.queues.comm_router_q,
            pq_counter=self.queues.pq_counter,
            gyro_mag_q=self.queues.gyro_mag_q,
            imu_signals=self.imu_signals,
            config=config,
            imu_mock_mode_s=self.imu_mock_mode_s,
        )

        tracker_sync = TrackerSync(
            tracker_data_s=self.tracker_data_signals,
            tracker_s=self.tracker_signals,
            comm_router_q=self.queues.comm_router_q,
            pq_counter=self.queues.pq_counter,
            tracker_data_q=self.queues.tracker_data_q,
            tracker_health_q=self.queues.tracker_health_q,
            tracker_response_l_q=self.queues.tracker_resp_l_q,
            tracker_response_r_q=self.queues.tracker_resp_r_q,
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
            use_gui=self.use_eyeloop_gui,
            processor_timing=self.processor_timing,
            engine_timing=self.engine_timing,
        )

        tracker_control = TrackerControl(
            com_router_queue_q=self.queues.comm_router_q,
            pq_counter=self.queues.pq_counter,
            tracker_cmd_l_q=self.queues.tracker_cmd_l_q,
            tracker_cmd_r_q=self.queues.tracker_cmd_r_q,
            comm_router_signals=self.comm_router_signals,
            tracker_data_signals=self.tracker_data_signals,
            tracker_signals=self.tracker_signals,
            i_tracker_process=tracker_process,
            config=config,
        )

        frame_provider = FrameProvider(
            i_camera_manager=camera_manager,
            i_tracker_control=tracker_control,
            comm_router_s=self.comm_router_signals,
            eye_tracker_s=self.eye_ready_signals,
            tracker_s=self.tracker_signals,
            tracker_cmd_l_q=self.queues.tracker_cmd_l_q,
            tracker_cmd_r_q=self.queues.tracker_cmd_r_q,
            config=config,
            use_test_video=self.fr_pr_test_video,
            frame_provider_timing=self.frame_provider_timing,
            capture_timing=self.capture_timing,
        )

        gaze_calib = GazeCalib(
            eye_vector_q=self.queues.eye_vector_q,
            comm_router_q=self.queues.comm_router_q,
            pq_counter=self.queues.pq_counter,
            gaze_signals=self.gaze_signals,
            config=config,
            use_logger=self.log_calibration,
        )

        gaze_v_e = GazeVectorExtractor(
            tracker_data_q=self.queues.tracker_data_q,
            eye_vector_q=self.queues.eye_vector_q,
            comm_router_q=self.queues.comm_router_q,
            pq_counter=self.queues.pq_counter,
            gaze_signals=self.gaze_signals,
            imu_send_to_gaze_signal=self.imu_signals.imu_send_to_gaze_s,
            config=config,
        )

        gaze_control = GazeControl(
            gaze_signals=self.gaze_signals,
            imu_signals=self.imu_signals,
            i_gaze_calib=gaze_calib,
            config=config,
        )

        comm_router = CommRouter(
            i_tcp_server=tcp_server,
            i_gaze_control=gaze_control,
            i_gaze_service=gaze_calib,
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
            "TrackerProcess": tracker_process,
            "TrackerSync": tracker_sync,
            "TrackerControl": tracker_control,
            "FrameProvider": frame_provider,
            "GazeVectorExtractor": gaze_v_e,
            "GazeCalib": gaze_calib,
            "GazeControl": gaze_control,
        }

    # ------------------------ lifecycle: start/stop ---------------------

    def start(self) -> None:
        """Start services in dependency order, waiting for readiness on each."""
        self.logger.info("Starting services.")
        if not self.services:
            self.logger.warning("No services registered. "
                "Did you forget to call build() or wire them?")
            return

        # Order listed in build()
        start_order: list[str] = list(self.services.keys())
        #self.logger.info("Starting services in order: %s", " -> ".join(start_order))

        # Wait for the service to declare readiness
        for name in start_order:
            svc = self.services[name]
            #self.logger.info("-> start %s", name)

            if name in {"TCPServer", "ConfigService"}:  # noqa: SIM108
                # TCP server needs longer timeout since client may take time to connect
                timeout = 120
                #timeout = float("inf")
            else:
                timeout = 5

            svc.start()
            status = self._wait_ready_or_stop(svc, timeout=timeout)

            if status == "stopped":
                self.logger.warning("Startup interrupted during %s; stopping…", name)
                return
            if status == "timeout":
                self.logger.error("Service '%s' did not become ready in time: %ss", name, timeout)
                self._stop_requested.set()
                return

        self.logger.info("All services started and ready.")


    def stop(self) -> None:  # noqa: C901
        """Stop services in reverse order and join them."""
        if not self.services:
            return

        stop_order = list(reversed(self.services.keys()))
        #self.logger.info("Stopping services in reverse order: %s", " <- ".join(stop_order))

        # Request stop
        for name in stop_order:
            svc = self.services[name]

            try:
                #self.logger.info("-> stop %s", name)
                svc.stop()
            except (RuntimeError, ValueError, OSError) as e:
                # Common states: not started, already closed, socket already closed
                self.logger.warning("Benign stop error in %s: %s", name, e, exc_info=True)
                continue
            except Exception:  # pylint: disable=broad-except
                self.logger.exception("Unexpected error calling stop() on %s", name)
                continue

            try:
                # BaseService now exposes stopped() and alive
                if getattr(svc, "alive", False):
                    # Wait on the stopped event first
                    if hasattr(svc, "stopped"):
                        ok = svc.stopped(timeout=5.0)
                        if not ok:
                            self.logger.error("%s did not report stopped within 5s.", name)
                    else:
                        # Fallback: use join if stopped() is not available
                        svc.join(timeout=5.0)

                    # Verify thread status if possible
                    if getattr(svc, "alive", False):
                        self.logger.error("%s did not stop within 5s (still alive).", name)

            except (RuntimeError, ValueError) as e:
                self.logger.warning("Join/stop wait error in %s: %s", name, e, exc_info=True)
            except Exception:  # pylint: disable=broad-except
                self.logger.exception("Unexpected exception waiting for %s to stop", name)

        self.logger.info("All services stopped.")


    def wait_forever(self) -> None:
        """Idle loop for the supervisor. Add supervision/restarts here later if needed."""
        #self.logger.info("Waiting for services to stop...")
        cycle_count = 0
        try:
            while not self._stop_requested.is_set():
                tracker_control = self.services.get("TrackerControl")
                if not isinstance(tracker_control, TrackerControl):
                    return
                cycle_count += 1
                time.sleep(0.5)
                if cycle_count == 1:
                    tracker_control.tracker_control({"mode": "online"})

                if cycle_count == 6:
                    ms.load_calib_json(
                        comm_router_q=self.queues.comm_router_q,
                        pq_counter=self.queues.pq_counter,
                    )


        except KeyboardInterrupt:
            # If SIGINT wasn't caught by handler, catch the raw KeyboardInterrupt
            self.logger.info("KeyboardInterrupt received, shutting down…")
            self._stop_requested.set()


    # --------------------------- helpers ---------------------------

    def _wait_ready_or_stop(self, svc: BaseService, timeout: float | None) -> str:
        """Wait until a service is ready; return 'ready', 'stopped', or 'timeout'."""
        slice_s = 0.05
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            if self._stop_requested.is_set():
                return "stopped"

            # compute remaining time if any
            if deadline is None:
                chunk = slice_s
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return "timeout"
                chunk = min(slice_s, remaining)

            # wait a short slice on the service's ready Event
            if svc.ready(timeout=chunk):
                return "ready"


    # --------------------------- signal hooks --------------------------

    def install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""

        def _handler(
            signum: int,
            _frame: object,
        ) -> None:
            """Signal handler to request shutdown."""
            self.logger.info("Signal %s received, shutting down…", signum)
            self._stop_requested.set()

        signal.signal(signal.SIGINT, _handler)
        try:  # noqa: SIM105
            signal.signal(signal.SIGTERM, _handler)
        except (AttributeError, OSError):
            # Not available on some platforms (e.g., Windows older Pythons)
            pass


# ------------------------------ Entrypoint -----------------------------

def main(argv: list[str] | None = None) -> int:
    """Run the main entrypoint for the VR Core application."""
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
