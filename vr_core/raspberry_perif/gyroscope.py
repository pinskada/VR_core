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
        self.calibration = True
        self.calib_buffer_x = []
        self.calib_buffer_y = []
        self.calib_buffer_z = []
        self.x_ofset = 0
        self.y_ofset = 0
        self.z_ofset = 0

        if self.mock_mode:
            # If mock mode is enabled, we don't need to check for hardware availability
            self.health_monitor.status("Gyroscope", "Mock mode active")
            print("[INFO] Gyroscope: Mock mode active — simulating gyro values")
            self.online = True
            try:
                self.run_thread = threading.Thread(target=self.run) # Create a thread to run the gyroscope data reading
                self.run_thread.start()  # Start the thread to read gyro data
                print("[INFO] Gyroscope: Thread have initialised.")
            except Exception as e:
                print(f"[ERROR] Gyroscope: Thread did not initialise: {e}")
        else:
            try:
                if self.ensure_i2c_enabled() is False:
                    print("[ERROR] Gyroscope: I2C not enabled. Exiting.")
                    self.health_monitor.failure("Gyroscope", "I2C not enabled")
                    self.online = False
                    return
                
                import smbus2 # type: ignore # Import the smbus2 library for I2C communication
             
                self.bus = smbus2.SMBus(gyroscope_config.bus_num) # I2C bus number (1 for Raspberry Pi 3 and later)

                # --- Initialize LSM6DS33 (gyro + accel) ---
                # Enable Gyroscope: 104 Hz, 2000 dps full scale
                self.bus.write_byte_data(gyroscope_config.addr_gyr_acc, 0x11, 0x4C)  # CTRL2_G: ODR = 104 Hz, FS = ±2000 dps
                #self.bus.write_byte_data(gyroscope_config.addr_gyr_acc, 0x11, 0x40)  # CTRL1_XL: ODR = 104 Hz, FS = ±2g

                # Enable Accelerometer: 104 Hz, ±2g full scale
                self.bus.write_byte_data(gyroscope_config.addr_gyr_acc, 0x10, 0x4C)  # CTRL1_XL: ODR = 104 Hz, FS = ±2g

                # --- Initialize LIS3MDL (magnetometer) ---
                # Enable Magnetometer: Ultra-high performance, 80 Hz
                self.bus.write_byte_data(gyroscope_config.addr_mag, 0x20, 0x7E)  # CTRL_REG1: Temp disable, Ultra-high perf, 80 Hz
                self.bus.write_byte_data(gyroscope_config.addr_mag, 0x21, 0x60)  # CTRL_REG2: Full scale ±4 gauss
                self.bus.write_byte_data(gyroscope_config.addr_mag, 0x22, 0x00)  # CTRL_REG3: Continuous-conversion mode
                self.bus.write_byte_data(gyroscope_config.addr_mag, 0x23, 0x0C)  # CTRL_REG4: Ultra-high perf on Z

                #CTRL1_XL = 0x10 → Accelerometer config: 104Hz, ±2g, 400Hz bandwidth
                self.bus.write_byte_data(gyroscope_config.addr_gyr_acc, 0x10, 0x40)

                # CTRL9_XL = 0x18 → Enable all accel axes
                self.bus.write_byte_data(gyroscope_config.addr_gyr_acc, 0x18, 0x38)  # XEN_XL | YEN_XL | ZEN_XL

                # CTRL3_C = 0x12 → Enable BDU (Block Data Update)
                self.bus.write_byte_data(gyroscope_config.addr_gyr_acc, 0x12, 0x44)  # BDU = 1, IF_INC = 1

                self.online = True  # Set online status to True  
                self.run_thread = threading.Thread(target=self.run) # Create a thread to run the gyroscope data reading
                self.run_thread.start() # Start the thread to read gyro data

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
            low = self.bus.read_byte_data(gyroscope_config.addr_gyr_acc, reg)
            high = self.bus.read_byte_data(gyroscope_config.addr_gyr_acc, reg+1)
            val = (high << 8) + low
            return val if val < 32768 else val - 65536

        return {
            'x': read_word(gyroscope_config.gyro_reg_out_x) * gyroscope_config.scale_factor,
            'y': read_word(gyroscope_config.gyro_reg_out_y) * gyroscope_config.scale_factor,
            'z': read_word(gyroscope_config.gyro_reg_out_z) * gyroscope_config.scale_factor,
        }


    def read_accel(self):
        """Read accelerometer data."""

        # Create synthetic data if in mock mode
        if self.mock_mode:
            self.mock_angle += 0.1
            return {
                'x': round(25.0 * math.sin(self.mock_angle), 2),
                'y': round(15.0 * math.sin(self.mock_angle / 2), 2),
                'z': round(10.0 * math.cos(self.mock_angle), 2),
            }

        def read_word(reg):
            low = self.bus.read_byte_data(gyroscope_config.addr_gyr_acc, reg)
            high = self.bus.read_byte_data(gyroscope_config.addr_gyr_acc, reg+1)
            val = (high << 8) + low
            return val if val < 32768 else val - 65536

        return {
            'x': read_word(gyroscope_config.acc_reg_out_x),  # OUTX_L_XL
            'y': read_word(gyroscope_config.acc_reg_out_y),  # OUTY_L_XL
            'z': read_word(gyroscope_config.acc_reg_out_z),  # OUTZ_L_XL
        }


    def read_mag(self):
        """Read magnetometer data."""
        
        # Create synthetic data if in mock mode
        if self.mock_mode:
            self.mock_angle += 0.1
            return {
                'x': round(25.0 * math.sin(self.mock_angle), 2),
                'y': round(15.0 * math.sin(self.mock_angle / 2), 2),
                'z': round(10.0 * math.cos(self.mock_angle), 2),
            }
        
        def read_word(reg):
            low = self.bus.read_byte_data(gyroscope_config.addr_mag, reg)
            high = self.bus.read_byte_data(gyroscope_config.addr_mag, reg+1)
            val = (high << 8) + low
            return val if val < 32768 else val - 65536

        return {
            'x': read_word(gyroscope_config.mag_reg_out_x),
            'y': read_word(gyroscope_config.mag_reg_out_y),
            'z': read_word(gyroscope_config.mag_reg_out_z),
        }


    def run(self):
        """Continuously read gyroscope data and send it over TCP."""
        error = None
        failure_count = 0
        print_count = 0
        calib_count = 0
        while self.online:

            if self.calibration == True:
                gyro_data = self.read_gyro() # Get the gyroscope data
                self.calib_buffer_x.append(gyro_data.get("x"))
                self.calib_buffer_y.append(gyro_data.get("y"))
                self.calib_buffer_z.append(gyro_data.get("z"))


                calib_count += 1

                if calib_count >= gyroscope_config.calib_buffer_size:
                    self.calibration = False

                    self.x_ofset = sum(self.calib_buffer_x) / len(self.calib_buffer_x)
                    self.y_ofset = sum(self.calib_buffer_y) / len(self.calib_buffer_y)
                    self.z_ofset = sum(self.calib_buffer_z) / len(self.calib_buffer_z)
            else:
                try:
                    gyro_data = self.read_gyro() # Get the gyroscope data
                    accel_data = self.read_accel() # Get the accelerometer data
                    mag_data = self.read_mag() # Get the magnetometer data

                    gyro_data['x'] -= self.x_ofset
                    gyro_data['y'] -= self.y_ofset
                    gyro_data['z'] -= self.z_ofset

                    data = {"gyro": gyro_data, 
                            "accel": accel_data, 
                            "mag": mag_data} # Combine the data into a single dictionary

                    if self.tcp_server is not None:
                        self.tcp_server.send(
                        {
                            "type": "9dof",
                            "data": data
                        }, data_type='JSON', priority='high')
                        error = None
                        #self.tcp_server.send({
                        #    "type": "STATUS",
                        #    "data": "connection test"
                        #}, data_type="JSON", priority="high")
                    else:
                        print("[WARN] Gyroscope: No TCP sender available. Skipping data send.")
                    
                except Exception as e:
                    failure_count += 1
                    error = e
                    #print(f"[ERROR] Gyroscope: Failed sending message: {e}")

                print_count += 1
                #print("[INFO] Gyroscope: Data sent:", data)
                if print_count == 10:
                    print(data)
                    print_count = 0

                if error is not None and failure_count >= gyroscope_config.retry_attempts:
                    self.health_monitor.failure("Gyroscope", "Error reading gyro data")
                    self.online = False
                    print(f"[ERROR] Gyroscope: Error reading gyro data {error}.")
                    break

            time.sleep(gyroscope_config.update_rate)  # Sleep for the specified update rate
