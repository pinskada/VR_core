from setuptools import setup, find_packages

install_requires = []

with open('requirements.txt') as f:
    for line in f.readlines():
        req = line.strip()
        if not req or req.startswith('#') or '://' in req:
            continue
        install_requires.append(req)

setup(
    name="vr_core",
    python_requires='==3.11',
    version="0.1",
    packages=find_packages(),  # Automatically includes all folders with __init__.py
    install_requires=[
        # add other deps like "multiprocessing" (built-in), etc. if needed
    ],
)