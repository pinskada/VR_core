# File: vr_core/network/tcp_server.py

import socket
import threading
import queue
import time

from vr_core.config import tcp_config 
import vr_core.config as config 


class TCPServer:
    def __init__(self, autostart=True):
        self.core = config.core     # Reference to the Core instance
        self.host = tcp_config.host # Host IP address
        self.port = tcp_config.port # Port number
        self.server_socket = None   # Server socket
        self.client_conn = None     # Client connection
        self.client_addr = None     # Client address
        self.online = False        # Server status

        # Queues for prioritized outbound messages
        self.priority_queues = tcp_config.message_priorities

        # Thread handles
        self.listener_thread = None
        self.receiver_thread = None
        self.sender_thread = None

        # Start the server immediately
        if autostart:
            self.verify_static_ip()
            self.start_server()


    def is_online(self):
        return self.online
    

    def start_server(self):
        """Starts the server and launches threads."""

        self.online = True # Set online flag to True

        self.listener_thread = threading.Thread(target=self._listen_for_connection, daemon=True) # Daemon thread
        self.listener_thread.start() # Start the listener thread


    def stop_server(self):
        """Stops the server and cleans up resources."""

        self.online = False
        if self.client_conn:
            self.client_conn.close()
        if self.server_socket:
            self.server_socket.close()


    def verify_static_ip(self, expected_prefix=tcp_config.static_ip_prefix):
        """Check if the current IP matches the expected static IP prefix."""

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)      # UDP socket for IP check
            s.connect((tcp_config.google_dns, tcp_config.http_port))  # Use Google DNS for connectivity check
            ip = s.getsockname()[0] # Get the local IP address
        except Exception as e:
            print(f"[TCPServer] Could not determine IP: {e}")
            return False
        finally:
            s.close()

        if ip.startswith(expected_prefix): # Check if the IP starts with the expected prefix
            print(f"[TCPServer] IP OK: {ip}")
            return True
        else:
            print(f"[TCPServer] Unexpected IP: {ip} — expected prefix {expected_prefix}")
            print("[TCPServer] Suggestion: Run `set_static_ip.sh` manually with sudo if needed.")
            return False


    def _listen_for_connection(self):
        """Accept a single Unity client and start communication threads."""

        # Create a TCP socket
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) 
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(1)

        print(f"[TCPServer] Waiting for Unity to connect on {self.host}:{self.port}...")
        self.client_conn, self.client_addr = self.server_socket.accept() # Accept a connection

        # Disable Nagle's algorithm for low latency
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

        while self.online:
            try:
                data = self.client_conn.recv(tcp_config.recv_buffer_size) # Receive data from the socket
                if not data:
                    break
                message = data.decode().strip() # Decode the message
                self._handle_incoming(message)  # Process the message
            except Exception as e:
                print(f"[TCPServer] Receive error: {e}")
                break


    def _send_loop(self):
        """Send outgoing messages based on priority."""

        while self.online:
            for priority in ['high', 'medium', 'low']: # Check high to low priority
                try:
                    msg = self.priority_queues[priority].get_nowait()
                    self._send_direct(msg) # Send the message
                    break  # Send one message per cycle
                except queue.Empty:
                    continue
            time.sleep(tcp_config.send_loop_interval) # Sets the send interval


    def _send_direct(self, message: str):
        """Send data to Unity immediately."""

        try:
            if self.client_conn:
                # Encode the message with a newline and send it over the socket
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
