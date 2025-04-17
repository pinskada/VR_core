# File: vr_core/network/tcp_server.py

import socket
import threading
import queue
import time

class TCPServer:
    def __init__(self, core, host='0.0.0.0', port=65432, autostart=True):
        self.core = core                      # Reference to Core
        self.host = host
        self.port = port
        self.server_socket = None
        self.client_conn = None
        self.client_addr = None
        self.running = False

        # Queues for prioritized outbound messages
        self.priority_queues = {
            'high': queue.Queue(),    # For gyro data
            'medium': queue.Queue(),  # For viewing distance
            'low': queue.Queue()      # For commands, status updates
        }

        # Thread handles
        self.listener_thread = None
        self.receiver_thread = None
        self.sender_thread = None

        # Start the server immediately
        if autostart:
            self.start_server()

    # Public entry point
    def start_server(self):
        """Starts the server and launches threads."""
        self.running = True
        self.listener_thread = threading.Thread(target=self._listen_for_connection, daemon=True)
        self.listener_thread.start()

    def stop_server(self):
        """Stops the server and cleans up resources."""
        self.running = False
        if self.client_conn:
            self.client_conn.close()
        if self.server_socket:
            self.server_socket.close()

    def verify_static_ip(self, expected_prefix="192.168.1."):
        """Check if the current IP matches the expected static IP prefix."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        except Exception as e:
            print(f"[TCPServer] Could not determine IP: {e}")
            return False
        finally:
            s.close()

        if ip.startswith(expected_prefix):
            print(f"[TCPServer] IP OK: {ip}")
            return True
        else:
            print(f"[TCPServer] Unexpected IP: {ip} — expected prefix {expected_prefix}")
            print("[TCPServer] Suggestion: Run `set_static_ip.sh` manually with sudo if needed.")
            return False

    # Accept connection from Unity
    def _listen_for_connection(self):
        """Accept a single Unity client and start communication threads."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(1)

        print(f"[TCPServer] Waiting for Unity to connect on {self.host}:{self.port}...")
        self.client_conn, self.client_addr = self.server_socket.accept()
        self.client_conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        print(f"[TCPServer] Connected to Unity at {self.client_addr}")
        self._send_direct("CONNECTED\n")

        # Launch communication threads
        self.receiver_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self.sender_thread = threading.Thread(target=self._send_loop, daemon=True)
        self.receiver_thread.start()
        self.sender_thread.start()

    def _receive_loop(self):
        """Handle incoming messages from Unity."""
        while self.running:
            try:
                data = self.client_conn.recv(1024)
                if not data:
                    break
                message = data.decode().strip()
                self._handle_incoming(message)
            except Exception as e:
                print(f"[TCPServer] Receive error: {e}")
                break

    def _send_loop(self):
        """Send outgoing messages based on priority."""
        while self.running:
            for priority in ['high', 'medium', 'low']:
                try:
                    msg = self.priority_queues[priority].get_nowait()
                    self._send_direct(msg)
                    break  # Send one message per cycle
                except queue.Empty:
                    continue
            time.sleep(0.001)

    def _send_direct(self, message: str):
        """Send data to Unity immediately."""
        try:
            if self.client_conn:
                self.client_conn.sendall((message + '\n').encode())
        except Exception as e:
            print(f"[TCPServer] Send error: {e}")

    def _handle_incoming(self, message: str):
        """Dispatch incoming messages to Core."""
        print(f"[TCPServer] Received: {message}")
        self.core.dispatch_command(message)

    def send(self, message: str, priority='low'):
        """Place a message in the appropriate priority queue."""
        if priority not in self.priority_queues:
            priority = 'low'
        self.priority_queues[priority].put(message)
