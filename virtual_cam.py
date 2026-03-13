"""
virtual_cam.py — Cross-platform virtual camera abstraction for NokiCam.

Auto-detects the best available backend without requiring user configuration.
Supports Linux (v4l2loopback), Windows (mediafoundation / unitycapture / obs),
and macOS (obs). Falls back to display-only mode if no virtual camera is available.
"""

from __future__ import annotations

import glob
import platform
import subprocess
import sys
import time
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    print(f"[VirtualCam] {msg}", flush=True)


def _linux_find_v4l2loopback_device() -> Optional[str]:
    """
    Scan /dev/video* and return the first device that is a v4l2loopback device
    with label 'NokiCam' or 'VirtualCam'. Falls back to /dev/video10 if present.
    """
    candidates = sorted(glob.glob("/dev/video*"))
    target_labels = {"nokicam", "virtualcam"}

    for dev in candidates:
        # Try to read the device name via v4l2-ctl
        try:
            result = subprocess.run(
                ["v4l2-ctl", "--device", dev, "--info"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            output = result.stdout.lower()
            if any(label in output for label in target_labels):
                return dev
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    # Fallback: /dev/video10 is the conventional v4l2loopback device
    if "/dev/video10" in candidates:
        return "/dev/video10"

    return None


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

def detect_backend() -> dict:
    """
    Probe available backends without opening a camera.

    Returns a dict with keys:
        platform  (str)  — 'linux', 'windows', 'darwin', or 'unknown'
        backend   (str)  — selected backend name or 'display-only'
        device    (str)  — device path / identifier, or '' for display-only
        available (bool) — True if a real virtual camera backend was found
        notes     (str)  — human-readable explanation
    """
    system = platform.system().lower()

    # Check whether pyvirtualcam is importable at all
    try:
        import pyvirtualcam  # noqa: F401
        _pvc_available = True
    except ImportError:
        _pvc_available = False

    result = {
        "platform": system if system in {"linux", "windows", "darwin"} else "unknown",
        "backend": "display-only",
        "device": "",
        "available": False,
        "notes": "",
    }

    # ------------------------------------------------------------------
    # Linux
    # ------------------------------------------------------------------
    if system == "linux":
        if not _pvc_available:
            result["notes"] = (
                "pyvirtualcam not installed; display-only mode active. "
                "Install pyvirtualcam and load v4l2loopback to enable virtual camera."
            )
            return result

        device = _linux_find_v4l2loopback_device()
        if device:
            result.update(
                backend="pyvirtualcam/v4l2loopback",
                device=device,
                available=True,
                notes=f"v4l2loopback device found at {device}.",
            )
        else:
            result["notes"] = (
                "No v4l2loopback device found. "
                "Load it with: sudo modprobe v4l2loopback devices=1 "
                "video_nr=10 card_label='VirtualCam' exclusive_caps=1"
            )
        return result

    # ------------------------------------------------------------------
    # Windows
    # ------------------------------------------------------------------
    if system == "windows":
        if not _pvc_available:
            result["notes"] = (
                "pyvirtualcam not installed; display-only mode active."
            )
            return result

        for backend_name in ("mediafoundation", "unitycapture", "obs"):
            result.update(
                backend=f"pyvirtualcam/{backend_name}",
                device=backend_name,
                available=True,
                notes=f"Will attempt pyvirtualcam backend '{backend_name}'.",
            )
            return result  # probe order; actual availability confirmed on open

    # ------------------------------------------------------------------
    # macOS
    # ------------------------------------------------------------------
    if system == "darwin":
        if not _pvc_available:
            result["notes"] = "pyvirtualcam not installed; display-only mode active."
            return result

        result.update(
            backend="pyvirtualcam/obs",
            device="obs",
            available=True,
            notes="macOS: will attempt pyvirtualcam with OBS plugin backend.",
        )
        return result

    # ------------------------------------------------------------------
    # Unknown platform
    # ------------------------------------------------------------------
    result["notes"] = f"Unsupported platform '{system}'; display-only mode active."
    return result


# ---------------------------------------------------------------------------
# VirtualCamera class
# ---------------------------------------------------------------------------

class VirtualCamera:
    """
    Cross-platform virtual camera output.

    Usage::

        with VirtualCamera(width=1920, height=1080, fps=30) as vcam:
            while True:
                frame_rgb = ...  # numpy array, dtype uint8, shape (H, W, 3)
                vcam.send(frame_rgb)
                vcam.sleep_until_next_frame()
    """

    def __init__(self, width: int, height: int, fps: int = 30) -> None:
        self._width = width
        self._height = height
        self._fps = fps
        self._vcam = None          # pyvirtualcam.Camera instance, if active
        self._active = False
        self._device_name = "display-only"
        self._frame_interval = 1.0 / fps
        self._last_frame_time: float = 0.0

        self._open()

    # ------------------------------------------------------------------
    # Internal open logic
    # ------------------------------------------------------------------

    def _open(self) -> None:
        system = platform.system().lower()

        try:
            import pyvirtualcam
        except ImportError:
            _log("pyvirtualcam not installed — running in display-only mode.")
            return

        if system == "linux":
            self._open_linux(pyvirtualcam)
        elif system == "windows":
            self._open_windows(pyvirtualcam)
        elif system == "darwin":
            self._open_macos(pyvirtualcam)
        else:
            _log(f"Unsupported platform '{system}' — running in display-only mode.")

    def _open_linux(self, pyvirtualcam) -> None:
        # First try the conventional device /dev/video10
        device = _linux_find_v4l2loopback_device() or "/dev/video10"

        _log(f"Linux: attempting v4l2loopback on {device} …")
        try:
            self._vcam = pyvirtualcam.Camera(
                width=self._width,
                height=self._height,
                fps=self._fps,
                device=device,
            )
            self._active = True
            self._device_name = f"pyvirtualcam/v4l2loopback ({device})"
            _log(f"Virtual camera active: {self._device_name}")
        except Exception as exc:
            _log(f"v4l2loopback failed ({exc}). Scanning other /dev/video* devices …")
            # Try every /dev/video* device
            for dev in sorted(glob.glob("/dev/video*")):
                if dev == device:
                    continue
                try:
                    self._vcam = pyvirtualcam.Camera(
                        width=self._width,
                        height=self._height,
                        fps=self._fps,
                        device=dev,
                    )
                    self._active = True
                    self._device_name = f"pyvirtualcam/v4l2loopback ({dev})"
                    _log(f"Virtual camera active: {self._device_name}")
                    return
                except Exception:
                    pass
            _log(
                "No usable v4l2loopback device found. "
                "Run: sudo modprobe v4l2loopback devices=1 video_nr=10 "
                "card_label='VirtualCam' exclusive_caps=1\n"
                "Falling back to display-only mode."
            )

    def _open_windows(self, pyvirtualcam) -> None:
        backends = ["mediafoundation", "unitycapture", "obs"]
        for backend in backends:
            _log(f"Windows: trying pyvirtualcam backend='{backend}' …")
            # Try with camera_name first (pyvirtualcam >= 0.9); fall back without
            for kwargs in ({"camera_name": "NokiCam"}, {}):
                try:
                    self._vcam = pyvirtualcam.Camera(
                        width=self._width,
                        height=self._height,
                        fps=self._fps,
                        backend=backend,
                        **kwargs,
                    )
                    self._active = True
                    self._device_name = f"pyvirtualcam/{backend}"
                    _log(f"Virtual camera active: {self._device_name}")
                    return
                except TypeError:
                    continue  # camera_name not supported, retry without
                except Exception as exc:
                    _log(f"  backend='{backend}' unavailable: {exc}")
                    break  # backend itself failed, try next one

        _log("No Windows virtual camera backend succeeded — display-only mode.")

    def _open_macos(self, pyvirtualcam) -> None:
        _log("macOS: trying pyvirtualcam backend='obs' …")
        try:
            self._vcam = pyvirtualcam.Camera(
                width=self._width,
                height=self._height,
                fps=self._fps,
                backend="obs",
            )
            self._active = True
            self._device_name = "pyvirtualcam/obs"
            _log(f"Virtual camera active: {self._device_name}")
        except Exception as exc:
            _log(
                f"macOS OBS virtual camera failed ({exc}). "
                "Install the OBS Virtual Camera plugin and start OBS first.\n"
                "Falling back to display-only mode."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """True if virtual camera is outputting (not display-only)."""
        return self._active

    @property
    def device_name(self) -> str:
        """Human-readable name of the active backend."""
        return self._device_name

    def send(self, rgb_frame: np.ndarray) -> None:
        """
        Send an RGB frame to the virtual camera.

        Parameters
        ----------
        rgb_frame:
            NumPy array with shape (H, W, 3), dtype uint8, in RGB colour order.
            No-op when running in display-only mode.
        """
        if self._vcam is not None:
            self._vcam.send(rgb_frame)
            self._last_frame_time = time.monotonic()

    def sleep_until_next_frame(self) -> None:
        """
        Throttle to the target FPS.

        Delegates to pyvirtualcam's own sleep when a real backend is active;
        uses a manual time.sleep() calculation in display-only mode.
        """
        if self._vcam is not None:
            self._vcam.sleep_until_next_frame()
        else:
            # Manual pacing for display-only mode
            now = time.monotonic()
            elapsed = now - self._last_frame_time
            remaining = self._frame_interval - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_frame_time = time.monotonic()

    def close(self) -> None:
        """Release the virtual camera and free resources."""
        if self._vcam is not None:
            try:
                self._vcam.__exit__(None, None, None)
            except Exception:
                pass
            self._vcam = None
        self._active = False
        _log(f"Virtual camera closed ({self._device_name}).")

    # Context-manager support
    def __enter__(self) -> "VirtualCamera":
        return self

    def __exit__(self, *args) -> None:
        self.close()

    def __repr__(self) -> str:
        status = "active" if self._active else "display-only"
        return (
            f"VirtualCamera(width={self._width}, height={self._height}, "
            f"fps={self._fps}, backend={self._device_name!r}, status={status!r})"
        )


# ---------------------------------------------------------------------------
# Quick self-test / CLI usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    info = detect_backend()
    print("Backend detection result:")
    for key, value in info.items():
        print(f"  {key}: {value}")
    print()

    _log("Opening VirtualCamera (1920×1080 @ 30 fps) …")
    with VirtualCamera(width=1920, height=1080, fps=30) as vcam:
        print(vcam)
        print(f"  is_active  : {vcam.is_active}")
        print(f"  device_name: {vcam.device_name}")

        if vcam.is_active:
            _log("Sending 30 black test frames …")
            blank = np.zeros((1080, 1920, 3), dtype=np.uint8)
            for _ in range(30):
                vcam.send(blank)
                vcam.sleep_until_next_frame()
            _log("Test frames sent successfully.")
        else:
            _log("Display-only mode — no frames sent.")
