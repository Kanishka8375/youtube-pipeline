"""
YouTube Video Generator - Desktop Application
===============================================

A simple desktop wrapper for the YouTube video generation pipeline.

INSTALLATION
------------
1. Ensure Python 3.8+ is installed
2. Install dependencies:
   pip install pywebview

RUNNING
-------
Double-click or run:
   python desktop_app/launcher.py

Or create a shortcut to launcher.py

FEATURES
--------
- Native desktop window (no browser needed)
- Real-time progress in terminal
- Video gallery with open button
- Cross-platform (Windows, macOS, Linux)

BUILDING EXECUTABLE
-------------------
Install PyInstaller:
   pip install pyinstaller

Build:
   pyinstaller --onefile --windowed desktop_app/launcher.py --name YouTubeVideoGenerator

The executable will be in dist/ folder.
"""

from setuptools import setup

setup(
    name="youtube-video-generator-desktop",
    version="1.0.0",
    description="Desktop application for AI-powered YouTube video generation",
    author="Your Name",
    # setup.py sits *inside* the package directory, so `find_packages()` looks
    # for sub-packages of desktop_app and finds none -- installing nothing while
    # still registering a console script that imports `desktop_app`. Map the name
    # onto this directory explicitly instead.
    package_dir={"desktop_app": "."},
    packages=["desktop_app"],
    install_requires=[
        "pywebview>=4.0",
    ],
    entry_points={
        "console_scripts": [
            "youtube-generator=desktop_app.launcher:main",
        ],
    },
    python_requires=">=3.8",
)
