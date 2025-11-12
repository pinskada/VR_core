from picamera2 import Picamera2
import time
p = Picamera2()
p.start()
time.sleep(2)
p.stop()
print("Picamera2 OK")
