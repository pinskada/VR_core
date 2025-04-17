# VR_core/gyroscope/gyro_handler.py
import threading
import time
from vr_core.config import gyroscope_config
import os

# Check if I2C is enabled on the Raspberry Pi
def ensure_i2c_enabled():

    if not os.path.exists("/dev/i2c-1"):
        print("[Gyroscope] I2C not detected.")
        print("Run `sudo raspi-config` > Interface Options > I2C > Enable")
        return
    
ensure_i2c_enabled()

# Check if smbus2 is available for I2C communication
try:
    import smbus2
    HARDWARE_AVAILABLE = True # I2C is available
except ImportError:
    print("[gyro_handler] smbus2 not available - mock mode")
    HARDWARE_AVAILABLE = False # I2C not available, use mock mode

class Gyroscope:
    def __init__(self, tcp_sender):
        self.tcp_sender = tcp_sender
        self.running = False
        self.thread = threading.Thread(target=self.run, daemon=True)

        self.addr = gyroscope_config.addr
        self.bus = smbus2.SMBus(gyroscope_config.bus_num) if HARDWARE_AVAILABLE else None
        self.mock_angle = 0.0

        if HARDWARE_AVAILABLE:
            self.bus.write_byte_data(self.addr, gyroscope_config.reg_ctrl1, gyroscope_config.ctrl1_enable)  # Enable gyro
            print("[gyro_handler] Gyro initialized")

    def start(self):
        self.running = True
        self.thread.start()
        print("[gyro_handler] Started")

    def stop(self):
        self.running = False
        print("[gyro_handler] Stopped")

    def read_gyro(self):
        if not HARDWARE_AVAILABLE:
            self.mock_angle += 1.5
            return {'x': 0.0, 'y': 0.0, 'z': self.mock_angle}

        def read_word(reg):
            low = self.bus.read_byte_data(self.addr, reg)
            high = self.bus.read_byte_data(self.addr, reg+1)
            val = (high << 8) + low
            return val if val < 32768 else val - 65536

        return {
            'x': read_word(gyroscope_config.reg_out_x_l),
            'y': read_word(gyroscope_config.reg_out_y_l),
            'z': read_word(gyroscope_config.reg_out_z_l),
        }

    def run(self):
        while self.running:
            data = self.read_gyro()
            self.tcp_sender.send({
                "type": "gyro",
                "data": data
            }, priority='high')
            time.sleep(0.01)  # 100 Hz


def ensure_i2c_enabled():

    if not os.path.exists("/dev/i2c-1"):
        print("[Gyroscope] I2C not detected.")
        print("Run `sudo raspi-config` > Interface Options > I2C > Enable")
        return