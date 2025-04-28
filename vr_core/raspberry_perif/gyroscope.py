import threading
import time
from vr_core.config import gyroscope_config
import os
import math
import vr_core.module_list as module_list 


class Gyroscope:
    def __init__(self, force_mock=False):
        self.online = True

        module_list.gyroscope = self  # Register the gyroscope in the module list
        self.tcp_server = module_list.tcp_server  # Reference to the TCP server
        self.health_monitor = module_list.health_monitor

        self.mock_angle = 0.0
        self.mock_mode = force_mock
        self.run_thread = threading.Thread(target=self.run)      

        if self.mock_mode:
            # If mock mode is enabled, we don't need to check for hardware availability
            self.health_monitor.status("Gyroscope", "Mock mode active")
            print("[INFO] Gyroscope: Mock mode active — simulating gyro values")
            self.online = True
            self.run_thread.start()  # Start the thread to read gyro data
        else:
            try:
                if self.ensure_i2c_enabled() is False:
                    print("[ERROR] Gyroscope: I2C not enabled. Exiting.")
                    self.health_monitor.failure("Gyroscope", "I2C not enabled")
                    self.online = False
                    return
                
                import smbus2 # type: ignore # Import the smbus2 library for I2C communication
                self.addr = gyroscope_config.addr # I2C address of the gyroscope (L3GD20H)

                self.bus = smbus2.SMBus(gyroscope_config.bus_num) # I2C bus number (1 for Raspberry Pi 3 and later)
                self.bus.write_byte_data(self.addr, gyroscope_config.reg_ctrl1, gyroscope_config.ctrl1_enable)    
                self.online = True  # Set online status to True             
                self.thread.start() # Start the thread to read gyro data

                print("[INFO] Gyroscope: Gyro initialized")
            except OSError as e:
                self.health_monitor.failure("Gyroscope", "Initialisation error")
                print(f"[ERROR] Gyroscope: Error initializing: {e}")
                self.online = False
                return


    def stop(self):
        """Stop the gyroscope thread."""

        self.online = False
        print("[INFO] Gyroscope: Stopped")


    def is_online(self):
        return self.online


    # Check if I2C is enabled on the Raspberry Pi
    def ensure_i2c_enabled(self):
        """Check if I2C is enabled on the Raspberry Pi."""

        if not os.path.exists("/dev/i2c-1"):
            print("[ERROR] Gyroscope: I2C not detected.")
            print("[INFO] Gyroscope: Run 'sudo raspi-config' > Interface Options > I2C > Enable")
            return False
        else:
            return True
    

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
    
        error = None
        failure_count = 0
        while self.online:
            
            try:
                data = self.read_gyro() # Get the gyroscope data
                
                if not self.mock_mode:
                    if self.tcp_server is not None:
                        self.tcp_server.send(
                        {
                            "type": "gyro",
                            "data": data
                        }, data_type='JSON', priority='high')
                        error = None
                    else:
                        print("[WARN] Gyroscope: No TCP sender available. Skipping data send.")
                    
                else:
                    print("[INFO] Gyroscope: Mock data sent:", data)
                    error = None

            except Exception as e:
                failure_count += 1
                error = e

            if error is not None and failure_count >= gyroscope_config.retry_attempts:
                self.health_monitor.failure("Gyroscope", "Error reading gyro data")
                self.online = False
                print("[ERROR] Gyroscope:] Error reading gyro data.")
                break

            time.sleep(gyroscope_config.update_rate)  # Sleep for the specified update rate
