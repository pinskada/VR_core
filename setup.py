from setuptools import setup, find_packages

setup(
    name="vr_core",
    version="0.1",
    packages=find_packages(),  # Automatically includes all folders with __init__.py
    install_requires=[
        "opencv-python",
        "numpy",
        # add other deps like "multiprocessing" (built-in), etc. if needed
    ],
)