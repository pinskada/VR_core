

class TrackerHandler:
    """
    Eye tracker handler for the VR core.
    """

    def __init__(self, config: object) -> None:
        self.config = config
        self.source = None  # Placeholder for source object
        self.width = 0
        self.height = 0
        self.center = (0, 0)



        #EyeLoop(sys.argv[1:], logger=None)