# ruff: noqa: ERA001

"""Config module dataclasses."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TCP:
    """Network configuration settings."""

    host: str = "0.0.0.0" # Listen on all interfaces
    port: int = 65432     # Port for the TCP server

    static_ip_prefix: str = "192.168.2." # Static IP prefix for the device
    recv_buffer_size: int = 1024         # Buffer size for receiving data
    send_loop_interval: float = 0.001      # Interval for sending messages (in seconds)
    receive_loop_interval: float = 0.001   # Interval for receiving messages (in seconds)

    google_dns: str = "8.8.8.8" # Used to check if the device is connected to the internet
    http_port: int = 80 # Port for HTTP requests (if needed)

    max_resend_attempts: int = 3      # Number of times to resend a message if not acknowledged

    # Timeout for establishing a connection, where -1 means no timeout (in seconds)
    connect_timeout: float = 300

    max_packet_size: int = 0xFFFFFF  # Maximum allowed packet size

    restart_server_count: int = 1


@dataclass
class Tracker:
    """Tracker configuration settings."""

    frame_provider_max_fps: int = 1000 # Maximum FPS for the frame provider
    png_compression: int = 3  # PNG compression level (0-9)
    sync_timeout: float = 0.2  # Timeout for EyeLoop response in seconds
    resp_q_timeout: float = 0.001  # Timeout for queue operations in seconds
    provider_queue_timeout: float = 0.01  # Timeout for provider queue operations in seconds
    process_launch_time: float = 0.4  # Time to wait for the tracker to stabilize (in seconds)
    png_send_rate: int = 8

    sharedmem_name_left: str = "eye_left_frame"  # Shared memory buffer name for left eye
    sharedmem_name_right: str = "eye_right_frame"  # Shared memory buffer name for right eye
    memory_dtype: str = "uint8"  # Data type for the shared memory buffer
    memory_shape_l: tuple[int, int] = (1080, 960)  # Size of the shared memory buff (height, width)
    memory_shape_r: tuple[int, int] = (1080, 960)  # Size of the shared memory buff (height, width)
    full_frame_resolution: tuple[int, int] = (1080, 1920)  # Full frame resolution (height, width)
    # Time to wait for shared memory to be released (in seconds)
    memory_unlink_timeout: float = 5.0
    # Time to wait for frame provider to release frames (in seconds)
    frame_hold_timeout: float = 2.0

    # Path to the blink calibration file
    blink_calibration_l: str = "blink_calibration/blink_calibration_cropL.npy"
    blink_calibration_r: str = "blink_calibration/blink_calibration_cropR.npy"

    eyeloop_start_timeout: float = 5

    # Importer name for the EyeLoop process
    importer_name: str = "shared_memory_importer"

    # Interval for health check of the eyeloop processes in seconds
    health_check_interval: int = 3

    use_test_video: bool = False  # Use saved video instead of live camera
    test_video_path: str = "test_video/test_video.mp4"  # Path to test video
    # Hardcoded resolution, must be changed in the code if needed
    test_video_width: int = 1080
    test_video_height: int = 720
    # Number of channels in the test video, must be changed in the code if needed
    test_video_channels: int = 1

    sync_buffer_size: int = 32  # Maximum number of frames to hold for synchronization

    # eyeloop_model: str = "circular"
    eyeloop_model: str = "fast_elliptical"

@dataclass
class Gaze:
    """Gaze configuration settings."""

    print_ipd_state: int = 50  # Flag to indicate if the system should print the IPD state
    filter_alpha: float = 0.5  # Alpha value for the low-pass filter (0-1)
    # Factor to determine the amount of data to discard from the start and end of the buffer
    buffer_crop_factor: float = 0.1
    # Threshold for standard deviation to determine if the sample is valid
    std_threshold: float = 3.0
    # Threshold for gyroscope data to determine if the system should trust the data
    gyro_threshold: int = 5
    gyro_thr_high: int = 15  # High threshold for gyro to untrust tracker
    gyro_thr_low: int = 7    # Low threshold for gyro to trust tracker
    settle_time_s: float = 0.2  # Time to wait after untrusting before trusting again (in seconds)

    ipd_min_samples: int = 10  # Minimum number of samples required for IPD calculation
    compensation_factor: float = 0.1
    tracker_data_timeout: float = 0.05  # Timeout for receiving tracker data (in seconds)
    ipd_queue_timeout: float = 0.01  # Timeout for receiving IPD data (in seconds)
    diop_impairment: float = 0.0  # Diopter value for vision impairment compensation
    max_diop_impairment: float = 8.0  # Maximum diopter impairment supported
    # Maximum shift as a fraction of 'b' to avoid excessive compensation
    max_shift_factor: float = 1
    # Model parameters for the inverse model (to be set during calibration)
    model_params: Any = None
    corrected_model_params: Any = None

@dataclass
class Gaze2:
    """Gaze configuration settings."""

    vector_queue_timeout: float = 0.01  # Timeout for receiving IPD data (in seconds)
    vector_min_samples: int = 10  # Minimum number of vector samples required for calibration

    print_ipd_state: int = 50  # Flag to indicate if the system should print the IPD state
    filter_alpha: float = 0.5  # Alpha value for the low-pass filter (0-1)
    # Factor to determine the amount of data to discard from the start and end of the buffer
    buffer_crop_factor: float = 0.1
    # Threshold for standard deviation to determine if the sample is valid
    std_threshold: float = 3.0
    # Threshold for gyroscope data to determine if the system should trust the data
    gyro_threshold: int = 5
    gyro_thr_high: int = 15  # High threshold for gyro to untrust tracker
    gyro_thr_low: int = 7    # Low threshold for gyro to trust tracker
    settle_time_s: float = 0.2  # Time to wait after untrusting before trusting again (in seconds)

    compensation_factor: float = 0.1
    tracker_data_timeout: float = 0.05  # Timeout for receiving tracker data (in seconds)
    diop_impairment: float = 0.0  # Diopter value for vision impairment compensation
    max_diop_impairment: float = 8.0  # Maximum diopter impairment supported
    # Maximum shift as a fraction of 'b' to avoid excessive compensation
    max_shift_factor: float = 1
    # Model parameters for the inverse model (to be set during calibration)
    model_params: Any = None
    corrected_model_params: Any = None


@dataclass
class TrackerCrop:
    """Defines crop region for the tracker."""

    # Relative region (x1, x2, y1, y2) for the left eye
    # crop_left: tuple[tuple[float, float], tuple[float, float]] = ((0.0, 0.5), (0.0, 1.0))
    # # Relative region (x1, x2, y1, y2) for the right eye
    # crop_right: tuple[tuple[float, float], tuple[float, float]] = ((0.5, 1.0), (0.0, 1.0))

    # crop_left: tuple[tuple[float, float], tuple[float, float]] = ((0.0, 0.4), (0.3, 0.7))
    # # Relative region (x1, x2, y1, y2) for the right eye
    # crop_right: tuple[tuple[float, float], tuple[float, float]] = ((0.6, 1), (0.3, 0.7))

    crop_left: tuple[tuple[float, float], tuple[float, float]] = ((0.3, 0.5), (0.35, 0.6))
    # Relative region (x1, x2, y1, y2) for the right eye
    crop_right: tuple[tuple[float, float], tuple[float, float]] = ((0.5, 0.7), (0.35, 0.6))

# 2300 x 2592 -> 1000x1200

@dataclass
class Eyeloop:
    """Eyeloop configuration settings."""

    # left_threshold_pupil: int = 62  # Threshold for pupil detection in the left eye
    # left_blur_size_pupil: int = 3  # Size of the blur applied to the image
    # left_min_radius_pupil: int = 5  # Minimum radius for pupil detection
    # left_max_radius_pupil: int = 50  # Maximum radius for pupil detection

    # right_threshold_pupil: int = 62  # Threshold for pupil detection in the right eye
    # right_blur_size_pupil: int = 3  # Size of the blur applied to the image
    # right_min_radius_pupil: int = 5  # Minimum radius for pupil detection
    # right_max_radius_pupil: int = 50  # Maximum radius for pupil detection


    left_threshold_pupil: int = 55  # Threshold for pupil detection in the left eye
    left_blur_size_pupil: int = 10  # Size of the blur applied to the image
    left_min_radius_pupil: int = 5  # Minimum radius for pupil detection
    left_max_radius_pupil: int = 50  # Maximum radius for pupil detection

    right_threshold_pupil: int = 52  # Threshold for pupil detection in the right eye
    right_blur_size_pupil: int = 10  # Size of the blur applied to the image
    right_min_radius_pupil: int = 5  # Minimum radius for pupil detection
    right_max_radius_pupil: int = 50  # Maximum radius for pupil detection

    left_threshold_cr: int = 140  # Threshold for cr detection in the left eye
    left_blur_size_cr: int = 0  # Size of the blur applied to the image
    left_min_radius_cr: int = 2  # Minimum radius for cr detection
    left_max_radius_cr: int = 10  # Maximum radius for cr detection

    right_threshold_cr: int = 140 # Threshold for cr detection in the right eye
    right_blur_size_cr: int = 0  # Size of the blur applied to the image
    right_min_radius_cr: int = 2  # Minimum radius for cr detection
    right_max_radius_cr: int = 10  # Maximum radius for cr detection

    left_min_circularity_pupil: float = 0.5  # Minimum circularity for pupil detection
    left_max_circularity_pupil: float = 1.8  # Maximum circularity for pupil detection
    left_max_aspect_ratio_pupil: float = 2.2  # Maximum aspect ratio for pupil detection

    right_min_circularity_pupil: float = 0.5  # Minimum circularity for pupil detection
    right_max_circularity_pupil: float = 1.8  # Maximum circularity for pupil detection
    right_max_aspect_ratio_pupil: float = 2.2  # Maximum aspect ratio for pupil detection

    left_min_circularity_cr: float = 0.0 # Minimum circularity for pupil detection
    left_max_circularity_cr: float = 1.8  # Maximum circularity for pupil detection
    left_max_aspect_ratio_cr: float = 2.2  # Maximum aspect ratio for pupil detection

    right_min_circularity_cr: float = 0.0  # Minimum circularity for pupil detection
    right_max_circularity_cr: float = 1.8  # Maximum circularity for pupil detection
    right_max_aspect_ratio_cr: float = 2.2  # Maximum aspect ratio for pupil detection

@dataclass
class Camera:
    """Camera configuration settings."""

    full_res_width: int = 1536
    full_res_height: int = 864

    target_res_width: int = 1536
    target_res_height: int = 864

    # full_res_width: int = 2304
    # full_res_height: int = 1296

    # target_res_width: int = 2304
    # target_res_height: int = 1296

    focus: int = 22 # Only used if autofocus is False
    exposure: int = 10000  # In microseconds
    gain: float = 25  # Brightness boost
    af_mode: int = 0  # 0 = manual, 1 = auto
    buffer_count: int = 2  # Number of buffers for the camera

    capture_timeout_ms: int = 200  # Timeout for capturing a frame (in milliseconds)
    reconfig_interval: float = 5.0  # Time between config checks (in seconds)
    capture_retries: int = 3  # Number of attempts to capture a frame
    jpeg_quality: int = 15  # JPEG encoding quality (0-100)
    preview_fps: int = 20  # FPS for preview stream


@dataclass
class IMU:
    """IMU configuration settings."""

    update_rate: float = 0.01  # in seconds (100 Hz)
    retry_attempts: int = 10  # Number of attempts to read data from the gyroscope

    calib_buffer_size: int = 300
    scale_factor: float = 0.07

    bus_num: int = 1  # I2C bus number (1 for Raspberry Pi 3 and later)
    addr_gyr_acc: int = 0x6b  # I2C address of the gyroscope (L3GD20H)
    addr_mag: int = 0x1E  # I2C address of the magnetometer (LIS3MDL)


    # Register map
    reg_ctrl1: int = 0x20
    ctrl1_enable: int = 0x0F

    # Registers for X, Y, Z axes
    gyro_reg_out_x: int = 0x22
    gyro_reg_out_y: int = 0x24
    gyro_reg_out_z: int = 0x26

    acc_reg_out_x: int = 0x28
    acc_reg_out_y: int = 0x2A
    acc_reg_out_z: int = 0x2C

    mag_reg_out_x: int = 0x28
    mag_reg_out_y: int = 0x2A
    mag_reg_out_z: int = 0x2C


@dataclass
class ESP32:
    """ESP32 configuration settings."""

    # Serial port for ESP32 (e.g., /dev/serial0 on Raspberry Pi)
    port: str = "/dev/ttyAMA0" # "/dev/serial0"
    baudrate: int = 115200  # Baud rate for the serial connection
    timeout: float = 5  # Timeout for the serial connection (in seconds)

    esp_boot_interval: float = 2.0  # Time to wait for ESP32 to boot (in seconds)

    handshake_attempts: int = 3  # Number of attempts to perform the handshake
    handshake_interval: float = 5  # Interval between handshake attempts (in seconds)
    handshake_message: str = "PING"  # Handshake message to send to ESP32
    handshake_response: str = "PONG"  # Expected response from ESP32 after handshake

    cmd_queue_timeout: float = 0.1  # Timeout for command queue operations (in seconds)
    send_attempts: int = 3  # Number of attempts to send the focal distance


@dataclass
class Health:
    """Health monitor configuration settings."""

    enabled: bool = True
    log_interval_s: int = 60


@dataclass
class RootConfig:
    """Root configuration holding all modules."""

    tcp: TCP = field(default_factory=TCP)
    tracker: Tracker = field(default_factory=Tracker)
    tracker_crop: TrackerCrop = field(default_factory=TrackerCrop)
    gaze: Gaze = field(default_factory=Gaze)
    gaze2: Gaze2 = field(default_factory=Gaze2)
    camera: Camera = field(default_factory=Camera)
    imu: IMU = field(default_factory=IMU)
    esp32: ESP32 = field(default_factory=ESP32)
    health: Health = field(default_factory=Health)
    eyeloop: Eyeloop = field(default_factory=Eyeloop)
