#!/usr/bin/env bash
# NokiCam launcher — activates venv then starts the app
cd "/home/nokikuji/Documents/NokiCam"
source "/home/nokikuji/Documents/NokiCam/.venv/bin/activate"
exec python "/home/nokikuji/Documents/NokiCam/main.py" "$@"
