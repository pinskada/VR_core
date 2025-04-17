import queue

# ---- Component Instances ------------------------------------------
core = None
tcp_server = None
gyroscope = None


# ---- TCP Configuration --------------------------------------------
class TCPConfig:
    host = '0.0.0.0'
    port = 65432
    message_priorities = {
        'high': queue.Queue(),
        'medium': queue.Queue(),
        'low': queue.Queue()
    }

tcp = TCPConfig()


# ---- Gyroscope Configuration --------------------------------------
class GyroscopeConfig:
    bus_num = 1
    addr = 0x6b
    update_rate = 0.01  # in seconds (100 Hz)

    # Register map
    reg_ctrl1 = 0x20
    ctrl1_enable = 0x0F

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
    # Add values as needed
    pass

esp32_config = ESP32Config()
