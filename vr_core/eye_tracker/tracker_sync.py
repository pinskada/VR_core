"""Handles the communication between the EyeLoop processes and the main process."""

import queue
import multiprocessing as mp
from enum import Enum
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from vr_core.network.comm_contracts import MessageType
from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.signals import TrackerDataSignals


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
    left: Optional[_HalfFrame] = None
    right: Optional[_HalfFrame] = None

    def complete(self) -> bool:
        """Returns True if both left and right halves are present."""
        return self.left is not None and self.right is not None


class TrackerSync(BaseService):
    """
    Receives messages from EyeLoop processes and routes them to the appropriate queues.
    Synchronizes frames between left and right EyeLoop processes.
    """

    def __init__(
        self,
        tracker_data_s: TrackerDataSignals,
        comm_router_q: queue.PriorityQueue,
        gaze_data_q: queue.Queue,
        tracker_health_q: queue.Queue,
        tracker_response_l_q: mp.Queue,
        tracker_response_r_q: mp.Queue,
        config: Config
    ) -> None:
        super().__init__(name="TrackerSync")

        # Signal events for output data control
        self.log_data_s = tracker_data_s.log_data
        self.provide_data_s = tracker_data_s.provide_data

        # Queues for outputting data
        self.comm_router_q = comm_router_q
        self.gaze_data_q = gaze_data_q

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
        self._eye_data_buf: Dict[int, _SyncBucket] = {}
        self._image_buf: Dict[int, _SyncBucket] = {}

        self.online = False


# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Initializes the QueueHandler service."""

        self._t_left = threading.Thread(
            target=self._response_loop,
            name="eye-left-rx",
            args=(self.tracker_response_l_q, Eye.LEFT),
            daemon=True
        )
        self._t_right = threading.Thread(
            target=self._response_loop,
            name="eye-right-rx",
            args=(self.tracker_response_r_q, Eye.RIGHT),
            daemon=True
        )
        self._t_left.start()
        self._t_right.start()
        self.online = True
        self._ready.set()


    def _run(self) -> None:
        """Main loop for the QueueHandler service."""
        while not self._stop.is_set():
            self._stop.wait(0.1)


    def _on_stop(self) -> None:
        """Cleans up the QueueHandler service."""
        self.online = False
        for t in (self._t_left, self._t_right):
            if t and t.is_alive():
                t.join(timeout=0.5)


# ---------- Internals ----------

    def _response_loop(
        self,
        response_queue: mp.Queue,
        eye: Eye
    ) -> None:
        """Loop to handle responses from EyeLoop processes."""

        while not self._stop.is_set():
            try:
                msg = response_queue.get(timeout=self.cfg.tracker.resp_q_timeout)
            except queue.Empty:
                # Nothing to read this tick
                continue

            try:
                self._dispatch_message(msg, eye)
            except (KeyError, ValueError, TypeError) as e:
                print(f"[WARN] TrackerSync: malformed message from {eye}: {e}")


    def _dispatch_message(
        self,
        message: Any,
        eye: Eye
    ) -> None:
        """
        Dispatches a message to the appropriate queue based on its content.
        """

        if isinstance(message, dict):
            payload_type = message.get("type")

            match payload_type:
                case "eye_data":
                    self._try_sync(message, eye, MessageType.trackerData)
                case "image_preview":
                    self._try_sync(message, eye, MessageType.trackerPreview)
                case "health":
                    payload = message.get("payload")
                    self.tracker_health_q.put((payload, eye))
                case _:
                    print("[WARN] TrackerSync: Missing 'payload' in message.")
        else:
            print(f"[WARN] TrackerSync: Unexpected message format: {type(message)}")


    def _try_sync(
        self,
        data: Any,
        eye: Eye,
        message_type: MessageType,
    ) -> None:
        """Attempts to synchronize frames from left and right EyeLoop processes."""

        frame_id = data.get("frame_id")
        payload = data.get("payload")
        if frame_id is None or payload is None:
            # Can't sync without frame_id; drop or log
            print("[WARN] TrackerSync dropping message without frame_id or payload")
            return

        # Select buffer based on payload type
        if message_type is MessageType.trackerData:
            buf = self._eye_data_buf
            lock: threading.Lock = self._eye_lock
        elif message_type is MessageType.trackerPreview:
            buf = self._image_buf
            lock = self._img_lock
        else:
            # if your enum could grow, be explicit so type-checkers know we return here
            raise ValueError(f"[ERROR] TrackerSync: Unexpected message_type: {message_type}")

        # Prevent concurrent access to the buffer
        with lock:
            # Fetch/create bucket for this frame_id
            bucket = buf.get(frame_id)
            if bucket is None:
                bucket = _SyncBucket()
                buf[frame_id] = bucket

            half = _HalfFrame(data=payload)

            if eye == Eye.LEFT:
                bucket.left = half
            else:
                bucket.right = half

            if bucket.complete():
                left = bucket.left
                right = bucket.right
                if left is None or right is None:
                    return

                # Both halves are present; forward the paired data
                pair = (left.data, right.data)

                match message_type:
                    case MessageType.trackerData:
                        # Fan-out based on control signals
                        if self.provide_data_s.is_set():
                            # Send to gaze module
                            self.gaze_data_q.put(pair)

                        if self.log_data_s.is_set():
                            # Send to comm router for logging/telemetry
                            self.comm_router_q.put((5, MessageType.trackerData, pair))
                    case MessageType.trackerPreview:
                        # Forward both images as a pair to CommRouter (it will PNG-encode)
                        self.comm_router_q.put((5, MessageType.trackerPreview, pair))

                # Cleanup consumed bucket
                del buf[frame_id]

            # GC if buffer grew too large
            if len(buf) > self.cfg.tracker.sync_buffer_size:
                self._trim_buffer(buf)


    def _trim_buffer(
        self,
        buf: Dict[int, _SyncBucket],
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

        print(f"[WARN] TrackerSync Trimmed sync buffer by {drop_n} entries.")