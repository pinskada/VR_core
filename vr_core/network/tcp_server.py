"""Cross-platform TCP server for Unity."""

import socket
import queue
import time

from vr_core.base_service import BaseService
from vr_core.ports.interfaces import INetworkService
from vr_core.config_service.config import Config
from vr_core.network.comm_contracts import MessageType
from vr_core.utilities.logger_setup import setup_logger

class TCPServer(BaseService, INetworkService):
    """
    Cross-platform TCP server for Unity client.
    """

    def __init__(
        self,
        config: Config,
        tcp_receive_q: queue.Queue
    ) -> None:
        super().__init__(name="TCPServer")

        self.logger = setup_logger("TCPServer")

        self.cfg = config
        self.tcp_receive_q = tcp_receive_q

        self.online = False

        # Internal state
        self.server_socket: socket.socket | None = None
        self.client_conn: socket.socket | None = None
        self.client_addr: tuple[str, int] | None = None

        self._buf = bytearray()

        self.logger.info("Service initialized.")


    def _on_start(self) -> None:
        """Set up server socket and wait for client connection."""

        self._verify_static_ip()

        if not self._start_server():
            return

        # Mark as ready
        self._ready.set()
        self.logger.info("Service _ready is set.")


    def _run(self) -> None:
        while not self._stop.is_set():

            self._receive()
            self._stop.wait(self.cfg.tcp.receive_loop_interval)


    def _on_stop(self) -> None:
        """Signal threads to stop, close sockets, and join threads."""
        self.online = False

        self.logger.info("Service is stopping.")

        # Close sockets to unblock accept/recv
        if self.client_conn:
            try:
                self.client_conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.client_conn.close()

        self.client_addr = None

        if self.server_socket:
            try:
                self.server_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            self.server_socket.close()


    def is_online(self) -> bool:
        """Check connection and lifecycle state"""
        return self.online and self._thread.is_alive() and self._ready.is_set() and not self._fatal


    def _verify_static_ip(self) -> bool:
        """Optional check: does our local IP match the expected static prefix?"""
        expected_prefix=self.cfg.tcp.static_ip_prefix
        test_sock = None
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.connect((self.cfg.tcp.google_dns, self.cfg.tcp.http_port))
            ip = test_sock.getsockname()[0]
        except OSError as e:
            self.logger.warning("IP check failed: %s", e)
            return False
        finally:
            if test_sock:
                test_sock.close()

        if ip.startswith(expected_prefix):
            self.logger.info("IP OK: %s", ip)
            return True
        self.logger.warning("Unexpected IP %s, expected prefix %s", ip, expected_prefix)
        return False


    def _start_server(self) -> bool:
        # Create, bind, and listen
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.cfg.tcp.host, self.cfg.tcp.port))
        self.server_socket.listen(1)
        self.server_socket.settimeout(1.0)

        self.logger.info("Waiting for Unity on %s:%d...", self.cfg.tcp.host, self.cfg.tcp.port)
        start = time.time()
        deadline = self.cfg.tcp.connect_timeout
        infinite_timeout = deadline == -1

        while not self.stop_requested:
            try:
                conn, addr = self.server_socket.accept()

                self.client_conn, self.client_addr = conn, addr
                self.client_conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.client_conn.settimeout(getattr(self.cfg.tcp, "recv_timeout", 0.1))
                self.online = True

                self.logger.info("Connected to %s", addr)

                return True

            except socket.timeout as e:
                if infinite_timeout:
                    continue
                elif time.time() - start >= deadline:
                    self.logger.warning("TCPServer: accept timeout before client connected")
                    raise RuntimeError("TCPServer: accept timeout before client connected") from e
                continue
            except OSError as e:
                # Bind/listen failed or socket got closed during shutdown
                self.logger.error("TCPServer: accept failed: %s", e)
                raise RuntimeError(f"TCPServer: accept failed: {e}") from e

        return False


    def _receive(self) -> None:
        """Receive data from the client connection."""

        if not self.client_conn:
            return
        try:
            chunk = self.client_conn.recv(self.cfg.tcp.recv_buffer_size)
            if not chunk:
                self.logger.warning("TCPServer: Connection closed by client.")
                self.online = False
                return
            self._buf.extend(chunk)
            self._decode_message()  # parse whatever we have
        except socket.timeout:
            # No data this cycle — not an error. Let _run() continue.
            return
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as e:
            self.logger.warning("TCPServer: Receive error: %s", e)


    def _decode_message(self) -> None:
        """Decode messages from the buffer."""

        # Process as many complete packets as are available
        mv = memoryview(self._buf)
        consumed = 0
        max_size = int(self.cfg.tcp.max_packet_size)

        while len(mv) - consumed >= 4:  # header present?
            h = mv[consumed:consumed+4]
            pkt_type = h[0]
            payload_len = int.from_bytes(h[1:4], "big")

            # sanity
            if payload_len <= 0 or payload_len > max_size:
                self.logger.error(
                    "TCPServer: Invalid payload length %d; clearing buffer.",
                    payload_len)
                self._buf.clear()
                return

            total = 4 + payload_len
            if len(mv) - consumed < total:
                break  # wait for more bytes

            # extract payload (copy bytes only once here)
            start = consumed + 4
            end = start + payload_len
            payload = bytes(mv[start:end])

            # map to MessageType; skip unknown (mirrors Unity’s check)
            try:
                msg_type = MessageType(pkt_type)
            except ValueError:
                self.logger.warning("TCPServer: Unknown MessageType %d, skipping packet.", pkt_type)
                consumed += total
                continue

            # enqueue raw bytes + type (no decoding)
            self.tcp_receive_q.put((payload, msg_type))

            consumed += total

        if consumed:
            # drop consumed prefix once (amortized O(n))
            del self._buf[:consumed]


    def tcp_send(
        self,
        payload: bytes,
        message_type: MessageType,
    ) -> None:
        """Encode a payload and send it."""

        if not self.client_conn:
            self.logger.warning("TCPServer: tcp_send called but no client is connected.")
            self.online = False
            return

        try:
            msg_type = MessageType(message_type)
        except ValueError:
            self.logger.error("TCPServer: unknown MessageType %r", message_type)
            return

        if not isinstance(payload, (bytes, bytearray, memoryview)):
            self.logger.error("TCPServer: payload must be bytes-like.")
            return
        body = bytes(payload)

        packet = self._encode_message(body, msg_type)
        max_attempts = self.cfg.tcp.max_resend_attempts
        for attempt in range(max_attempts):
            try:
                if self.client_conn:
                    self.client_conn.sendall(packet)
                    return
            except OSError as e:
                self.logger.warning("TCPServer: Send error (%d/%d): %s", attempt+1, max_attempts, e)
                if attempt+1 >= max_attempts:
                    self.logger.error("TCPServer: Max resend attempts reached; giving up.")
                    self.online = False
                    return
                self._stop.wait(0.01)


    def _encode_message(
        self,
        payload: bytes,
        message_type: MessageType
    ) -> bytes:
        """Encode a message with header for sending.

        The format is following:
            [MessageType][PayloadSize][Payload]
                1 byte      3 bytes   variable
        """

        length = len(payload)
        if length > self.cfg.tcp.max_packet_size:
            self.logger.error(
                "TCPServer: Payload too large: %d > %d",
                length, self.cfg.tcp.max_packet_size)
            raise ValueError("Payload too large.")

        header = bytes([int(message_type)]) + length.to_bytes(3, 'big')
        return header + payload
