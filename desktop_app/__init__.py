"""Desktop wrapper around the video pipeline.

This file exists so `pip install -e .` from this directory installs something.
Without it setuptools finds no package here, the install silently succeeds
having installed nothing, and the `youtube-generator` command it registers
fails at import.
"""
