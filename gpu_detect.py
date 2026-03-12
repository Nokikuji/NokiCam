"""
gpu_detect.py — GPU detection and OpenCV backend configuration for NokiCam.

Detects available GPU hardware via multiple methods (OpenCL, CUDA, lspci,
/proc/driver/nvidia, /sys/class/drm) and configures OpenCV accordingly.
Linux only.
"""

from __future__ import annotations

import dataclasses
import glob
import os
import subprocess
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclasses.dataclass
class GpuInfo:
    name: str = "CPU-only"
    vendor: str = "Unknown"
    has_opencl: bool = False
    has_cuda: bool = False
    opencl_version: str = ""
    backend: str = "cpu"  # "cuda" | "opencl" | "cpu"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _try_import_cv2():
    """Return the cv2 module or None if it is not installed."""
    try:
        import cv2  # noqa: PLC0415
        return cv2
    except ImportError:
        return None


def _detect_via_cuda(cv2) -> tuple[bool, int]:
    """Return (has_cuda, device_count)."""
    try:
        count = cv2.cuda.getCudaEnabledDeviceCount()
        return count > 0, count
    except Exception:
        return False, 0


def _detect_via_opencl(cv2) -> tuple[bool, str]:
    """Return (has_opencl, opencl_version_string)."""
    try:
        if not cv2.ocl.haveOpenCL():
            return False, ""
        # Attempt to get device info — this can fail on some drivers
        try:
            cv2.ocl.setUseOpenCL(True)
            device = cv2.ocl.Device.getDefault()
            if device.available():
                version = device.OpenCLVersion() or ""
                return True, version.strip()
        except Exception:
            pass
        return True, ""
    except Exception:
        return False, ""


def _opencl_device_name(cv2) -> Optional[str]:
    """Return the OpenCL device name, or None."""
    try:
        cv2.ocl.setUseOpenCL(True)
        device = cv2.ocl.Device.getDefault()
        if device.available():
            return device.name() or None
    except Exception:
        pass
    return None


def _detect_nvidia_proc() -> Optional[str]:
    """
    Parse /proc/driver/nvidia/gpus/ to find NVIDIA GPU model name.
    Returns the first GPU name found, or None.
    """
    gpu_base = "/proc/driver/nvidia/gpus"
    try:
        if not os.path.isdir(gpu_base):
            return None
        for gpu_dir in os.listdir(gpu_base):
            info_path = os.path.join(gpu_base, gpu_dir, "information")
            if not os.path.isfile(info_path):
                continue
            with open(info_path, "r", errors="replace") as fh:
                for line in fh:
                    if line.lower().startswith("model:"):
                        model = line.split(":", 1)[1].strip()
                        if model:
                            return model
    except Exception:
        pass
    return None


def _detect_via_lspci() -> tuple[Optional[str], Optional[str]]:
    """
    Run lspci and look for VGA / 3D / Display controller lines.
    Returns (vendor, name) where vendor is one of NVIDIA/AMD/Intel/Unknown,
    or (None, None) if lspci is unavailable or nothing useful found.
    """
    try:
        result = subprocess.run(
            ["lspci"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None, None

        vendor_keywords = {
            "NVIDIA": "NVIDIA",
            "Advanced Micro Devices": "AMD",
            "AMD": "AMD",
            "ATI": "AMD",
            "Intel": "Intel",
        }

        for line in result.stdout.splitlines():
            lower = line.lower()
            # Only look at display-class devices
            if not any(k in lower for k in ("vga", "3d controller", "display controller")):
                continue
            # Extract the description part (after the PCI address and class)
            # lspci format: "00:02.0 VGA compatible controller: Intel Corporation ..."
            if ":" in line:
                # Take everything after the second colon
                parts = line.split(":", 2)
                desc = parts[2].strip() if len(parts) > 2 else line
            else:
                desc = line

            for keyword, vendor in vendor_keywords.items():
                if keyword in desc:
                    return vendor, desc
            return "Unknown", desc

    except FileNotFoundError:
        # lspci not installed
        pass
    except Exception:
        pass
    return None, None


def _detect_via_drm() -> tuple[Optional[str], Optional[str]]:
    """
    Read /sys/class/drm/*/device/vendor to identify GPU vendor.
    PCI vendor IDs:
      0x10de → NVIDIA
      0x1002 → AMD
      0x8086 → Intel
    Returns (vendor_string, None) — no model name available from this path.
    """
    vendor_map = {
        "0x10de": "NVIDIA",
        "0x1002": "AMD",
        "0x8086": "Intel",
    }
    try:
        paths = glob.glob("/sys/class/drm/*/device/vendor")
        seen: set[str] = set()
        for path in sorted(paths):
            try:
                with open(path, "r") as fh:
                    raw = fh.read().strip().lower()
                if raw in seen:
                    continue
                seen.add(raw)
                vendor = vendor_map.get(raw)
                if vendor:
                    return vendor, None
            except Exception:
                continue
    except Exception:
        pass
    return None, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_gpu() -> GpuInfo:
    """
    Probe available hardware and return a populated GpuInfo.

    Detection order (fastest / most reliable first):
    1. NVIDIA proc filesystem  → confirms NVIDIA + gives model name
    2. lspci                   → vendor + model for any GPU
    3. /sys/class/drm          → vendor fallback (no model)
    4. OpenCV CUDA             → confirms CUDA support
    5. OpenCV OpenCL           → confirms OpenCL support + version
    """
    info = GpuInfo()
    cv2 = _try_import_cv2()

    # ------------------------------------------------------------------
    # Step 1: NVIDIA /proc
    # ------------------------------------------------------------------
    nvidia_model = _detect_nvidia_proc()
    if nvidia_model:
        info.vendor = "NVIDIA"
        info.name = nvidia_model

    # ------------------------------------------------------------------
    # Step 2: lspci
    # ------------------------------------------------------------------
    if info.vendor == "Unknown":
        lspci_vendor, lspci_name = _detect_via_lspci()
        if lspci_vendor:
            info.vendor = lspci_vendor
        if lspci_name and info.name == "CPU-only":
            info.name = lspci_name

    # ------------------------------------------------------------------
    # Step 3: /sys/class/drm (vendor only, last resort for name)
    # ------------------------------------------------------------------
    if info.vendor == "Unknown":
        drm_vendor, _ = _detect_via_drm()
        if drm_vendor:
            info.vendor = drm_vendor

    # ------------------------------------------------------------------
    # Step 4: OpenCV CUDA
    # ------------------------------------------------------------------
    if cv2 is not None:
        has_cuda, _cuda_count = _detect_via_cuda(cv2)
        info.has_cuda = has_cuda

    # ------------------------------------------------------------------
    # Step 5: OpenCV OpenCL
    # ------------------------------------------------------------------
    if cv2 is not None:
        has_opencl, opencl_ver = _detect_via_opencl(cv2)
        info.has_opencl = has_opencl
        info.opencl_version = opencl_ver

        # Try to fill name from OpenCL device if still unknown
        if info.name == "CPU-only":
            ocl_name = _opencl_device_name(cv2)
            if ocl_name:
                info.name = ocl_name

    # ------------------------------------------------------------------
    # Determine best backend
    # ------------------------------------------------------------------
    if info.has_cuda:
        info.backend = "cuda"
    elif info.has_opencl:
        info.backend = "opencl"
    else:
        info.backend = "cpu"

    # If we found *any* GPU info but name is still default, use vendor
    if info.name == "CPU-only" and info.vendor not in ("Unknown", ""):
        info.name = f"{info.vendor} GPU (model unknown)"

    return info


def configure_opencv(info: GpuInfo) -> None:
    """
    Apply the best available OpenCV acceleration settings and print a
    short status message describing what is active.
    """
    cv2 = _try_import_cv2()
    if cv2 is None:
        print("[gpu_detect] WARNING: cv2 not available — cannot configure OpenCV.")
        return

    # Always enable SIMD-optimised paths
    cv2.setUseOptimized(True)

    if info.backend == "cuda":
        # CUDA is used implicitly by cv2.cuda.* calls; nothing global to set.
        # We still enable OpenCL as a fallback for non-CUDA ops.
        if info.has_opencl:
            cv2.ocl.setUseOpenCL(True)
        cv2.setNumThreads(0)
        print(
            f"[gpu_detect] Backend: CUDA  |  GPU: {info.name}  |  "
            f"OpenCL fallback: {info.has_opencl}"
        )

    elif info.backend == "opencl":
        cv2.ocl.setUseOpenCL(True)
        cv2.setNumThreads(0)
        ver_str = f"  (OpenCL {info.opencl_version})" if info.opencl_version else ""
        print(
            f"[gpu_detect] Backend: OpenCL{ver_str}  |  GPU: {info.name}"
        )

    else:
        # CPU-only: disable OpenCL so we don't pay the overhead of failed
        # attempts, and let NumThreads=0 use all cores.
        cv2.ocl.setUseOpenCL(False)
        cv2.setNumThreads(0)
        print(
            "[gpu_detect] Backend: CPU-only  |  "
            "SIMD optimisations enabled  |  all threads available"
        )


# ---------------------------------------------------------------------------
# CLI diagnostic report
# ---------------------------------------------------------------------------

def _print_report(info: GpuInfo) -> None:
    sep = "-" * 50
    print(sep)
    print("  NokiCam GPU Diagnostic Report")
    print(sep)
    print(f"  GPU name       : {info.name}")
    print(f"  Vendor         : {info.vendor}")
    print(f"  Has CUDA       : {info.has_cuda}")
    print(f"  Has OpenCL     : {info.has_opencl}")
    print(f"  OpenCL version : {info.opencl_version or 'N/A'}")
    print(f"  Best backend   : {info.backend}")
    print(sep)

    cv2 = _try_import_cv2()
    if cv2 is None:
        print("  cv2 not installed — cannot report build info.")
    else:
        build = cv2.getBuildInformation()
        # Print only the CUDA / OpenCL sections to keep output compact
        in_section = False
        for line in build.splitlines():
            stripped = line.strip()
            if any(
                stripped.lower().startswith(s)
                for s in ("cuda:", "opencl:", "video i/o:", "cpu/hw features")
            ):
                in_section = True
            elif stripped == "" and in_section:
                in_section = False
            if in_section:
                print(" ", line)
    print(sep)


if __name__ == "__main__":
    _info = detect_gpu()
    _print_report(_info)
    print()
    configure_opencv(_info)
