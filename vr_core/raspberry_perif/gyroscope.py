
class Gyro:
    def __init__(self, bus, address):
        self.bus = bus
        self.address = address
        self.gyro_data = None

 