import queue

# ---- Component Instances ------------------------------------------
core = None
tcp_server = None
gyroscope = None


# ---- TCP Configuration --------------------------------------------
class TCPConfig:
    host = '0.0.0.0' # Listen on all interfaces
    port = 65432     # Port for the TCP server

    static_ip_prefix = "192.168.1." # Static IP prefix for the device
    recv_buffer_size = 1024         # Buffer size for receiving data
    send_loop_interval = 0.001      # Interval for sending messages (in seconds)

    google_dns = "8.8.8.8"  # Used to check if the device is connected to the internet
    http_port = 80          # Port for HTTP requests (if needed)

    # Message priorities for the TCP server
    message_priorities = {
        'high': queue.Queue(), # Reserved for gyroscope data
        'medium': queue.Queue(), # Reserved for eye tracker data
        'low': queue.Queue() # Reserved for other messages
    }

tcp_config = TCPConfig()


# ---- Gyroscope Configuration --------------------------------------
class GyroscopeConfig:
    bus_num = 1         # I2C bus number (1 for Raspberry Pi 3 and later)
    addr = 0x6b         # I2C address of the gyroscope (L3GD20H)
    update_rate = 0.01  # in seconds (100 Hz)

    # Register map
    reg_ctrl1 = 0x20
    ctrl1_enable = 0x0F

    # Registers for X, Y, Z axes
    reg_out_x_l = 0x28
    reg_out_y_l = 0x2A
    reg_out_z_l = 0x2C

gyroscope_config = GyroscopeConfig()


# ---- Eye Tracker Configuration ------------------------------------
class EyeTrackerConfig:
    interval = 0.033  # ~30 FPS

eye_tracker_config = EyeTrackerConfig()


# ---- ESP32 Configuration ------------------------------------------
class ESP32Config:
    port="/dev/serial0" # Serial port for ESP32 (e.g., /dev/serial0 on Raspberry Pi)
    baudrate=115200 # Baud rate for the serial connection 
    timeout=1 # Timeout for the serial connection (in seconds)

    handshake_attempts = 3 # Number of attempts to perform the handshake
    handshake_message = "HELLO" # Handshake message to send to ESP32
    handshake_response = "READY" # Expected response from ESP32 after handshake

    send_attempts = 3 # Number of attempts to send the focal distance
esp32_config = ESP32Config()
