import time
import socket
import threading
from vr_core.network.tcp_server import TCPServer
import vr_core.config as config

# Simulated Core that handles commands received from Unity
class MockCore:
    def dispatch_command(self, message):
        print(f"[MockCore] Received command from Unity: {message}")

def mock_unity_client(expected_messages=3):
    """Simulate Unity connecting and interacting with the TCPServer."""
    time.sleep(1)  # Wait for server to start

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect(("127.0.0.1", config.TCP_PORT))
        sock.settimeout(2)

        print("[MockUnity] Connected to TCP server")

        # Receive initial "CONNECTED" response
        print("[MockUnity] Received:", sock.recv(1024).decode().strip())

        # Send a test command to the server
        sock.sendall(b"TEST_COMMAND\n")

        # Wait to receive prioritized responses
        received = 0
        try:
            while received < expected_messages:
                msg = sock.recv(1024).decode().strip()
                print(f"[MockUnity] Received: {msg}")
                received += 1
        except socket.timeout:
            print("[MockUnity] Timeout reached.")

        print("[MockUnity] Disconnecting.")

def test_tcp_server():
    print("🚀 Starting TCPServer test")

    # Set mock Core in config (for TCPServer and other modules)
    config.core = MockCore()

    # Start TCP server (auto-starts in constructor)
    server = TCPServer(config.core)

    # Launch Unity simulator
    client_thread = threading.Thread(target=mock_unity_client, daemon=True)
    client_thread.start()

    # Wait for client to connect and exchange data
    time.sleep(3)

    # Place prioritized messages into global queues
    config.MESSAGE_PRIORITIES['high'].put("GYRO:0.1,0.2,0.3")
    config.MESSAGE_PRIORITIES['medium'].put("DIST:52.1")
    config.MESSAGE_PRIORITIES['low'].put("STATUS:All good")

    # Let messages flush through the system
    time.sleep(2)

    # Clean shutdown
    server.stop_server()
    print("------------------------------------------------TCPServer test completed-----------------------------------------")

if __name__ == "__main__":
    test_tcp_server()
