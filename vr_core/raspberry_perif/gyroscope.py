import threading
import time
from vr_core.config import gyroscope_config
import os
import math


class Gyroscope:
    def __init__(self, tcp_sender, force_mock=False):
        self.mock_angle = 0.0
        self.mock_mode = force_mock
        self.online = False
        self.tcp_sender = tcp_sender
        self.thread = threading.Thread(target=self.run, daemon=True)      

        if self.mock_mode:
            # If mock mode is enabled, we don't need to check for hardware availability
            print("[Gyroscope] MOCK MODE ACTIVE — Simulating gyro values")
        else:
            try:
                if self.ensure_i2c_enabled() is False:
                    print("[Gyroscope] I2C not enabled. Exiting.")
                    return
                
                import smbus2 # type: ignore # Import the smbus2 library for I2C communication
                self.addr = gyroscope_config.addr # I2C address of the gyroscope (L3GD20H)

                self.bus = smbus2.SMBus(gyroscope_config.bus_num) # I2C bus number (1 for Raspberry Pi 3 and later)
                self.bus.write_byte_data(self.addr, gyroscope_config.reg_ctrl1, gyroscope_config.ctrl1_enable)    

                print("[Gyroscope] Gyro initialized")
            except OSError as e:
                print(f"[Gyroscope] Error initializing gyro: {e}")
                return
            
        self.online = True  # Set online status to True             
        self.thread.start() # Start the thread to read gyro data
        
        print("[Gyroscope] Started")


    def stop(self):
        """Stop the gyroscope thread."""

        self.online = False
        print("[Gyroscope] Stopped")


    def is_online(self):
        return self.online


    # Check if I2C is enabled on the Raspberry Pi
    def ensure_i2c_enabled(self):
        """Check if I2C is enabled on the Raspberry Pi."""

        if not os.path.exists("/dev/i2c-1"):
            print("[Gyroscope] I2C not detected.")
            print("Run 'sudo raspi-config' > Interface Options > I2C > Enable")
            return False
    

    def read_gyro(self):
        """Read gyroscope data."""

        # Create synthetic data if in mock mode
        if self.mock_mode:
            self.mock_angle += 0.1
            return {
                'x': round(25.0 * math.sin(self.mock_angle), 2),
                'y': round(15.0 * math.sin(self.mock_angle / 2), 2),
                'z': round(10.0 * math.cos(self.mock_angle), 2),
            }

        # Read the gyroscope data from the I2C bus
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
        """Continuously read gyroscope data and send it over TCP."""

        while self.online:
            data = self.read_gyro() # Get the gyroscope data

            if self.tcp_sender is not None:
                self.tcp_sender.send(
                {
                    "type": "gyro",
                    "data": data
                }, priority='high')
            else:
                print("[Gyroscope] No TCP sender available. Skipping data send.")

            time.sleep(gyroscope_config.update_rate)  # Sleep for the specified update rate
