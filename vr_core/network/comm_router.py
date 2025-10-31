"""Communication router module."""

from typing import Callable, Dict, Any, Optional
from queue import PriorityQueue
from multiprocessing.shared_memory import SharedMemory
from multiprocessing.synchronize import Event as MpEvent
import queue
import json
import threading
from threading import Event

import numpy as np

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.network.comm_contracts import MessageType
import vr_core.network.routing_table as routing_table
import vr_core.network.image_encoder as image_encoder
from vr_core.ports.interfaces import IImuService, IGazeService, ITrackerService, INetworkService
from vr_core.ports.signals import CommRouterSignals, TrackerSignals, ConfigSignals


class CommRouter(BaseService):
    """Communication router for handling incoming messages."""

    def __init__(
        self,
        i_tcp_server: INetworkService,
        i_imu: IImuService,
        i_gaze_control: IGazeService,
        i_tracker_control: ITrackerService,
        com_router_queue_q: PriorityQueue,
        tcp_receive_q: queue.Queue,
        esp_cmd_q: queue.Queue,
        comm_router_s: CommRouterSignals,
        tracker_signals: TrackerSignals,
        config_signals: ConfigSignals,
        config: Config,
    ) -> None:
        super().__init__(name="CommRouter")

        # Initialize interfaces
        self.i_tcp_server = i_tcp_server
        self.i_imu = i_imu
        self.i_gaze_control = i_gaze_control
        self.i_tracker_control = i_tracker_control

        # Initialize queues
        self.com_router_queue_q = com_router_queue_q
        self.tcp_receive_q = tcp_receive_q
        self.esp_cmd_q = esp_cmd_q

        # Initialize shared memory signals
        self.tcp_send_enabled_s: Event = comm_router_s.tcp_send_enabled
        self.frame_ready_s: Event = comm_router_s.frame_ready
        self.sync_frames_s: Event = comm_router_s.sync_frames
        self.comm_shm_is_closed_s: Event = comm_router_s.comm_shm_is_closed

        self.shm_active_s: MpEvent = tracker_signals.shm_active
        self.eye_ready_l_s: MpEvent = tracker_signals.eye_ready_l
        self.eye_ready_r_s: MpEvent = tracker_signals.eye_ready_r

        self.config_ready_s: Event = config_signals.config_ready

        # Initialize config
        self.cfg = config

        # Initialize routing table
        self.routing_table: Dict[MessageType, Callable[[Any], None]] = {}

        # Worker threads
        self._t_recv: threading.Thread
        self._t_send: threading.Thread
        self._t_shm: threading.Thread

        # Shared memory handles
        self.shm_left: SharedMemory | None = None
        self.shm_right: SharedMemory | None = None

        self.memory_shape_l: tuple[int, int]
        self.memory_shape_r: tuple[int, int]

        # SHM and online state
        self.online = False


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Initialize routing table and mark as ready."""
        self.routing_table = routing_table.build_routing_table(
            i_imu=self.i_imu,
            i_gaze_control=self.i_gaze_control,
            i_tracker_control=self.i_tracker_control,
            esp_cmd_q=self.esp_cmd_q,
            config=self.cfg,
            config_ready=self.config_ready_s
        )

        self._copy_settings_to_local()

        self.online = True

        # Start worker threads
        self._t_recv = threading.Thread(
            target=self._tcp_receive_loop,
            name="CommRouter-recv",
            daemon=True
        )
        self._t_send = threading.Thread(
            target=self._tcp_send_loop,
            name="CommRouter-send",
            daemon=True
        )
        self._t_shm = threading.Thread(
            target=self._tcp_send_shm_loop,
            name="CommRouter-shm",
            daemon=True
        )

        self.comm_shm_is_closed_s.set()

        self._t_recv.start()
        self._t_send.start()
        self._t_shm.start()

        self._ready.set()


    def _run(self) -> None:
        # Supervise until stop requested
        while not self._stop.wait(0.2):
            pass


    def _on_stop(self) -> None:
        """Signal threads to stop, close sockets, and join threads."""
        self.online = False

        if not self.comm_shm_is_closed_s.is_set():
            self._disconnect_shm()

        # Join workers (best-effort)
        for t in (
            getattr(self, "_t_recv", None), \
            getattr(self, "_t_send", None), \
            getattr(self, "_t_shm", None)
        ):

            if t:
                t.join(timeout=1.0)


    def is_online(self) -> bool:
        """Check connection and lifecycle state"""
        return self.online and self._thread.is_alive() and self._ready.is_set() and not self._fatal


    # ---------------- Worker loops ----------------

    def _tcp_receive_loop(self) -> None:
        """Handle incoming TCP messages on the tcp_receive_q by routing them based on priority."""
        while not self._stop.is_set():
            try:
                payload, msg_type = self.tcp_receive_q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._tcp_receive_handler(payload, msg_type)
            except Exception as e:  # pylint: disable=broad-except
                print(f"[CommRouter] recv handler error for {msg_type}: {e}")


    # ruff: noqa: F841
    # pylint: disable=unused-variable
    def _tcp_send_loop(self) -> None:
        """Drains com_router_queue_q and sends messages to Unity via TCPServer."""
        # Expected item format: payload: Any, priority: int, msg_type: MessageType
        while not self._stop.is_set():
            try:
                item = self.com_router_queue_q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                # Accept either tuple (priority, msg_type, payload)
                priority: Optional[int] = None
                msg_type = None
                payload: Any = None

                if isinstance(item, tuple) and len(item) >= 3:
                    priority, msg_type, payload = item[0], item[1], item[2]
                else:
                    print("[CommRouter] Unknown send queue item format:", type(item))
                    continue

                self._tcp_send_handler(payload, msg_type)
            except Exception as e:  # pylint: disable=broad-except
                print(f"[CommRouter] send handler error: {e}")


    def _tcp_send_shm_loop(self) -> None:
        """If set, loads image from shared memory, encodes it, and sends it over TCP."""

        while not self._stop.is_set():

            # If TCP sending is disabled, wait and continue
            if not self.tcp_send_enabled_s.is_set():

                # If SHM is not closed, but sending disabled, disconnect
                if not self.comm_shm_is_closed_s.is_set():
                    self._disconnect_shm()
                self._stop.wait(0.1)
                continue

            # If SHM is active and not connected, connect
            if self.shm_active_s.is_set():
                if self.comm_shm_is_closed_s.is_set():
                    self._connect_shm()

            # If SHM is not active and connected, disconnect
            else:
                if not self.comm_shm_is_closed_s.is_set():
                    self._disconnect_shm()
                continue

            # If frame is not ready, wait and continue
            if not self.frame_ready_s.is_set():
                self._stop.wait(0.05)
                continue

            # If ready, ack and send frame
            try:
                self.frame_ready_s.clear()
                self._tcp_send_shm_handler()

                # If in camera preview mode, signal both eyes are ready
                if self.sync_frames_s.is_set():
                    self.eye_ready_l_s.set()
                    self.eye_ready_r_s.set()

            except Exception as e:  # pylint: disable=broad-except
                print(f"[CommRouter] shm send handler error: {e}")

    # ---------------- Handlers ----------------

    def _tcp_receive_handler(self, payload: bytes, msg_type: MessageType) -> None:
        """Decodes inbound payload (usually JSON) and routes to the appropriate local handler."""
        # Map msg_type to handler
        handler = self.routing_table.get(msg_type)
        if handler is None:
            print(f"[CommRouter] No handler for MessageType {msg_type}")
            return

        msg_obj: Any
        # Many control/config messages are JSON; if this fails, fall back to bytes.
        try:
            msg_obj = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            msg_obj = payload  # let handler decide
            print(f"[CommRouter] JSON decode error for {msg_type}: {e}")

        handler(msg_obj)


    def _tcp_send_handler(self, payload: Any, msg_type: MessageType) -> None:
        """Encodes application objects to bytes and uses TCPServer to send them out."""
        # Encode to bytes (default JSON)
        body: bytes
        if msg_type == MessageType.trackerPreview:
            try:
                body = image_encoder.encode_images_packet(
                    items=payload,
                    codec="png",
                    png_compression=self.cfg.tracker.png_compression,
                    color_is_bgr=True  # Assuming images in payload are BGR
                )
            except Exception as e:  # pylint: disable=broad-except
                print(f"[CommRouter] encode failed: {e} for png")
                return
        elif isinstance(payload, (bytes, bytearray, memoryview)):
            body = bytes(payload)
        else:
            try:
                body = json.dumps(payload).encode("utf-8")
            except (TypeError, ValueError) as e:
                print(f"[CommRouter] JSON encode failed for {msg_type}: {e}")
                return

        # Push to the socket through the TCPServer interface. :contentReference[oaicite:7]{index=7}
        self.i_tcp_server.tcp_send(body, msg_type)


    def _tcp_send_shm_handler(self) -> None:
        """Loads image from shared memory, encodes it, and sends it over TCP."""
        # Load left and right image from shared memory to an array with shape from config
        if not self.shm_left or not self.shm_right:
            print("[CommRouter] SHM not connected properly.")
            return

        left_image: np.ndarray = np.ndarray(
            shape=self.memory_shape_l,
            dtype=np.uint8,
            buffer=self.shm_left.buf).copy()
        right_image: np.ndarray = np.ndarray(
            shape=self.memory_shape_r,
            dtype=np.uint8,
            buffer=self.shm_right.buf).copy()

        try:
            # Encode using image_encoder
            encoded_payload = image_encoder.encode_images_packet(
                items=[(0, left_image), (1, right_image)],
                codec="jpeg",
                jpeg_quality=self.cfg.tracker.jpeg_quality,
                color_is_bgr=True  # Assuming images in SHM are BGR
            )
        except Exception as e:  # pylint: disable=broad-except
            print(f"[CommRouter] encode failed: {e} for jpeg")
            return

        # Send using i_tcp_server.tcp_send()
        self.i_tcp_server.tcp_send(encoded_payload, MessageType.eyePreview)


    # --- SHM handling methods ---

    def _copy_settings_to_local(self):
        """Copies/binds memory shapes to local variables."""
        self.memory_shape_l = self.cfg.tracker.memory_shape_l
        self.memory_shape_r = self.cfg.tracker.memory_shape_r


    def _reconfigure_shm(self):
        """Reconnects to shared memory using a new configuration."""
        self._disconnect_shm()
        self._copy_settings_to_local()
        self._connect_shm()


    def _connect_shm(self):
        """Establish connection to shared memory."""
        if not self.comm_shm_is_closed_s.is_set():
            print("[CommRouter] SHM already connected.")
            return

        shm_left = shm_right = None
        try:
            shm_left = SharedMemory(name=self.cfg.tracker.sharedmem_name_left)
            shm_right = SharedMemory(name=self.cfg.tracker.sharedmem_name_right)
        except FileNotFoundError:
            if shm_left:
                shm_left.close()
            if shm_right:
                shm_right.close()
            print("[ERROR] TrackerCenter: Shared memory not found for preview loop.")
            return

        self.shm_left, self.shm_right = shm_left, shm_right
        self.comm_shm_is_closed_s.clear()


    def _disconnect_shm(self):
        """Disconnect from shared memory."""
        if self.comm_shm_is_closed_s.is_set():
            print("[CommRouter] SHM not connected; cannot disconnect.")
            return

        if self.shm_left:
            self.shm_left.close()
            self.shm_left = None
        else:
            print("[CommRouter] SHM left was already None.")

        if self.shm_right:
            self.shm_right.close()
            self.shm_right = None
        else:
            print("[CommRouter] SHM right was already None.")

        self.comm_shm_is_closed_s.set()
