from picamera2 import Picamera2

picam2 = Picamera2()
for mode in picam2.sensor_modes:
    print(mode)