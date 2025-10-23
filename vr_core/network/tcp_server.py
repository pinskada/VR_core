"""Cross-platform TCP server for Unity."""

import socket
import queue
import time

from vr_core.base_service import BaseService
from vr_core.ports.interfaces import INetworkService
from vr_core.config_service.config import Config
from vr_core.network.comm_contracts import MessageType

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

        self.cfg = config
        self.tcp_receive_q = tcp_receive_q

        self.online = False

        # Internal state
        self.server_socket: socket.socket | None = None
        self.client_conn: socket.socket | None = None
        self.client_addr: tuple[str, int] | None = None

        self._buf = bytearray()


    def _on_start(self) -> None:
        self._verify_static_ip()

        if not self._start_server():
            return

        self._ready.set()


    def _run(self) -> None:
        while not self._stop.is_set():

            self._receive()
            time.sleep(self.cfg.tcp.receive_loop_interval)


    def _on_stop(self) -> None:
        """Signal threads to stop, close sockets, and join threads."""
        self.online = False

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
            print(f"[WARN] TCPServer: IP check failed: {e}")
            return False
        finally:
            if test_sock:
                test_sock.close()

        if ip.startswith(expected_prefix):
            print(f"[INFO] TCPServer: IP OK: {ip}")
            return True
        print(f"[WARN] TCPServer: Unexpected IP {ip}, expected prefix {expected_prefix}")
        return False


    def _start_server(self) -> bool:
        # Create, bind, and listen
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.cfg.tcp.host, self.cfg.tcp.port))
        self.server_socket.listen(1)
        self.server_socket.settimeout(1.0)

        print(f"[INFO] TCPServer: Waiting for Unity on {self.cfg.tcp.host}:{self.cfg.tcp.port}...")
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

                print(f"[INFO] TCPServer: Connected to {addr}")

                return True

            except socket.timeout as e:
                if infinite_timeout:
                    continue
                elif time.time() - start >= deadline:
                    raise RuntimeError("TCPServer: accept timeout before client connected") from e
                continue
            except OSError as e:
                # Bind/listen failed or socket got closed during shutdown
                raise RuntimeError(f"TCPServer: accept failed: {e}") from e

        return False


    def _receive(self) -> None:
        """Receive data from the client connection."""

        if not self.client_conn:
            return
        try:
            chunk = self.client_conn.recv(self.cfg.tcp.recv_buffer_size)
            if not chunk:
                print("[WARN] TCPServer: Connection closed by client.")
                self.online = False
                return
            self._buf.extend(chunk)
            self._decode_message()  # parse whatever we have
        except socket.timeout:
            # No data this cycle — not an error. Let _run() continue.
            return
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError) as e:
            print(f"[WARN] TCPServer: Receive error: {e}")
            self.online = False


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
                print(f"[ERROR] TCPServer: Invalid payload length {payload_len}; clearing buffer.")
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
                print(f"[WARN] TCPServer: Unknown MessageType {pkt_type}, skipping packet.")
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
            print("[WARN] TCPServer: tcp_send called but no client is connected.")
            self.online = False
            return

        try:
            msg_type = MessageType(message_type)
        except ValueError:
            print(f"[ERROR] TCPServer: unknown MessageType {message_type!r}")
            return

        if not isinstance(payload, (bytes, bytearray, memoryview)):
            print("[ERROR] TCPServer: payload must be bytes-like.")
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
                print(f"[WARN] TCPServer: Send error ({attempt+1}/{max_attempts}): {e}")
                if attempt+1 >= max_attempts:
                    print("[ERROR] TCPServer: Max resend attempts reached; giving up.")
                    self.online = False
                    return
                time.sleep(0.01)


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
            raise ValueError("Payload too large.")

        header = bytes([int(message_type)]) + length.to_bytes(3, 'big')
        return header + payload
