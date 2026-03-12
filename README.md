# NokiCam

A real-time webcam processing tool that fixes fisheye distortion, simulates natural focal lengths, removes backgrounds, and applies 100 live video filters — outputting a virtual camera that works in Zoom, Google Meet, OBS, Discord, and any other app that accepts a webcam input.

---

## Features

### Lens Correction
- **Fisheye / barrel distortion removal** using per-camera calibration or built-in estimated values
- **Focal length simulation** — dial from 24mm (wide angle) up to 85mm (portrait telephoto)
- Real-time GPU-accelerated processing via OpenCL (works on AMD, Intel, and NVIDIA GPUs)

### Background Effects
- **Background blur** (portrait / bokeh mode)
- **Custom background image** — replace your background with any JPG or PNG
- **Animated GIF backgrounds** — loop any GIF behind you
- **Invert mask** — replace yourself with an image instead (intentionally cursed)

### 100 Live Filters
Filters are split into two categories accessible from the Filters button:

**Useful (50):** Auto White Balance, Exposure Compensation, Noise Reduction, Edge Sharpening, Soft Focus, Background Blur, Chromatic Aberration Fix, Vignette Removal, Histogram Equalization, HDR Tone Mapping, Warm/Cool Color Temperature, Saturation Boost, Contrast Enhance, Shadow Lift, Highlight Recovery, Chroma Key, Virtual Background Replace, Face Centering, Low Light Boost, Stabilization, Letterbox, Mirror (H/V), Auto Face Brightness, Grayscale, Sepia, Red Eye Reduction, Zoom Smooth, Color Blind Assist (Deuteranopia / Protanopia / Tritanopia), High Contrast Mode, Blue Light Filter, Podcast Mode, Interview Mode, Screen Glare Reduction, Noise Gate, Auto Rotate, Timestamp Overlay, FPS Counter, Resolution Scaler, Night Vision, Depth of Field, Border Overlay, Watermark, Flip to Portrait, Cinematic Teal & Orange, Sharpness & Clarity Boost

**Funny (50):** Super Fisheye, Funhouse Mirror, Melting Face, Bobblehead, Tiny Planet, Kaleidoscope, Zoom Punch, Earthquake Shake, Static TV Glitch, VHS Rewind, Deep Fry, Minecraft Pixelate, Thermal Imaging, Predator Cloak, Matrix Rain, Googly Eyes, Spinning Vortex, Pincushion, Stretch H/V, Swirl, Underwater Ripple, Shatter Glass, Drunk Sway, Comic Book, Oil Painting, Watercolor Bleed, Pencil Sketch, Neon Glow, Infrared Film, Old Film Projector, Mirror Ball, Face Zoom Lock, Confetti Explosion, Eyes Wide, Shrinking Head, Pop Art Warhol, Glitch Slice, Hologram, Rotating Cube, Mirror Army, Squeeze Center, Big Nose Warp, Emoji Face Replace, Cartoon Cel Shading, Dissolve Static, Infinite Zoom Tunnel, Wind Blow, Dollar Store Beauty, Surveillance Cam

Many filters include **tuning sliders** that appear when the filter is enabled (distortion amount, zoom level, blur radius, pixel block size, etc.).

### Virtual Camera Output
Processed video is output as a virtual camera device that appears in Zoom, Meet, Discord, OBS, and any other app that accepts webcam input. Select **"NokiCam"** as your camera source.

### Performance
- GPU-accelerated remap/undistort via OpenCL (Intel Arc, AMD, NVIDIA, Intel integrated)
- Filters run at preview resolution (960×540) — 4× less work than full 1080p
- Heavy artistic filters (Oil Painting, Watercolor) use frame-skipping and half-resolution for smooth playback
- Face detection runs at 1/4 resolution with result caching

---

## Installation

### Linux (CachyOS / Arch / Ubuntu)

**Requirements:** Python 3.10+, a webcam

```bash
# Clone or download the NokiCam folder, then:
bash install.sh
```

The installer will:
1. Check your distro and Python version
2. Install `v4l2loopback` (the virtual camera kernel module)
3. Load the module and configure it to persist across reboots
4. Create a Python virtual environment and install all dependencies
5. Add NokiCam to your application launcher

**Launch:**
```bash
bash nokicam-launch.sh
# or find "NokiCam" in your application launcher (Hyprland, GNOME, KDE, etc.)
```

**Virtual camera name:** `NokiCam` — select it in Zoom/Meet/OBS under camera settings.

---

### Windows

**Requirements:** Windows 10 version 2004 (May 2020 Update) or later, a webcam

1. Download or copy the NokiCam folder to your PC
2. Double-click **`setup_windows.bat`**
3. Follow the on-screen prompts — it handles everything automatically

The installer will:
1. Install Python 3.11 via `winget` if not already installed
2. Create a Python virtual environment
3. Install all dependencies including the **Windows Media Foundation virtual camera driver** (built into Windows 10 2004+, no extra software required)
4. Create a **desktop shortcut** and **Start Menu entry**

**Launch:** Double-click the **NokiCam** shortcut on your desktop.

**Virtual camera name:** `NokiCam` — select it in Zoom/Meet/OBS under camera settings.

> **Note:** The virtual camera uses Windows' built-in Media Foundation API. No OBS or third-party drivers needed.

---

### macOS

**Requirements:** Python 3.10+, OBS Studio, a webcam

macOS does not have a built-in virtual camera API, so OBS is required as a driver.

1. Install [OBS Studio](https://obsproject.com) (free)
2. Open OBS once to activate the Virtual Camera plugin
3. Install Python 3.10+ from [python.org](https://www.python.org/downloads/)
4. Open Terminal and run:

```bash
cd path/to/NokiCam
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

5. In OBS, start the Virtual Camera
6. In Zoom/Meet/etc., select **"OBS Virtual Camera"** as your camera source

> OBS is only needed as a virtual camera driver — you don't need to configure anything in OBS beyond installing it. NokiCam handles all the video processing itself.

---

## Optional: Lens Calibration

For the most accurate fisheye correction, calibrate NokiCam for your specific webcam:

1. Print a 9×6 checkerboard pattern (any size, measure the square size in mm)
2. Run the calibration tool:
   ```bash
   source .venv/bin/activate && python calibrate.py
   ```
3. Hold the checkerboard in front of your camera from different angles
4. Press **Space** to capture frames (aim for 20+), then **Q** to calibrate
5. Results are saved to `config.json` and loaded automatically on next launch

Without calibration, NokiCam uses estimated values that work well for most 90° FOV webcams.

---

## Project Files

| File | Purpose |
|---|---|
| `main.py` | Application entry point and PyQt5 GUI |
| `processor.py` | Fisheye undistortion and background segmentation |
| `filters.py` | All 100 filter implementations |
| `filter_pipeline.py` | Active filter registry and frame pipeline |
| `virtual_cam.py` | Cross-platform virtual camera abstraction |
| `gpu_detect.py` | GPU detection and OpenCL configuration |
| `calibrate.py` | Lens calibration tool |
| `config.json` | Camera matrix, distortion coefficients, frame size |
| `settings.json` | User preferences (zoom, sliders, autostart) |
| `install.sh` | Linux installer |
| `setup_windows.bat` | Windows installer |
| `requirements.txt` | Python dependencies (Linux/macOS) |
| `requirements_windows.txt` | Python dependencies (Windows, without pyvirtualcam) |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Virtual camera not appearing in Zoom/Meet | Restart Zoom/Meet after launching NokiCam |
| Linux: virtual camera device not found | Run `sudo modprobe v4l2loopback devices=1 video_nr=10 card_label=NokiCam exclusive_caps=1` |
| Windows: virtual camera not working | Requires Windows 10 version 2004 or later. Check Settings → System → About for your version |
| Low FPS with filters | GPU is being used automatically. Heavy filters (Oil Painting, Watercolor) are limited by the algorithm, not hardware |
| Image still distorted after correction | Run `python calibrate.py` with your actual camera for accurate coefficients |
| Black corners in preview | Reduce the zoom/focal length slider toward 24mm |
| App won't open on Linux | Run `bash nokicam-launch.sh` in a terminal to see the error message |
