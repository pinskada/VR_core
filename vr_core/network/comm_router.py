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
from vr_core.ports.interfaces import IGazeControl, ITrackerControl, INetworkService
from vr_core.ports.signals import CommRouterSignals, TrackerSignals, ConfigSignals, IMUSignals
from vr_core.utilities.logger_setup import setup_logger

class CommRouter(BaseService):
    """Communication router for handling incoming messages."""

    def __init__(
        self,
        i_tcp_server: INetworkService,
        i_gaze_control: IGazeControl,
        i_tracker_control: ITrackerControl,
        com_router_queue_q: PriorityQueue,
        tcp_receive_q: queue.Queue,
        esp_cmd_q: queue.Queue,
        imu_signals: IMUSignals,
        comm_router_signals: CommRouterSignals,
        tracker_signals: TrackerSignals,
        config_signals: ConfigSignals,
        config: Config,
    ) -> None:
        super().__init__(name="CommRouter")

        self.logger = setup_logger("CommRouter")

        # Initialize interfaces
        self.i_tcp_server = i_tcp_server
        self.i_gaze_control = i_gaze_control
        self.i_tracker_control = i_tracker_control

        # Initialize queues
        self.com_router_queue_q = com_router_queue_q
        self.tcp_receive_q = tcp_receive_q
        self.esp_cmd_q = esp_cmd_q


        # Initialize shared memory signals
        self.tcp_shm_send_s: Event = comm_router_signals.tcp_shm_send_s
        self.router_frame_ready_s: Event = comm_router_signals.router_frame_ready_s
        self.router_sync_frames_s: Event = comm_router_signals.router_sync_frames_s
        self.router_shm_is_closed_s: Event = comm_router_signals.router_shm_is_closed_s
        self.tcp_client_connected_s: Event = comm_router_signals.tcp_client_connected_s

        self.shm_active_s: MpEvent = tracker_signals.shm_active_s
        self.eye_ready_l_s: MpEvent = tracker_signals.eye_ready_l_s
        self.eye_ready_r_s: MpEvent = tracker_signals.eye_ready_r_s

        self.config_ready_s: Event = config_signals.config_ready_s

        self.imu_send_to_gaze_s: Event = imu_signals.imu_send_over_tcp_s

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

        #self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Initialize routing table and mark as ready."""
        self.routing_table = routing_table.build_routing_table(
            imu_s=self.imu_send_to_gaze_s,
            i_gaze_control=self.i_gaze_control,
            i_tracker_control=self.i_tracker_control,
            esp_cmd_q=self.esp_cmd_q,
            config=self.cfg,
            config_ready_s=self.config_ready_s
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

        self.router_shm_is_closed_s.set()

        self._t_recv.start()
        self._t_send.start()
        self._t_shm.start()

        self._ready.set()

        #self.logger.info("Service is ready.")


    def _run(self) -> None:
        # Supervise until stop requested
        while not self._stop.wait(0.2):
            pass


    def _on_stop(self) -> None:
        """Signal threads to stop, close sockets, and join threads."""

        #self.logger.info("Service is stopping.")
        self.online = False

        if not self.router_shm_is_closed_s.is_set():
            self._disconnect_shm()

        # Join workers (best-effort)
        for t in (
            getattr(self, "_t_recv", None), \
            getattr(self, "_t_send", None), \
            getattr(self, "_t_shm", None)
        ):

            if t:
                t.join(timeout=1.0)
                #self.logger.info("Service %s has stopped.", t.name)


    def is_online(self) -> bool:
        """Check connection and lifecycle state"""
        return self.online and self._thread.is_alive() and self._ready.is_set() and not self._fatal


    # ---------------- Worker loops ----------------

    def _tcp_receive_loop(self) -> None:
        """Handle incoming TCP messages on the tcp_receive_q by routing them based on priority."""
        #self.logger.info("_tcp_receive_loop has started.")

        while not self._stop.is_set():
            try:
                payload, msg_type = self.tcp_receive_q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self._tcp_receive_handler(payload, msg_type)
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error("recv handler error for %s: %s", msg_type, e)
                self.logger.info("payload: %f", payload)


    # ruff: noqa: F841
    # pylint: disable=unused-variable
    def _tcp_send_loop(self) -> None:
        """Drains com_router_queue_q and sends messages to Unity via TCPServer."""
        #self.logger.info("_tcp_send_loop has started.")

        # Expected item format: payload: Any, priority: int, msg_type: MessageType
        while not self._stop.is_set():
            try:
                item = self.com_router_queue_q.get(timeout=0.1)
            except queue.Empty:
                #self.logger.info("com_router_queue_q is empty.")
                continue

            if not self.tcp_client_connected_s.is_set():
                continue

            try:
                # Accept either tuple (priority, msg_type, payload)
                priority: Optional[int] = None
                msg_type = None
                payload: Any = None

                if isinstance(item, tuple) and len(item) == 4:
                    priority, _, msg_type, payload = item[0], item[1], item[2], item[3]
                    #self.logger.info("MessageType: %s being sent to Unity", msg_type)
                else:
                    self.logger.error("Unknown send queue item format: %s", type(item))
                    continue

                self._tcp_send_handler(payload, msg_type)
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error("send handler error: %s", e)


    def _tcp_send_shm_loop(self) -> None:
        """If set, loads image from shared memory, encodes it, and sends it over TCP."""
        #self.logger.info("_tcp_send_shm_loop has started.")

        while not self._stop.is_set():

            # If TCP sending is disabled, wait and continue
            if not self.tcp_shm_send_s.is_set():

                # If SHM is not closed, but sending disabled, disconnect
                if not self.router_shm_is_closed_s.is_set():
                    self._disconnect_shm()
                self._stop.wait(0.1)
                continue

            # If SHM is active and not connected, connect
            if self.shm_active_s.is_set():
                if self.router_shm_is_closed_s.is_set():
                    self._copy_settings_to_local()
                    self._connect_shm()

            # If SHM is not active and connected, disconnect
            else:
                if not self.router_shm_is_closed_s.is_set():
                    self._disconnect_shm()
                continue

            # If frame is not ready, wait and continue
            if not self.router_frame_ready_s.is_set():
                self._stop.wait(0.05)
                continue

            # If ready, ack and send frame
            try:
                self.router_frame_ready_s.clear()
                #self.logger.info("router_frame_ready_s cleared.")
                if self.tcp_client_connected_s.is_set():
                    self._tcp_send_shm_handler()

                # If in camera preview mode, signal both eyes are ready
                if self.router_sync_frames_s.is_set():
                    self.eye_ready_l_s.set()
                    self.eye_ready_r_s.set()
                    #self.logger.info("eye_ready_l_s and eye_ready_r_s set.")

            except Exception as e:  # pylint: disable=broad-except
                self.logger.error("shm send handler error: %s", e)

    # ---------------- Handlers ----------------

    def _tcp_receive_handler(self, payload: bytes, msg_type: MessageType) -> None:
        """Decodes inbound payload (usually JSON) and routes to the appropriate local handler."""
        # Map msg_type to handler
        handler = self.routing_table.get(msg_type)
        if handler is None:
            self.logger.error("No handler for MessageType %s", msg_type)
            return

        msg_obj: Any
        # Many control/config messages are JSON; if this fails, fall back to bytes.
        try:
            msg_obj = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            msg_obj = payload  # let handler decide
            self.logger.error("JSON decode error for %s: %s", msg_type, e)

        handler(msg_obj)


    def _tcp_send_handler(self, payload: Any, msg_type: MessageType) -> None:
        """Encodes application objects to bytes and uses TCPServer to send them out."""
        # Encode to bytes (default JSON)
        body: bytes
        preview_iterable = [(0, payload[0]), (1, payload[1])]

        if msg_type == MessageType.trackerPreview:
            try:
                body = image_encoder.encode_images_packet(
                    items=preview_iterable,
                    codec="png",
                    png_compression=self.cfg.tracker.png_compression,
                    color_is_bgr=True  # Assuming images in payload are BGR
                )
            except Exception as e:  # pylint: disable=broad-except
                self.logger.error("encode failed: %s for png", e)
                return
        elif isinstance(payload, (bytes, bytearray, memoryview)):
            body = bytes(payload)
        else:
            try:
                body = json.dumps(payload).encode("utf-8")
            except (TypeError, ValueError) as e:
                self.logger.error("JSON encode failed for %s: %s", msg_type, e)
                return

        # Push to the socket through the TCPServer interface. :contentReference[oaicite:7]{index=7}
        self.i_tcp_server.tcp_send(body, msg_type)
        #self.logger.info("Sent tracker preview image.")


    def _tcp_send_shm_handler(self) -> None:
        """Loads image from shared memory, encodes it, and sends it over TCP."""
        # Load left and right image from shared memory to an array with shape from config
        if not self.shm_left or not self.shm_right:
            self.logger.error("SHM not connected properly.")
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
                jpeg_quality=self.cfg.camera.jpeg_quality,
                color_is_bgr=True  # Assuming images in SHM are BGR
            )
        except Exception as e:  # pylint: disable=broad-except
            self.logger.error("Encode failed: %s for jpeg", e)
            return

        # Send using i_tcp_server.tcp_send()
        self.i_tcp_server.tcp_send(encoded_payload, MessageType.eyePreview)
        #self.logger.info("Sent eyePreview message over TCP.")


    # --- SHM handling methods ---

    def _copy_settings_to_local(self):
        """Copies/binds memory shapes to local variables."""
        self.memory_shape_l = self.cfg.tracker.memory_shape_l
        self.memory_shape_r = self.cfg.tracker.memory_shape_r
        if self._ready.is_set():
            self.logger.info("Local memory shapes copied.")


    def _connect_shm(self):
        """Establish connection to shared memory."""
        if not self.router_shm_is_closed_s.is_set():
            self.logger.info("router_shm_is_closed_s is already cleared.")
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
            self.logger.error("TrackerCenter: Shared memory not found for preview loop.")
            return

        self.shm_left, self.shm_right = shm_left, shm_right
        self.router_shm_is_closed_s.clear()
        self.logger.info("router_shm_is_closed_s has been cleared.")


    def _disconnect_shm(self):
        """Disconnect from shared memory."""
        if self.router_shm_is_closed_s.is_set():
            self.logger.info("router_shm_is_closed_s is already set.")
            return

        if self.shm_left:
            self.shm_left.close()
            self.shm_left = None
        else:
            self.logger.info("Left SHM was already closed.")

        if self.shm_right:
            self.shm_right.close()
            self.shm_right = None
        else:
            self.logger.info("Right SHM was already closed.")

        self.router_shm_is_closed_s.set()
        self.logger.info("router_shm_is_closed_s has been set.")
