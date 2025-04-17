import queue


core = 0
tcp_server = 0

TCP_HOST = '0.0.0.0'
TCP_PORT = 65432

GYRO_UPDATE_RATE = 0.01  # in seconds (100 Hz)
EYE_TRACKING_INTERVAL = 0.033  # ~30 FPS


MESSAGE_PRIORITIES = {
    'high': queue.Queue(),    # For gyro data
    'medium': queue.Queue(),  # For viewing distance
    'low': queue.Queue()      # For commands, status updates
}