# ruff: noqa: ERA001

"""Handles the communication between the EyeLoop processes and the main process."""

import itertools
import multiprocessing as mp
import queue
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.network.comm_contracts import MessageType
from vr_core.ports.signals import TrackerDataSignals, TrackerSignals
from vr_core.utilities.logger_setup import setup_logger


class Eye(Enum):
    """Enum for eye identification."""

    LEFT = 0
    RIGHT = 1


@dataclass
class _HalfFrame:
    """Holds data for one half of a frame."""

    data: Any


@dataclass
class _SyncBucket:
    """Holds L/R halves for a given frame_id."""

    left: _HalfFrame | None = None
    right: _HalfFrame | None = None

    def complete(self) -> bool:
        """Returns True if both left and right halves are present."""
        return self.left is not None and self.right is not None


class TrackerSync(BaseService):
    """Receives messages from EyeLoop processes and routes them to the appropriate queues.
    Synchronizes frames between left and right EyeLoop processes.
    """

    def __init__(
        self,
        tracker_data_s: TrackerDataSignals,
        tracker_s: TrackerSignals,
        comm_router_q: queue.PriorityQueue,
        pq_counter: itertools.count,
        tracker_data_q: queue.Queue,
        tracker_health_q: queue.Queue,
        tracker_response_l_q: mp.Queue,
        tracker_response_r_q: mp.Queue,
        config: Config,
    ) -> None:
        super().__init__(name="TrackerSync")

        self.logger = setup_logger("TrackerSync")

        # Signal events for output data control
        self.tracker_data_to_tcp_s = tracker_data_s.tracker_data_to_tcp_s
        self.tracker_data_to_gaze_s = tracker_data_s.tracker_data_to_gaze_s

        self.first_frame_processed_l_s = tracker_s.first_frame_processed_l_s
        self.first_frame_processed_r_s = tracker_s.first_frame_processed_r_s

        # Queues for outputting data
        self.comm_router_q = comm_router_q
        self.pq_counter = pq_counter
        self.tracker_data_q = tracker_data_q

        # Queue for forwarding tracker health messages to TrackerProcess
        self.tracker_health_q = tracker_health_q

        # Queues for receiving responses from EyeLoop processes
        self.tracker_response_l_q = tracker_response_l_q
        self.tracker_response_r_q = tracker_response_r_q

        # Configuration
        self.cfg = config

        # Threads
        self._t_left: threading.Thread
        self._t_right: threading.Thread

        self._eye_lock: threading.Lock = threading.Lock()
        self._img_lock: threading.Lock = threading.Lock()


        # Per-kind sync buffers: frame_id -> _SyncBucket
        self._eye_data_buf: dict[int, _SyncBucket] = {}
        self._image_buf: dict[int, _SyncBucket] = {}

        self.print_count = 0

        self.online = False

        #self.logger.info("Service initialized.")


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Initializes the QueueHandler service."""
        self._t_left = threading.Thread(
            target=self._response_loop,
            name="eye-left-rx",
            args=(self.tracker_response_l_q, Eye.LEFT),
            daemon=True,
        )
        self._t_right = threading.Thread(
            target=self._response_loop,
            name="eye-right-rx",
            args=(self.tracker_response_r_q, Eye.RIGHT),
            daemon=True,
        )
        self._t_left.start()
        self._t_right.start()
        self.online = True
        self._ready.set()

        #self.logger.info("Service _ready is set.")


    def _run(self) -> None:
        """Main loop for the QueueHandler service."""
        while not self._stop.is_set():
            self._stop.wait(0.1)


    def _on_stop(self) -> None:
        """Cleans up the QueueHandler service."""
        #self.logger.info("Service stopping.")

        self.online = False
        for t in (self._t_left, self._t_right):
            if t and t.is_alive():
                t.join(timeout=0.5)
                #self.logger.info("Service %s stopped.", t.name)


# ---------- Internals ----------

    def _response_loop(
        self,
        response_queue: mp.Queue,
        eye: Eye,
    ) -> None:
        """Loop to handle responses from EyeLoop processes."""
        #self.logger.info("Service %s started.", eye)

        while not self._stop.is_set():
            try:
                msg = response_queue.get(timeout=self.cfg.tracker.resp_q_timeout)
                #self.logger.info("Received message from %s: %s", eye, msg.get("type"))
            except queue.Empty:
                # Nothing to read this tick
                continue

            #try:
            self._dispatch_message(msg, eye)
            #except (KeyError, ValueError, TypeError) as e:
            #    self.logger.warning("Malformed message from %s: %s", eye, e)


    def _dispatch_message(
        self,
        message: Any,
        eye: Eye,
    ) -> None:
        """Dispatches a message to the appropriate queue based on its content.
        """
        if isinstance(message, dict):
            payload_type = message.get("type")

            match payload_type:
                case "eye_data":
                    #self.logger.info("Dispatching eye_data message from %s eye with ID: %s"
                    #    , eye, message.get("frame_id"))
                    self._try_sync(message, eye, MessageType.trackerData)
                case "image_preview":
                    self._try_sync(message, eye, MessageType.trackerPreview)
                case "health":
                    payload = message.get("payload")
                    self.tracker_health_q.put((payload, eye))
                case _:
                    self.logger.info("Missing 'payload' in message.")
        else:
            self.logger.warning("Unexpected message format: %s", type(message))


    def _extract_image_preview(self, message: dict) -> NDArray[np.uint8] | None:
        h = int(message.get("height", 0))
        w = int(message.get("width", 0))
        bit_map = message.get("bitmap")
        if not h or not w or bit_map is None:
            self.logger.info("No bitmap/size in image_preview message.")
            return None

        # accept bytes or array
        if isinstance(bit_map, (bytes, bytearray, memoryview)):
            packed = np.frombuffer(bit_map, dtype=np.uint8)
        else:
            packed = np.asarray(bit_map, dtype=np.uint8)

        # unpack with the same bit order used when packing
        bits = np.unpackbits(packed, bitorder="big")
        mask01: NDArray[np.uint8] = bits[: h * w].reshape((h, w)).astype(np.uint8)

        # keep dtype uint8 (0 -> 0, 1 -> 255)
        mask255: NDArray[np.uint8] = (mask01 * np.uint8(255)).astype(np.uint8)
        # optional: ensure contiguous for OpenCV
        return np.ascontiguousarray(mask255)



    def _try_sync(
        self,
        message: dict,
        eye: Eye,
        message_type: MessageType,
    ) -> None:
        """Attempts to synchronize frames from left and right EyeLoop processes."""
        frame_id = message.get("frame_id")


        if message_type == MessageType.trackerPreview:
            data = self._extract_image_preview(message)
            if data is not None:
                cv2.imwrite("/tmp/preview_sync.png", data)
        else:
            data = message.get("data")
        #self.logger.info("Received message from %s eye with ID: %s, of type: %s", eye, frame_id, str(message_type))

        # After Eyeloop processed first image, config can be sent
        if message_type is MessageType.trackerData:
            if eye == Eye.LEFT:
                self.first_frame_processed_l_s.set()
                #self.logger.info("first_frame_processed_l_s has been set.")
            else:
                self.first_frame_processed_r_s.set()
                #self.logger.info("first_frame_processed_r_s has been set.")


        if frame_id is None:
            # Can't sync without frame_id; drop or log
            self.logger.warning("Dropping %s message for %s eye without frame_id.",
                message_type, eye)
            return
        if data is None:
            # Can't sync without frame_id; drop or log
            self.logger.warning("Dropping %s message for %s eye, with ID: "
                "%s, without payload", message_type, eye, frame_id)
            return
        if message_type is MessageType.trackerData and data.get("pupil") is None:
            return

        # Select buffer based on payload type
        if message_type is MessageType.trackerData:
            buf = self._eye_data_buf
            lock: threading.Lock = self._eye_lock
            #self.logger.info("Processing tracker data from %s eye with id: %s", eye, frame_id)
        elif message_type is MessageType.trackerPreview:
            buf = self._image_buf
            lock = self._img_lock
            #self.logger.info("Processing tracker preview from %s eye with id: %s", eye, frame_id)
        else:
            # if your enum could grow, be explicit so type-checkers know we return here
            self.logger.error("Unexpected message_type: %s", message_type)
            raise ValueError(f"[ERROR] TrackerSync: Unexpected message_type: {message_type}")

        # Prevent concurrent access to the buffer
        with lock:
            # Fetch/create bucket for this frame_id
            bucket = buf.get(frame_id)
            if bucket is None:
                bucket = _SyncBucket()
                buf[frame_id] = bucket

            half = _HalfFrame(data=data)

            if eye == Eye.LEFT:
                bucket.left = half
            else:
                bucket.right = half

            if bucket.complete():
                left = bucket.left
                right = bucket.right
                if left is None or right is None:
                    return

                if message_type==MessageType.trackerData:

                    if not isinstance(left.data, dict) or not isinstance(right.data, dict):
                        self.logger.warning("Data type error, skipping.")
                        return

                    if not left.data or not right.data:
                        #self.logger.info("Empty pupil data, skipping.")
                        return

                # Both halves are present; forward the paired data
                pair = (left.data, right.data)

                match message_type:
                    case MessageType.trackerData:
                        # Fan-out based on control signals
                        # self.logger.info("Left coordinates: %s", left.data)
                        self.print_count += 1
                        # if self.print_count % 20 == 0:
                            # self.logger.info("%s ; %s", left.data, right.data)
                            # self.logger.info("Right coordinates: %s", right.data)
                        if self.tracker_data_to_gaze_s.is_set():
                            # Send to gaze module
                            self.tracker_data_q.put(pair)

                        if self.tracker_data_to_tcp_s.is_set():
                            left_eye  = self._eye_to_unity_format(left.data)
                            right_eye = self._eye_to_unity_format(right.data)

                            tracker_payload = {
                                "left_eye": left_eye,
                                "right_eye": right_eye,
                            }

                            # Send to comm router for logging/telemetry
                            self.comm_router_q.put((5, next(self.pq_counter),
                                MessageType.trackerData, tracker_payload))
                            #self.logger.info("Sending tracker data over TCP.")

                    case MessageType.trackerPreview:
                        # Forward both images as a pair to CommRouter (it will PNG-encode)
                        self.comm_router_q.put((8, next(self.pq_counter),
                            MessageType.trackerPreview, pair))
                        #self.logger.info("Sending preview images over TCP.")

                # Cleanup consumed bucket
                del buf[frame_id]

            # GC if buffer grew too large
            if len(buf) > self.cfg.tracker.sync_buffer_size:
                self._trim_buffer(buf)


    def _trim_buffer(
        self,
        buf: dict[int, _SyncBucket],
    ) -> None:
        """Trim sync buffers by *size only* (no time-based GC).

        Keeps at most `sync_buffer_size` newest frame_ids in each buffer.
        Assumes frame_id is an increasing integer; if not guaranteed, trimming
        still works but keeps arbitrary newer entries.
        """
        cap = int(self.cfg.tracker.sync_buffer_size)

        if len(buf) <= cap:
            return

        keys = sorted(buf.keys())
        drop_n = len(buf) - cap

        for k in keys[:drop_n]:
            buf.pop(k, None)

        #self.logger.warning("Trimmed sync buffer by %d entries.", drop_n)


    @staticmethod
    def _eye_to_unity_format(eye_dict: dict) -> dict[str, float]:
        """Convert EyeLoop eye data.

        EyeLoop eye data:
        {'pupil': ((cx, cy), rx, ry, something)}
        Unity's EyeData JSON:
        {center_x, center_y, radius_x, radius_y, is_valid}
        """
        pupil = eye_dict.get("pupil")
        if not pupil:
            return {
                "center_x": 0.0,
                "center_y": 0.0,
                "radius_x": 0.0,
                "radius_y": 0.0,
                "is_valid": False,
            }

        # pupil = ((cx, cy), rx, ry, _)
        (cx, cy), rx, ry, *_ = pupil

        return {
            "center_x": float(cx),
            "center_y": float(cy),
            "radius_x": float(rx),
            "radius_y": float(ry),
            "is_valid": True,
        }
