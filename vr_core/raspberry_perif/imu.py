"""Gyroscope module for VR Core on Raspberry Pi."""

import itertools
import os
import math
import time
from queue import Queue, PriorityQueue
from typing import Any
import platform

try:
    import smbus2
except ImportError:  # ImportError on dev machines without smbus2
    smbus2 = None  # type: ignore

from vr_core.base_service import BaseService
from vr_core.config_service.config import Config
from vr_core.ports.signals import IMUSignals
from vr_core.utilities.logger_setup import setup_logger
from vr_core.network.comm_contracts import MessageType


class Imu(BaseService):
    """Gyroscope module for VR Core on Raspberry Pi."""
    def __init__(
        self,
        comm_router_q: PriorityQueue,
        pq_counter: itertools.count,
        gyro_mag_q: Queue,
        imu_signals: IMUSignals,
        config: Config,
        imu_mock_mode_s: bool = False,
        ) -> None:

        super().__init__("IMU")
        self.logger = setup_logger("IMU")

        self.comm_router_q = comm_router_q
        self.pq_counter = pq_counter
        self.gyro_mag_q = gyro_mag_q

        self.imu_send_over_tcp_s = imu_signals.imu_send_over_tcp_s
        self.imu_send_to_gaze_s = imu_signals.imu_send_to_gaze_s
        self.hold_imu_during_calib_s = imu_signals.hold_imu_during_calib_s

        self.cfg = config
        self._unsubscribe = config.subscribe("IMU",
            self._on_config_changed
        )

        self.bus: Any = None

        self.x_offset: float
        self.y_offset: float
        self.z_offset: float

        self.mock_angle = 0.0
        self.mock_mode = imu_mock_mode_s

        self.send_counter: int = 0

        self.online = False

        #self.logger.info("Service initialized.")



# ---------- BaseService lifecycle ----------

    def _on_start(self) -> None:
        """Initialize the gyroscope sensor."""

        self.imu_send_over_tcp_s.set()

        if platform.system() != "Linux":
            self.logger.info("Non-Linux system detected; forcing mock mode.")
            self.mock_mode = True

        if not self.mock_mode:
            if self._ensure_i2c_enabled() is False:
                raise RuntimeError("I2C not enabled")
            self._init_imu()
            self._calibrate_gyro()
        else:
            self.logger.info("Running in mock mode; skipping IMU initialization.")

        self.online = True
        self._ready.set()
        #self.logger.info("Service is ready.")


    def _run(self) -> None:
        """Start the gyroscope data reading loop."""
        while not self._stop.is_set():
            self._process_imu()
            self._stop.wait(self.cfg.imu.update_rate)  # Sleep for the specified update rate


    def _on_stop(self) -> None:
        """Stop the gyroscope thread."""

        self.online = False
        #self.logger.info("Service stopped.")


# ------------- Internals -------------

    def _ensure_i2c_enabled(self) -> bool:
        """Check if I2C is enabled on the Raspberry Pi."""

        if not os.path.exists("/dev/i2c-1"):
            self.logger.error("I2C interface not found.")
            self.logger.info("Run 'sudo raspi-config' > Interface Options > I2C > Enable")
            return False
        else:
            return True


    def _init_imu(self) -> None:
        """Initialize the IMU sensor."""

        if smbus2 is None:
            self.logger.error("smbus2 not installed. Run 'pip install smbus2' or enable mock mode.")
            raise RuntimeError("smbus2 not installed")

        try:
            # I2C bus number
            self.bus = smbus2.SMBus(self.cfg.imu.bus_num)

            # --- Initialize LSM6DS33 (gyro + accel) ---
            # Enable Gyroscope: 104 Hz, 2000 dps full scale
            # CTRL2_G: ODR = 104 Hz, FS = ±2000 dps
            self.bus.write_byte_data(self.cfg.imu.addr_gyr_acc, 0x11, 0x4C)

            # TODO: Check which setting is correct

            # CTRL1_XL: ODR = 104 Hz, FS = ±2g
            #self.bus.write_byte_data(self.cfg.imu.addr_gyr_acc, 0x11, 0x40)

            # Enable Accelerometer: 104 Hz, ±2g full scale
            # CTRL1_XL: ODR = 104 Hz, FS = ±2g
            self.bus.write_byte_data(self.cfg.imu.addr_gyr_acc, 0x10, 0x4C)

            # --- Initialize LIS3MDL (magnetometer) ---
            # Enable Magnetometer: Ultra-high performance, 80 Hz

            # CTRL_REG1: Temp disable, Ultra-high perf, 80 Hz
            self.bus.write_byte_data(self.cfg.imu.addr_mag, 0x20, 0x7E)
            # CTRL_REG2: Full scale ±4 gauss
            self.bus.write_byte_data(self.cfg.imu.addr_mag, 0x21, 0x60)
            # CTRL_REG3: Continuous-conversion mode
            self.bus.write_byte_data(self.cfg.imu.addr_mag, 0x22, 0x00)
            # CTRL_REG4: Ultra-high perf on Z
            self.bus.write_byte_data(self.cfg.imu.addr_mag, 0x23, 0x0C)

            #CTRL1_XL = 0x10 → Accelerometer config: 104Hz, ±2g, 400Hz bandwidth
            self.bus.write_byte_data(self.cfg.imu.addr_gyr_acc, 0x10, 0x40)

            # CTRL9_XL = 0x18 → Enable all accel axes
            # XEN_XL | YEN_XL | ZEN_XL
            self.bus.write_byte_data(self.cfg.imu.addr_gyr_acc, 0x18, 0x38)

            # CTRL3_C = 0x12 → Enable BDU (Block Data Update)
            # BDU = 1, IF_INC = 1
            self.bus.write_byte_data(self.cfg.imu.addr_gyr_acc, 0x12, 0x44)

        except OSError as e:
            self.logger.error("Failed to initialize IMU sensor: %s.", e)
            raise RuntimeError("Failed to initialize IMU sensor.") from e


    def _calibrate_gyro(self) -> None:
        """Calibrate the gyroscope sensor."""

        calib_buffer_x: list[float] = []
        calib_buffer_y: list[float] = []
        calib_buffer_z: list[float] = []

        for _ in range(self.cfg.imu.calib_buffer_size):
            gyro_data = self._read_gyro() # Get the gyroscope data
            calib_buffer_x.append(gyro_data["x"])
            calib_buffer_y.append(gyro_data["y"])
            calib_buffer_z.append(gyro_data["z"])

        self.x_offset = sum(calib_buffer_x) / len(calib_buffer_x)
        self.y_offset = sum(calib_buffer_y) / len(calib_buffer_y)
        self.z_offset = sum(calib_buffer_z) / len(calib_buffer_z)
        self.logger.info("%s ; %s ; %s", self.x_offset, self.y_offset, self.z_offset)

    def _read_gyro(self) -> dict[str, float]:
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
            low = self.bus.read_byte_data(self.cfg.imu.addr_gyr_acc, reg)
            high = self.bus.read_byte_data(self.cfg.imu.addr_gyr_acc, reg+1)
            val = (high << 8) + low
            return val if val < 32768 else val - 65536

        return {
            'x': read_word(self.cfg.imu.gyro_reg_out_x) * self.cfg.imu.scale_factor,
            'y': read_word(self.cfg.imu.gyro_reg_out_y) * self.cfg.imu.scale_factor,
            'z': read_word(self.cfg.imu.gyro_reg_out_z) * self.cfg.imu.scale_factor,
        }


    def _read_accel(self) -> dict[str, float]:
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
            low = self.bus.read_byte_data(self.cfg.imu.addr_gyr_acc, reg)
            high = self.bus.read_byte_data(self.cfg.imu.addr_gyr_acc, reg+1)
            val = (high << 8) + low
            return val if val < 32768 else val - 65536

        return {
            'x': read_word(self.cfg.imu.acc_reg_out_x),  # OUTX_L_XL
            'y': read_word(self.cfg.imu.acc_reg_out_y),  # OUTY_L_XL
            'z': read_word(self.cfg.imu.acc_reg_out_z),  # OUTZ_L_XL
        }


    def _read_mag(self) -> dict[str, float]:
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
            low = self.bus.read_byte_data(self.cfg.imu.addr_mag, reg)
            high = self.bus.read_byte_data(self.cfg.imu.addr_mag, reg+1)
            val = (high << 8) + low
            return val if val < 32768 else val - 65536

        return {
            'x': read_word(self.cfg.imu.mag_reg_out_x),
            'y': read_word(self.cfg.imu.mag_reg_out_y),
            'z': read_word(self.cfg.imu.mag_reg_out_z),
        }


    def _process_imu(self):
        """Continuously read IMU data and send it over TCP and/or to gaze module."""

        retry_attempt = 0

        #self.logger.info("Processing IMU data.")

        for _ in range(self.cfg.imu.retry_attempts):
            try:
                # Read sensor data
                gyro_data = self._read_gyro()
                accel_data = self._read_accel()
                mag_data = self._read_mag()
                timestamp = time.perf_counter_ns() / 1e9

                # Apply calibration offsets
                if not self.mock_mode:
                    gyro_data['x'] -= self.x_offset
                    gyro_data['y'] -= self.y_offset
                    gyro_data['z'] -= self.z_offset

                data = {
                    "gyro": gyro_data,
                    "accel": accel_data,
                    "mag": mag_data,
                    "timestamp": timestamp
                }

                #self.logger.info(data)

                if (
                    self.imu_send_over_tcp_s.is_set() and
                    not self.hold_imu_during_calib_s.is_set()
                ):
                    self.send_counter += 1
                    if self.send_counter % 20 == 0:
                        # sel f.logger.info(data)
                        self.send_counter = 0
                    # Send data via TCP
                    tcp_tuple = (
                        1, next(self.pq_counter),
                        MessageType.imuSensor,
                        data
                        )
                    # self.comm_router_q.put(tcp_tuple)
                else:
                    self.send_counter += 1
                    if self.send_counter % 10 == 0:
                        #self.logger.info("imu_send_over_tcp_s is not set.")
                        self.send_counter = 0

                if self.imu_send_to_gaze_s.is_set():
                    self.gyro_mag_q.put(data)

                break

            except (OSError, IOError, ConnectionError, ValueError, AttributeError) as e:
                # Catch expected I/O / networking / value / attribute errors explicitly
                retry_attempt += 1
                self.logger.warning("Failed sending message: %s", e)

                if retry_attempt >= self.cfg.imu.retry_attempts:
                    self.online = False
                    self.logger.error("Max retry attempts reached. Skipping this IMU read.")
                    raise RuntimeError("Max retry attempts reached for IMU processing.") from e

    #  pylint: disable=unused-argument
    def _on_config_changed(self, path: str, old_val: Any, new_val: Any) -> None:
        """Handle configuration changes."""
