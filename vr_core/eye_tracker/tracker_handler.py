import sys
import os
import subprocess
from pathlib import Path

class TrackerHandler:
    def __init__(self):
        python_path = sys.executable
        project_root = Path(__file__).resolve().parents[2]
        eyeloop_path = project_root / 'vr_core' / 'eye_tracker' / 'eyeloop_module'

        # Define environment with custom PYTHONPATH
        env = os.environ.copy()
        env["PYTHONPATH"] = str(eyeloop_path)

        # Define file paths
        video_folder = "test_eye_video"
        test_video_L = f"{video_folder}/testVideoNoCR_L.mp4"
        test_video_R = f"{video_folder}/testVideoNoCR_R.mp4"

        blink_folder = 'vr_core/eye_tracker/eyeloop_module/blink_calibration'
        blink_cal_L = f"{blink_folder}/blink_calibration_cropL.npy"
        blink_cal_R = f"{blink_folder}/blink_calibration_cropR.npy"

        pupil_folder = 'vr_core/eye_tracker/eyeloop_module/pupil_parameters'
        pupil_cal_L = f"{pupil_folder}/pupil_parameters_cropL.npy"
        pupil_cal_R = f"{pupil_folder}/pupil_parameters_cropR.npy"

        # Arguments using the -m approach with fixed imports
        args_left = [
            python_path, "-m", "eyeloop.run_eyeloop",
            "-s", "L",
            "-sc", "0.45",
            "-v", test_video_L,
            "-b", blink_cal_L,
            "-p", pupil_cal_L,
            "-fps", "5",
            "-trf", "20",
        ]

        args_right = [
            python_path, "-m", "eyeloop.run_eyeloop",
            "-s", "R",
            "-sc", "0.45",
            "-v", test_video_R,
            "-b", blink_cal_R,
            "-p", pupil_cal_R,
            "-fps", "5",
            "-thr", "2",
            "-trf", "20",
        ]

        # Start both subprocesses
        self.proc_left = subprocess.Popen(args_left, env=env)
        self.proc_right = subprocess.Popen(args_right, env=env)


if __name__ == "__main__":
    eyeloop = TrackerHandler()
    try:
        print(">> Running... Press Ctrl+C to stop.")

        eyeloop.proc_left.wait()
        eyeloop.proc_right.wait()
    except KeyboardInterrupt:
        print(">> Ctrl+C received. Terminating...")
        eyeloop.proc_left.terminate()
        eyeloop.proc_right.terminate()
    