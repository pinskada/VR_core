"""Communication router module."""

from typing import Callable, Dict, Any, Optional
from queue import PriorityQueue
from multiprocessing.shared_memory import SharedMemory
import queue
import json
import threading
import numpy as np

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.network.comm_contracts import MessageType
import vr_core.network.routing_table as routing_table
import vr_core.network.image_encoder as image_encoder
from vr_core.ports.interfaces import IImuService, IGazeService, ITrackerService, INetworkService
from vr_core.ports.signals import CommRouterSignals


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
        shm_signals: CommRouterSignals,
        config: Config
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
        self.shm_signals = shm_signals

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

        # SHM and online state
        self.shm_connected = False
        self.online = False


    def _on_start(self) -> None:
        """Initialize routing table and mark as ready."""
        self.routing_table = routing_table.build_routing_table(
            i_imu=self.i_imu,
            i_gaze_control=self.i_gaze_control,
            i_tracker_control=self.i_tracker_control,
            esp_cmd_q=self.esp_cmd_q,
            config=self.cfg
        )

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

        if self.shm_connected:
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


    # ruff: noqa: F401,F841
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
            if not self.shm_signals.tcp_send_enabled.is_set():
                if self.shm_connected:
                    self._disconnect_shm()
                self._stop.wait(0.1)
                continue

            if not self.shm_connected:
                self._connect_shm()
                continue

            if self.shm_signals.shm_reconfig.is_set():
                # Reconfigure shared memory connection here if needed
                self._reconfigure_shm()
                self.shm_signals.shm_reconfig.clear()

            if not self.shm_signals.frame_ready.is_set():
                self._stop.wait(0.01)
                continue
            try:
                self._tcp_send_shm_handler()
            finally:
                self.shm_signals.frame_ready.clear()


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
            shape=self.cfg.tracker.memory_shape_L,
            dtype=np.uint8,
            buffer=self.shm_left.buf).copy()
        right_image: np.ndarray = np.ndarray(
            shape=self.cfg.tracker.memory_shape_R,
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

    def _reconfigure_shm(self):
        """Reconnects to shared memory using a new configuration."""
        self._disconnect_shm()
        self._connect_shm()


    def _connect_shm(self):
        """Establish connection to shared memory."""
        if self.shm_connected:
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
        self.shm_connected = True


    def _disconnect_shm(self):
        """Disconnect from shared memory."""
        if not self.shm_connected:
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

        self.shm_connected = False
