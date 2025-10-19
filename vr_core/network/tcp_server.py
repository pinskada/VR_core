"""Cross-platform TCP server for Unity."""

import socket
import threading
import queue
import time
import json

from vr_core.config import tcp_config
import vr_core.module_list as module_list


class TCPServer:
    """
    Cross-platform TCP server for Unity (Windows 10 & Raspberry Pi 5).
    - On init: verifies static IP (optional) and optionally autostarts.
    - start_server(): spawns listener thread.
    - Listener thread: blocks on accept(), then starts receiver and sender threads and terminates.
    - Receiver thread: loops on incoming messages, dispatching JSON commands.
    - Sender thread: loops on internal priority queues, sending any enqueued messages.
    - stop_server(): signals threads to exit, closes sockets, and joins threads.

    Message format: [1-byte type][3-byte length][payload bytes]
    Types: JSON='J', JPEG='G', PNG='P'
    """

    def __init__(self, autostart : bool =True):
        # Register server
        module_list.tcp_server = self

        # Configuration
        self.host = tcp_config.host
        self.port = tcp_config.port
        self.priority_queues = tcp_config.message_priorities

        # Internal state
        self.server_socket = None
        self.client_conn = None
        self.client_addr = None
        self.online = False
        self._stop_event = threading.Event()

        # Threads
        self.listener_thread = None
        self.receiver_thread = None
        self.sender_thread = None

        # Connection state
        self.reseting_connection = False
        self.last_unsent = False
        self.unsent_count = 0

        if autostart:
            #self.verify_static_ip()
            self.start_server()

    def verify_static_ip(self):
        """Optional check: does our local IP match the expected static prefix?"""
        expected_prefix=tcp_config.static_ip_prefix
        try:
            test_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            test_sock.connect((tcp_config.google_dns, tcp_config.http_port))
            ip = test_sock.getsockname()[0]
        except Exception as e:
            print(f"[WARN] TCPServer: IP check failed: {e}")
            return False
        finally:
            test_sock.close()

        if ip.startswith(expected_prefix):
            print(f"[INFO] TCPServer: IP OK: {ip}")
            return True
        print(f"[WARN] TCPServer: Unexpected IP {ip}, expected prefix {expected_prefix}")
        return False

    def start_server(self):
        """Begin listening for a single client connection."""
        if self.online:
            return
        self.online = True
        self._stop_event.clear()
        self.listener_thread = threading.Thread(target=self._listen_for_connection)
        self.listener_thread.start()

    def _listen_for_connection(self):
        # Create, bind, and listen
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(1)

        print(f"[INFO] TCPServer: Waiting for Unity on {self.host}:{self.port}...")
        try:
            conn, addr = self.server_socket.accept()
        except Exception as e:
            #print(f"[WARN] TCPServer: Accept failed: {e}")
            return

        self.client_conn, self.client_addr = conn, addr
        self.client_conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f"[INFO] TCPServer: Connected to {addr}")

        self.unsent_count = 0
        self.last_unsent = False
        self.reseting_connection = False

        # Spawn communication threads
        self.receiver_thread = threading.Thread(target=self._receive_loop)
        self.sender_thread = threading.Thread(target=self._send_loop)
        self.receiver_thread.start()
        self.sender_thread.start()
        # Listener thread exits here

    def _receive_loop(self):
        """Continuously receive data and dispatch JSON messages."""
        while self.online and not self._stop_event.is_set():
            try:
                data = self.client_conn.recv(tcp_config.recv_buffer_size)
                if data == 0 or not data:
                    print(f"[WARN] TCPServer: Connection closed by client.")
                    break
                text = data.decode('utf-8').strip()
                if module_list.command_dispatcher:
                    try:
                        msg = json.loads(text)
                        if module_list.cmd_dispatcher_queue is not None:
                            module_list.cmd_dispatcher_queue.put(msg)
                        else:
                            print("Command dispatcher not initialsed.")
                    except json.JSONDecodeError:
                        print(f"[WARN] TCPServer: Bad JSON: {text}")

            except Exception as e:
                print(f"[WARN] TCPServer: Receive error: {e}")
                break
        self.reseting_connection = True
        print("[WARN] TCPServer: Restarting server due to client dissconected.")
        self.restart_server()

    def _send_loop(self):
        """Continuously check priority queues and send waiting messages."""
        while self.online and not self._stop_event.is_set() and not self.reseting_connection:
            for level in ('high', 'medium', 'low'):
                try:
                    msg = self.priority_queues[level].get_nowait()
                except queue.Empty:
                    continue

                if isinstance(msg, bytes):
                    self._send_direct(msg)
                else:
                    print(f"[WARN] TCPServer: Skipping non-bytes: {type(msg)}")
                break

            time.sleep(tcp_config.send_loop_interval)

    def _send_direct(self, packet: bytes):
        """Immediately send a fully-formed packet to Unity."""
        if not self.reseting_connection:
            try:
                if self.client_conn:
                    self.client_conn.sendall(packet)
                    self.last_unsent = False
            except Exception as e:
                print(f"[WARN] TCPServer: Send error: {e}")
                if self.last_unsent == True:
                    self.unsent_count += 1
                self.last_unsent = True

    def send(self, payload, data_type : str = 'JSON', priority : str = 'low'):
        """Encode a payload and enqueue it by priority."""

        #if data_type == "JPEG":
        #    print(f"[INFO] TCPServer: Sending JPEG image.")
        packet = self.encode_message(payload, data_type)
        queue_ref = self.priority_queues.get(priority, self.priority_queues['low'])
        queue_ref.put(packet)

    def encode_message(self, payload, data_type: str) -> bytes:
        type_map = {'JSON': b'J', 'JPEG': b'G', 'PNG': b'P'}
        if data_type not in type_map:
            raise ValueError(f"Unsupported data type: {data_type}")

        if isinstance(payload, dict):
            body = json.dumps(payload).encode('utf-8')
        elif isinstance(payload, str):
            body = payload.encode('utf-8')
        elif isinstance(payload, bytes):
            body = payload
        else:
            raise ValueError("Payload must be dict, str, or bytes.")

        length = len(body)
        if length > 0xFFFFFF:
            raise ValueError("Payload too large.")

        header = type_map[data_type] + length.to_bytes(3, 'big')
        return header + body

    def restart_server(self):
        """"When client is unresponsive it shuts down all threads and launches a new listener"""
        self.stop_server()
        module_list.cmd_dispatcher_queue.put({"category": "tracker_mode", "action": "stop_preview"})
        self.start_server()

    def stop_server(self):
        """Signal threads to stop, close sockets, and join threads."""
        self.online = False
        self._stop_event.set()

        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Close sockets to unblock accept/recv
        if self.client_conn:
            try:
                self.client_conn.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.client_conn.close()

        if self.server_socket:
            try:
                self.server_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            self.server_socket.close()

        # Join threads
        current = threading.current_thread()
        for thr in (self.listener_thread, self.receiver_thread, self.sender_thread):
            if thr and thr.is_alive() and thr != current:
                thr.join()

        self.listener_thread = None
        self.receiver_thread = None
        self.sender_thread = None


    def is_online(self):
        return self.online
