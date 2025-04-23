import time
import socket
import threading
import os
import sys
import json
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from vr_core.network.tcp_server import TCPServer
import vr_core.config as config


class MockDispatcher:
    def handle_message(self, message):
        print(f"[TEST] MockDispatcher: Got command: {message}")


def mock_unity_client(expected_messages=3):
    """Simulate Unity connecting and interacting with the TCPServer."""
    time.sleep(1)  # Wait for server to start

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect(("127.0.0.1", config.TCPConfig.port))
        sock.settimeout(5)  # Set a timeout for the socket operations

        print("[TEST] MockUnity: Connected to TCP server")

        # Receive initial CONNECTED handshake
        print("[TEST] MockUnity: Received:", sock.recv(1024).decode().strip())

        # Send a test JSON command
        test_command = {"cmd": "sync", "value": 1}
        sock.sendall((json.dumps(test_command) + "\n").encode())

        # Wait for encoded messages
        received = 0
        try:
            while received < expected_messages:
                raw = sock.recv(4096)
                if not raw:
                    break
                header = raw[:4]
                payload = raw[4:]
                print(f"[TEST] MockUnity: Received: header={header}, payload={payload[:50]}...")
                received += 1
        except socket.timeout:
            print("[TEST] MockUnity: Timeout reached.")

        print("[TEST] MockUnity: Received all 3 expected messages.")
        print("[TEST] MockUnity: Disconnecting.")


def test_tcp_server():
    print("[TEST] Starting TCPServer test")

    # Start TCP server
    server = TCPServer(autostart=False)
    server.command_dispatcher = MockDispatcher()
    server.start_server()

    # Launch simulated Unity
    client_thread = threading.Thread(target=mock_unity_client, daemon=True)
    client_thread.start()

    # Wait for client to connect
    time.sleep(3)
    data = {"x": 0.1, "y": 0.2, "z": 0.3}
    # Send some encoded test messages
    server.send({"type": "gyro", "x": 0.1, "y": 0.2, "z": 0.3}, data_type = 'JSON', priority="high")
    server.send({"type": "distance", "value": 52.1}, data_type = 'JSON', priority="medium")
    server.send(
        {
            "type": "gyro",
            "data": data
        }, data_type='JSON', priority='high')

    # Let the system flush messages
    time.sleep(4)

    server.stop_server()
    print("[TEST] TCPServer test completed successfully")


if __name__ == "__main__":
    test_tcp_server()
