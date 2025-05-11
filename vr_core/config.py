import queue
from types import SimpleNamespace

# ---- TCP Configuration --------------------------------------------
tcp_config = SimpleNamespace(
    host = '0.0.0.0', # Listen on all interfaces
    port = 65432,     # Port for the TCP server

    static_ip_prefix = "192.168.1.", # Static IP prefix for the device
    recv_buffer_size = 1024,         # Buffer size for receiving data
    send_loop_interval = 0.001,      # Interval for sending messages (in seconds)

    google_dns = "8.8.8.8",  # Used to check if the device is connected to the internet
    http_port = 80,          # Port for HTTP requests (if needed)

    restart_server_count = 1,

    # Message priorities for the TCP server7
    message_priorities = {
        'high': queue.Queue(), # Reserved for gyroscope data
        'medium': queue.Queue(), # Reserved for eye tracker data
        'low': queue.Queue() # Reserved for other messages
    }
)

# ---- Gyroscope Configuration --------------------------------------
gyroscope_config = SimpleNamespace(
    update_rate = 0.01,  # in seconds (100 Hz)
    retry_attempts = 10,  # Number of attempts to read data from the gyroscope

    calib_buffer_size = 100,
    scale_factor = 0.075,

    bus_num = 1,         # I2C bus number (1 for Raspberry Pi 3 and later)
    addr_gyr_acc = 0x6b,         # I2C address of the gyroscope (L3GD20H)
    addr_mag = 0x1E,     # I2C address of the magnetometer (LIS3MDL)


    # Register map
    reg_ctrl1 = 0x20,
    ctrl1_enable = 0x0F,

    # Registers for X, Y, Z axes
    gyro_reg_out_x = 0x22,
    gyro_reg_out_y = 0x24,
    gyro_reg_out_z = 0x26,

    acc_reg_out_x = 0x28,
    acc_reg_out_y = 0x2A,
    acc_reg_out_z = 0x2C,

    mag_reg_out_x = 0x28,
    mag_reg_out_y = 0x2A,
    mag_reg_out_z = 0x2C


)

# ---- ESP32 Configuration ------------------------------------------
esp32_config = SimpleNamespace(
    port="/dev/serial0", # Serial port for ESP32 (e.g., /dev/serial0 on Raspberry Pi)
    baudrate=115200, # Baud rate for the serial connection 
    timeout=1, # Timeout for the serial connection (in seconds)

    handshake_attempts = 3, # Number of attempts to perform the handshake
    handshake_interval_inner = 1, # Interval between handshake attempts (in seconds)
    handshake_interval_outer = 5, # Interval between outer handshake attempts (in seconds)
    handshake_message = "STATUS", # Handshake message to send to ESP32
    handshake_response = "ONLINE", # Expected response from ESP32 after handshake

    send_attempts = 3 # Number of attempts to send the focal distance   
)

# ---- Tracker Configuration ------------------------------------
tracker_config = SimpleNamespace(
    frame_provider_max_fps = 1000, # Maximum FPS for the frame provider3`1`3
    jpeg_quality = 15,  # JPEG encoding quality (0-100)
    sync_timeout = 10,  # Timeout for EyeLoop response in seconds
    preview_fps = 20,  # FPS for preview stream
    handler_queue_timeout = 0.001,  # Timeout for queue operations in seconds
    provider_queue_timeout = 0.01,  # Timeout for provider queue operations in seconds
    process_launch_time = 0.4,  # Time to wait for the EyeLoop process to stabilize (in seconds)
    png_send_rate = 8,
    
    crop_left = ((0.0, 1.0), (0.0, 0.5)),  # Relative region (x1, x2, y1, y2) for the left eye
    crop_right = ((0.0, 1.0), (0.5, 1.0)),  # Relative region (x1, x2, y1, y2) for the right eye

    sharedmem_name_left = "eye_left_frame",  # Shared memory buffer name for left eye
    sharedmem_name_right = "eye_right_frame",  # Shared memory buffer name for right eye
    memory_dtype = "uint8",  # Data type for the shared9`1b54n67` memory buffer
    memory_shape_L = [960, 1080],  # Size of the shared memory buffer (height, width)
    memory_shape_R = [960, 1080],  # Size of the shared memory buffer (height, width)
    full_frame_resolution = [1920, 1080],  # Full frame resolution (height, width)

    blink_calibration_L = "blink_calibration/blink_calibration_cropL.npy",  # Path to the blink calibration file
    blink_calibration_R = "blink_calibration/blink_calibration_cropR.npy",  # Path to the blink calibration file

    importer_name = "shared_memory_importer",  # Importer name for the EyeLoop process

    eyeloop_health_check_interval = 3,  # Interval for health check of the eyeloop processes in seconds

    use_test_video = False,  # Use saved video instead of live camera
    test_video_path = "test_video/test_video.mp4",  # Path to test video
    test_video_resolution = (1920, 1080),  # Hardcoded resolution, must be changed in the code if needed
    test_video_channels = 1  # Number of channels in the test video, must be changed in the code if needed
)

eye_processing_config = SimpleNamespace(

    print_ipd_state = 50,  # Flag to indicate if the system should print the IPD state
    filter_alpha = 0.5,  # Alpha value for the low-pass filter (0-1)
    buffer_crop_factor = 0.1,  # Factor to determine the amount of data to discard from the start and end of the buffer
    std_threshold = 0.01,  # Threshold for standard deviation to determine if the sample is valid
    gyro_threshold = 5,  # Threshold for gyroscope data to determine if the system should trust the data
    compensation_factor = 1,

    model_params = None,  # Model parameters for the inverse model (to be set during calibration)
    corrected_model_params = None  # Model parameters for the corrected model (to be set during calibration)
)


# ---- Camera Configuration ----------------------------------------
camera_manager_config = SimpleNamespace(
    width = 1280,
    height = 720,

    focus = 30,# Only used if autofocus is False
    exposure_time = 10000,  # In microseconds
    analogue_gain = 2.0,  # Brightness boost
    af_mode = 0,  # 0 = manual, 1 = auto

    capture_retries = 3  # Number of attempts to capture a frame
)

# ---- Health Monitor Configuration --------------------------------
health_monitor = SimpleNamespace(
    check_interval = 2,  # Interval for health check in seconds
    monitored_components = []
)