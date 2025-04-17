# VR_core/gyroscope/gyro_handler.py
import threading
import time
from vr_core.config import gyroscope_config
import os
import math

# Check if I2C is enabled on the Raspberry Pi
def ensure_i2c_enabled():

    if not os.path.exists("/dev/i2c-1"):
        print("[Gyroscope] I2C not detected.")
        print("Run 'sudo raspi-config' > Interface Options > I2C > Enable")
        return
    
ensure_i2c_enabled()

# Check if smbus2 is available for I2C communication
try:
    import smbus2
    HARDWARE_AVAILABLE = True # I2C is available
except ImportError:
    print("[gyroscope] smbus2 not available - mock mode")
    HARDWARE_AVAILABLE = False # I2C not available, use mock mode

class Gyroscope:
    def __init__(self, tcp_sender, force_mock=False):
        self.tcp_sender = tcp_sender
        self.thread = threading.Thread(target=self.run, daemon=True)

        self.addr = gyroscope_config.addr
        self.bus = smbus2.SMBus(gyroscope_config.bus_num) if HARDWARE_AVAILABLE else None

        self.mock_angle = 0.0
        self.mock_mode = force_mock or not HARDWARE_AVAILABLE

        if self.mock_mode:
            print("[Gyroscope] MOCK MODE ACTIVE — Simulating gyro values")
        else:
            self.bus.write_byte_data(self.addr, gyroscope_config.reg_ctrl1, gyroscope_config.ctrl1_enable)
            print("[Gyroscope] Gyro initialized")

        self.running = True
        self.thread.start()
        print("[gyroscope] Started")


    def stop(self):
        self.running = False
        print("[gyroscope] Stopped")


    def read_gyro(self):
        if self.mock_mode:
            self.mock_angle += 0.1
            return {
                'x': round(25.0 * math.sin(self.mock_angle), 2),
                'y': round(15.0 * math.sin(self.mock_angle / 2), 2),
                'z': round(10.0 * math.cos(self.mock_angle), 2),
            }

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
            time.sleep(gyroscope_config.update_rate)  # 100 Hz
