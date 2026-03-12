"""
filters.py — NokiCam: 100 real-time video filters
Useful (1-50): correction, enhancement, accessibility
Funny (51-100): distortion, effects, artistic
"""

from __future__ import annotations

import time
import math
import threading
import cv2
import numpy as np
from datetime import datetime

# ---------------------------------------------------------------------------
# GPU / OpenCL
# ---------------------------------------------------------------------------
cv2.ocl.setUseOpenCL(True)  # use GPU via OpenCL for eligible operations

# ---------------------------------------------------------------------------
# Module-level shared resources
# ---------------------------------------------------------------------------

_face_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)
_eye_cascade = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_eye.xml"
)
_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
_clahe_strong = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(8, 8))

_SEPIA_KERNEL = np.array([
    [0.272, 0.534, 0.131],
    [0.349, 0.686, 0.168],
    [0.393, 0.769, 0.189],
], dtype=np.float32)

# ---------------------------------------------------------------------------
# Per-filter parameter system (thread-safe)
# ---------------------------------------------------------------------------

_params_lock = threading.Lock()

# Default values for every tunable parameter
_filter_params: dict[str, dict[str, float]] = {
    "Noise Reduction":       {"d": 7},
    "Face Centering":        {"zoom": 1.3},
    "Podcast Mode":          {"zoom": 1.6},
    "Super Fisheye":         {"dist": 0.85},
    "Exposure Compensation": {"ev": 0.5},
    "Saturation Boost":      {"factor": 1.4},
    "Low Light Boost":       {"gain": 2.5},
    "Blue Light Filter":     {"reduction": 0.25},
    "Depth of Field":        {"radius": 15},
    "Minecraft Pixelate":    {"block": 16},
    "Edge Sharpening":       {"amount": 1.2},
    "Shadow Lift":           {"lift": 30.0},
    "Letterbox":             {"fraction": 0.10},
    "Background Blur":       {"radius": 21},
    "Drunk Sway":            {"amount": 8.0},
    "Underwater Ripple":     {"amp": 8.0},
    "Wind Blow":             {"length": 35},
    "Zoom Smooth":           {"max_zoom": 1.2},
}

def get_param(filter_name: str, key: str, default=None):
    with _params_lock:
        return _filter_params.get(filter_name, {}).get(key, default)

def set_param(filter_name: str, key: str, value):
    with _params_lock:
        if filter_name not in _filter_params:
            _filter_params[filter_name] = {}
        _filter_params[filter_name][key] = value

# Specification for the UI: {filter_name: [(label, key, default, min, max, step, display_scale)]}
# display_scale: multiply stored value by this for display (e.g. 100 to show %)
FILTER_PARAMS_SPEC: dict[str, list[tuple]] = {
    "Noise Reduction":       [("Strength", "d", 7, 1, 15, 1, 1)],
    "Face Centering":        [("Zoom", "zoom", 1.3, 1.0, 2.5, 0.05, 100)],
    "Podcast Mode":          [("Zoom", "zoom", 1.6, 1.0, 2.5, 0.05, 100)],
    "Super Fisheye":         [("Distortion %", "dist", 0.85, 0.1, 4.0, 0.05, 100)],
    "Exposure Compensation": [("EV", "ev", 0.5, -2.0, 2.0, 0.1, 10)],
    "Saturation Boost":      [("Amount %", "factor", 1.4, 0.5, 3.0, 0.05, 100)],
    "Low Light Boost":       [("Gain", "gain", 2.5, 1.0, 5.0, 0.1, 10)],
    "Blue Light Filter":     [("Reduction %", "reduction", 0.25, 0.0, 0.8, 0.05, 100)],
    "Depth of Field":        [("Blur Radius", "radius", 15, 3, 40, 1, 1)],
    "Minecraft Pixelate":    [("Block Size", "block", 16, 4, 64, 2, 1)],
    "Edge Sharpening":       [("Amount %", "amount", 1.2, 0.1, 3.0, 0.05, 100)],
    "Shadow Lift":           [("Lift", "lift", 30.0, 5.0, 80.0, 5.0, 1)],
    "Letterbox":             [("Bar Size %", "fraction", 0.10, 0.02, 0.25, 0.01, 100)],
    "Background Blur":       [("Radius", "radius", 21, 3, 61, 2, 1)],
    "Drunk Sway":            [("Sway", "amount", 8.0, 1.0, 20.0, 0.5, 1)],
    "Underwater Ripple":     [("Amplitude", "amp", 8.0, 1.0, 30.0, 1.0, 1)],
    "Wind Blow":             [("Strength", "length", 35, 5, 80, 5, 1)],
    "Zoom Smooth":           [("Max Zoom %", "max_zoom", 1.2, 1.05, 2.0, 0.05, 100)],
}

# ---------------------------------------------------------------------------
# Face detection helper — runs at 1/4 resolution for speed (16× faster)
# ---------------------------------------------------------------------------
_face_detect_scale = 4   # detect at 1/N resolution
_face_cache: dict[int, tuple] = {}   # thread_id → (last_faces, frame_counter)
_face_skip = 2           # re-detect every N frames

def _detect_faces(gray):
    """Detect faces at 1/4 resolution and scale coords back up."""
    tid = threading.get_ident()
    cache = _face_cache.get(tid, (None, 0))
    last_faces, counter = cache
    counter += 1
    _face_cache[tid] = (last_faces, counter)

    if last_faces is not None and counter % _face_skip != 0:
        return last_faces  # return cached result

    s = _face_detect_scale
    h, w = gray.shape[:2]
    small = cv2.resize(gray, (max(1, w // s), max(1, h // s)))
    faces = _face_cascade.detectMultiScale(small, 1.1, 4, minSize=(15, 15))
    if len(faces) > 0:
        faces = faces * s  # scale coordinates back to full resolution
    _face_cache[tid] = (faces, counter)
    return faces


def _to_uint8(arr):
    return np.clip(arr, 0, 255).astype(np.uint8)


# ===========================================================================
# USEFUL FILTERS (1-50)
# ===========================================================================

# 1. Auto White Balance
def auto_white_balance(frame):
    r = frame.astype(np.float32)
    mb, mg, mr = r[:,:,0].mean(), r[:,:,1].mean(), r[:,:,2].mean()
    mean_gray = (mb + mg + mr) / 3.0
    if mb > 0: r[:,:,0] *= mean_gray / mb
    if mg > 0: r[:,:,1] *= mean_gray / mg
    if mr > 0: r[:,:,2] *= mean_gray / mr
    return _to_uint8(r)

# 2. Exposure Compensation
def exposure_compensation(frame):
    ev = get_param("Exposure Compensation", "ev", 0.5)
    return _to_uint8(frame.astype(np.float32) * (2.0 ** ev))

# 3. Noise Reduction (fast bilateral + median combo)
def noise_reduction(frame):
    d = int(get_param("Noise Reduction", "d", 7))
    denoised = cv2.bilateralFilter(frame, d=d, sigmaColor=50, sigmaSpace=50)
    return cv2.medianBlur(denoised, 3)

# 4. Edge Sharpening
def edge_sharpening(frame):
    amount = get_param("Edge Sharpening", "amount", 1.2)
    blurred = cv2.GaussianBlur(frame, (3, 3), 0)
    return cv2.addWeighted(frame, 1.0 + amount, blurred, -amount, 0)

# 5. Soft Focus / Skin Smoothing
def soft_focus(frame):
    return cv2.bilateralFilter(frame, d=9, sigmaColor=75, sigmaSpace=75)

# 6. Background Blur (portrait mode)
def background_blur(frame):
    h, w = frame.shape[:2]
    r = int(get_param("Background Blur", "radius", 21)) | 1  # force odd
    blurred = cv2.GaussianBlur(frame, (r, r), 0)
    mask = np.zeros((h, w), dtype=np.float32)
    cv2.ellipse(mask, (w//2, h//2), (int(w*0.35), int(h*0.45)), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (61, 61), 0)[:,:,np.newaxis]
    return _to_uint8(frame.astype(np.float32) * mask + blurred.astype(np.float32) * (1-mask))

# 7. Chromatic Aberration Fix
def chromatic_aberration_fix(frame):
    h, w = frame.shape[:2]
    result = frame.copy()
    M_r = np.float32([[1, 0, 1], [0, 1, 0]])
    M_b = np.float32([[1, 0, -1], [0, 1, 0]])
    result[:,:,2] = cv2.warpAffine(frame[:,:,2], M_r, (w, h), borderMode=cv2.BORDER_REPLICATE)
    result[:,:,0] = cv2.warpAffine(frame[:,:,0], M_b, (w, h), borderMode=cv2.BORDER_REPLICATE)
    return result

# 8. Vignette Removal
def vignette_removal(frame):
    h, w = frame.shape[:2]
    Y, X = np.ogrid[:h, :w]
    dist = np.sqrt(((X - w/2.0)/(w/2.0))**2 + ((Y - h/2.0)/(h/2.0))**2).astype(np.float32)
    gain = 1.0 + 0.5 * np.clip(dist, 0, 1)**2
    return _to_uint8(frame.astype(np.float32) * gain[:,:,np.newaxis])

# 9. Histogram Equalization (CLAHE)
def histogram_equalization(frame):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lab[:,:,0] = _clahe.apply(lab[:,:,0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

# 10. HDR Tone Mapping
def hdr_tone_mapping(frame):
    img = frame.astype(np.float32) / 255.0
    img = img / (1.0 + img)
    img = np.power(img / (img.max() + 1e-6), 1.0 / 1.2)
    return _to_uint8(img * 255.0)

# 11. Color Temperature Warm
def color_temperature_warm(frame):
    r = frame.astype(np.float32)
    r[:,:,2] *= 1.15; r[:,:,1] *= 1.06; r[:,:,0] *= 0.85
    return _to_uint8(r)

# 12. Color Temperature Cool
def color_temperature_cool(frame):
    r = frame.astype(np.float32)
    r[:,:,0] *= 1.15; r[:,:,1] *= 1.03; r[:,:,2] *= 0.85
    return _to_uint8(r)

# 13. Saturation Boost
def saturation_boost(frame):
    factor = get_param("Saturation Boost", "factor", 1.4)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1] * factor, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

# 14. Contrast Enhance
def contrast_enhance(frame):
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lab[:,:,0] = _clahe_strong.apply(lab[:,:,0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

# 15. Shadow Lift
def shadow_lift(frame):
    lift = get_param("Shadow Lift", "lift", 30.0)
    lut = np.arange(256, dtype=np.float32)
    lut = lut + lift * (1.0 - lut / 255.0)**2
    return cv2.LUT(frame, np.clip(lut, 0, 255).astype(np.uint8))

# 16. Highlight Recovery
def highlight_recovery(frame):
    lut = np.arange(256, dtype=np.float32)
    mask = lut > 220
    over = lut[mask] - 220
    lut[mask] = 220 + over * 0.4
    return cv2.LUT(frame, np.clip(lut, 0, 255).astype(np.uint8))

# 17. Green Screen / Chroma Key
def chroma_key(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35,80,60]), np.array([85,255,255]))
    mask = cv2.dilate(mask, np.ones((3,3), np.uint8), iterations=1)
    result = frame.copy()
    result[mask > 0] = 0
    return result

# 18. Virtual Background Replace
def virtual_background_replace(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, np.array([35,80,60]), np.array([85,255,255]))
    mask = cv2.dilate(mask, np.ones((3,3), np.uint8), iterations=1)
    result = frame.copy()
    result[mask > 0] = (0, 120, 0)
    return result

# 19. Face Centering / Auto-Crop
class FaceCentering:
    def __init__(self):
        self._last_rect = None
        self._param_key = "Face Centering"
    def __call__(self, frame):
        h, w = frame.shape[:2]
        zoom = get_param(self._param_key, "zoom", 1.3)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = _detect_faces(gray)
        if len(faces) > 0:
            face = max(faces, key=lambda r: r[2]*r[3])
            fx, fy, fw, fh = face.astype(float)
            cx, cy = fx+fw/2, fy+fh/2
            target = np.array([cx, cy, fw*zoom, fh*zoom])
            if self._last_rect is None:
                self._last_rect = target
            else:
                self._last_rect += 0.15 * (target - self._last_rect)
        if self._last_rect is None:
            return frame
        cx, cy, rw, rh = self._last_rect
        side = max(rw, rh)
        x1, y1 = max(0, int(cx-side/2)), max(0, int(cy-side/2))
        x2, y2 = min(w, int(cx+side/2)), min(h, int(cy+side/2))
        if x2 <= x1 or y2 <= y1:
            return frame
        return cv2.resize(frame[y1:y2, x1:x2], (w, h))

# 20. Low Light Boost
def low_light_boost(frame):
    gain = get_param("Low Light Boost", "gain", 2.5)
    return _to_uint8(frame.astype(np.float32) * gain)

# 21. Stabilization (digital)
class Stabilization:
    def __init__(self):
        self._prev_gray = None
        self._accum = np.eye(2, 3, dtype=np.float32)
    def __call__(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = frame.shape[:2]
        if self._prev_gray is None:
            self._prev_gray = gray
            return frame
        warp = np.eye(2, 3, dtype=np.float32)
        try:
            # 15 iterations is enough for real-time; 50 was overkill
            _, warp = cv2.findTransformECC(self._prev_gray, gray, warp,
                cv2.MOTION_EUCLIDEAN,
                (cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT, 15, 1e-3),
                inputMask=None, gaussFiltSize=5)
            self._accum = 0.7 * self._accum + 0.3 * warp
        except cv2.error:
            pass
        self._prev_gray = gray
        inv = cv2.invertAffineTransform(self._accum)
        return cv2.warpAffine(frame, inv, (w, h), borderMode=cv2.BORDER_REPLICATE)

# 22. Letterbox / Cinematic Bars
def letterbox(frame):
    h, w = frame.shape[:2]
    fraction = get_param("Letterbox", "fraction", 0.10)
    result = frame.copy()
    bar = int(h * fraction)
    result[:bar, :] = 0
    result[h-bar:, :] = 0
    return result

# 23. Mirror Flip Horizontal
def mirror_horizontal(frame):
    return cv2.flip(frame, 1)

# 24. Mirror Flip Vertical
def mirror_vertical(frame):
    return cv2.flip(frame, 0)

# 25. Auto Face Brightness
class AutoFaceBrightness:
    def __call__(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = _detect_faces(gray)
        if len(faces) == 0:
            return frame
        face = max(faces, key=lambda r: r[2]*r[3])
        fx, fy, fw, fh = face
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype(np.float32)
        mean_L = lab[fy:fy+fh, fx:fx+fw, 0].mean()
        if mean_L < 1:
            return frame
        lab[:,:,0] = np.clip(lab[:,:,0] * (140.0 / mean_L), 0, 255)
        return cv2.cvtColor(lab.astype(np.uint8), cv2.COLOR_LAB2BGR)

# 26. Grayscale
def grayscale(frame):
    return cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)

# 27. Sepia Tone
def sepia_tone(frame):
    return _to_uint8(cv2.transform(frame.astype(np.float32), _SEPIA_KERNEL))

# 28. Red Eye Reduction
def red_eye_reduction(frame):
    result = frame.copy()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray)
    for (fx, fy, fw, fh) in faces:
        eyes = _eye_cascade.detectMultiScale(gray[fy:fy+fh, fx:fx+fw], 1.1, 10, minSize=(20,20))
        for (ex, ey, ew, eh) in eyes:
            roi = result[fy+ey:fy+ey+eh, fx+ex:fx+ex+ew]
            r, g, b = roi[:,:,2].astype(np.float32), roi[:,:,1].astype(np.float32), roi[:,:,0].astype(np.float32)
            red_mask = (r > 100) & (r > 1.5*g) & (r > 1.5*b)
            roi[:,:,2][red_mask] = ((g + b) / 2).astype(np.uint8)[red_mask]
    return result

# 29. Zoom Smooth (animated pulsing)
class ZoomSmooth:
    def __init__(self):
        self._start = time.monotonic()
    def __call__(self, frame):
        t = (math.sin(2*math.pi*(time.monotonic()-self._start)/4.0)+1)/2.0
        max_zoom = get_param("Zoom Smooth", "max_zoom", 1.2)
        zoom = 1.0 + t * (max_zoom - 1.0)
        h, w = frame.shape[:2]
        nw, nh = int(w/zoom), int(h/zoom)
        x1, y1 = (w-nw)//2, (h-nh)//2
        return cv2.resize(frame[y1:y1+nh, x1:x1+nw], (w, h))

# 30. Color Blind Assist (Deuteranopia)
def colorblind_deuteranopia(frame):
    r = frame.astype(np.float32)
    R, G, B = r[:,:,2].copy(), r[:,:,1].copy(), r[:,:,0].copy()
    r[:,:,2] = np.clip(0.625*R + 0.375*G, 0, 255)
    r[:,:,1] = np.clip(0.7*R + 0.3*G, 0, 255)
    r[:,:,0] = np.clip(0.1*G + 0.9*B, 0, 255)
    return r.astype(np.uint8)

# 31. Color Blind Assist (Protanopia)
def colorblind_protanopia(frame):
    r = frame.astype(np.float32)
    R, G, B = r[:,:,2].copy(), r[:,:,1].copy(), r[:,:,0].copy()
    r[:,:,2] = np.clip(0.567*R + 0.433*G, 0, 255)
    r[:,:,1] = np.clip(0.558*R + 0.442*G, 0, 255)
    r[:,:,0] = np.clip(0.242*G + 0.758*B, 0, 255)
    return r.astype(np.uint8)

# 32. Color Blind Assist (Tritanopia)
def colorblind_tritanopia(frame):
    r = frame.astype(np.float32)
    R, G, B = r[:,:,2].copy(), r[:,:,1].copy(), r[:,:,0].copy()
    r[:,:,2] = np.clip(0.95*R + 0.05*G, 0, 255)
    r[:,:,1] = np.clip(0.433*G + 0.567*B, 0, 255)
    r[:,:,0] = np.clip(0.475*G + 0.525*B, 0, 255)
    return r.astype(np.uint8)

# 33. High Contrast Mode
def high_contrast_mode(frame):
    clahe_hc = cv2.createCLAHE(clipLimit=6.0, tileGridSize=(4, 4))
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    lab[:,:,0] = clahe_hc.apply(lab[:,:,0])
    enhanced = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
    return saturation_boost(enhanced)

# 34. Blue Light Filter
def blue_light_filter(frame):
    reduction = get_param("Blue Light Filter", "reduction", 0.25)
    r = frame.astype(np.float32)
    r[:,:,0] *= (1.0 - reduction)
    return _to_uint8(r)

# 35. Podcast Mode
class PodcastMode:
    def __init__(self):
        self._fc = FaceCentering()
        self._fc._param_key = "Podcast Mode"
    def __call__(self, frame):
        cropped = self._fc(frame)
        smoothed = cv2.bilateralFilter(cropped, d=9, sigmaColor=75, sigmaSpace=75)
        h, w = smoothed.shape[:2]
        Y, X = np.ogrid[:h, :w]
        dist = np.sqrt(((X-w/2.0)/(w/2.0))**2 + ((Y-h/2.0)/(h/2.0))**2).astype(np.float32)
        vig = np.clip(1.0 - 0.4*dist**2, 0.5, 1.0)
        return _to_uint8(smoothed.astype(np.float32) * vig[:,:,np.newaxis])

# 36. Interview Mode
def interview_mode(frame):
    h, w = frame.shape[:2]
    nw, nh = int(w/1.15), int(h/1.15)
    x1, y1 = (w-nw)//2, (h-nh)//2
    zoomed = cv2.resize(frame[y1:y1+nh, x1:x1+nw], (w, h))
    r = zoomed.astype(np.float32)
    r[:,:,2] *= 1.10; r[:,:,1] *= 1.04; r[:,:,0] *= 0.90
    return cv2.bilateralFilter(_to_uint8(r), d=9, sigmaColor=75, sigmaSpace=75)

# 37. Screen Glare Reduction
def screen_glare_reduction(frame):
    r = frame.astype(np.float32)
    dark = r * 0.5
    lum = 0.299*r[:,:,2] + 0.587*r[:,:,1] + 0.114*r[:,:,0]
    glare = cv2.GaussianBlur((lum > 200).astype(np.float32), (15, 15), 0)[:,:,np.newaxis]
    return _to_uint8(r * (1 - 0.6*glare) + dark * 0.6*glare)

# 38. Noise Gate
class NoiseGate:
    def __init__(self):
        self._frozen = None
        self._prev_gray = None
    def __call__(self, frame):
        gray = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5,5), 0)
        if self._prev_gray is None:
            self._prev_gray = gray
            self._frozen = frame.copy()
            return frame
        diff = cv2.absdiff(self._prev_gray, gray)
        _, thresh = cv2.threshold(diff, 8, 255, cv2.THRESH_BINARY)
        self._prev_gray = gray
        if np.count_nonzero(thresh) > 500:
            self._frozen = frame.copy()
        return self._frozen if self._frozen is not None else frame

# 39. Auto Rotate
def auto_rotate(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    n_up = len(_detect_faces(gray))
    rotated = cv2.rotate(frame, cv2.ROTATE_180)
    n_down = len(_detect_faces(cv2.rotate(gray, cv2.ROTATE_180)))
    return rotated if n_down > n_up else frame

# 40. Timestamp Overlay
def timestamp_overlay(frame):
    result = frame.copy()
    ts = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
    cv2.putText(result, ts, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0,0,0), 3, cv2.LINE_AA)
    cv2.putText(result, ts, (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (255,255,255), 1, cv2.LINE_AA)
    return result

# 41. FPS Counter
class FPSCounter:
    def __init__(self):
        self._times = []
    def __call__(self, frame):
        now = time.monotonic()
        self._times.append(now)
        if len(self._times) > 30:
            self._times.pop(0)
        result = frame.copy()
        if len(self._times) >= 2:
            fps = (len(self._times)-1) / (self._times[-1] - self._times[0])
            text = f"FPS: {fps:.1f}"
            h, w = result.shape[:2]
            (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.75, 1)
            x = w - tw - 14
            cv2.putText(result, text, (x, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0,0,0), 3, cv2.LINE_AA)
            cv2.putText(result, text, (x, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0,255,0), 1, cv2.LINE_AA)
        return result

# 42. Resolution Scaler (pixelated)
def resolution_scaler(frame):
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (max(1,w//4), max(1,h//4)), interpolation=cv2.INTER_NEAREST)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

# 43. Letterbox to Pillarbox
def letterbox_to_pillarbox(frame):
    h, w = frame.shape[:2]
    target = 9/16
    if w/h <= target:
        return frame
    new_w = int(h * target)
    x1 = (w - new_w) // 2
    cropped = frame[:, x1:x1+new_w]
    pad_l = (w - new_w) // 2
    pad_r = w - new_w - pad_l
    return cv2.copyMakeBorder(cropped, 0, 0, pad_l, pad_r, cv2.BORDER_CONSTANT, value=(0,0,0))

# 44. Night Vision
def night_vision(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    enhanced = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8)).apply(gray)
    result = np.zeros_like(frame)
    result[:,:,1] = enhanced
    result[::2,:,1] = (result[::2,:,1].astype(np.uint16) * 85 // 100).astype(np.uint8)
    return result

# 45. Depth-of-Field
def depth_of_field(frame):
    h, w = frame.shape[:2]
    r = int(get_param("Depth of Field", "radius", 15)) * 2 + 1  # force odd
    blurred = cv2.GaussianBlur(frame, (r, r), 0)
    mask = np.zeros((h, w), dtype=np.float32)
    cv2.ellipse(mask, (w//2, h//2), (int(w*0.28), int(h*0.35)), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (71, 71), 0)[:,:,np.newaxis]
    return _to_uint8(frame.astype(np.float32)*mask + blurred.astype(np.float32)*(1-mask))

# 46. Border / Frame Overlay
def border_overlay(frame):
    result = frame.copy()
    h, w = result.shape[:2]
    t = 12
    cv2.rectangle(result, (t, t), (w-t, h-t), (200, 200, 200), t)
    return result

# 47. Watermark Overlay
def watermark_overlay(frame):
    result = frame.copy()
    h, w = result.shape[:2]
    scale = w / 1920.0 * 1.2
    thick = max(1, int(scale * 1.5))
    (tw, th), bl = cv2.getTextSize("NokiCam", cv2.FONT_HERSHEY_DUPLEX, scale, thick)
    overlay = result.copy()
    cv2.putText(overlay, "NokiCam", (w-tw-16, h-bl-12), cv2.FONT_HERSHEY_DUPLEX,
                scale, (255,255,255), thick, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.25, result, 0.75, 0, result)
    return result

# 48. Flip to Portrait
def flip_to_portrait(frame):
    h, w = frame.shape[:2]
    rotated = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
    rh, rw = rotated.shape[:2]
    scale = min(w/rw, h/rh)
    nw, nh = int(rw*scale), int(rh*scale)
    resized = cv2.resize(rotated, (nw, nh))
    canvas = np.zeros((h, w, 3), dtype=np.uint8)
    canvas[(h-nh)//2:(h-nh)//2+nh, (w-nw)//2:(w-nw)//2+nw] = resized
    return canvas

# 49. Cinematic Teal & Orange
def cinematic_teal_orange(frame):
    r = frame.astype(np.float32)
    lum = (0.299*r[:,:,2] + 0.587*r[:,:,1] + 0.114*r[:,:,0])
    sw = np.clip(1.0 - lum/255, 0, 1)[:,:,np.newaxis]
    hw = np.clip(lum/255, 0, 1)[:,:,np.newaxis]
    r[:,:,2] *= (1 - 0.3*sw[:,:,0])
    r[:,:,0] *= (1 + 0.25*sw[:,:,0])
    r[:,:,2] += 25*hw[:,:,0]
    r[:,:,1] += 10*hw[:,:,0]
    r[:,:,0] -= 20*hw[:,:,0]
    graded = np.clip(r, 0, 255).astype(np.uint8)
    return cv2.addWeighted(graded, 0.6, frame, 0.4, 0)

# 50. Sharpness + Clarity Boost
def sharpness_clarity_boost(frame):
    sharp = edge_sharpening(frame)
    lab = cv2.cvtColor(sharp, cv2.COLOR_BGR2LAB)
    lab[:,:,0] = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(6,6)).apply(lab[:,:,0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


# ===========================================================================
# FUNNY FILTERS (51-100)
# ===========================================================================

# 51. Super Fisheye
def super_fisheye(frame):
    h, w = frame.shape[:2]
    cx, cy = w/2.0, h/2.0
    fx = fy = max(w,h) * 0.8
    K = np.array([[fx,0,cx],[0,fy,cy],[0,0,1]], dtype=np.float64)
    dist_val = get_param("Super Fisheye", "dist", 0.85)
    dist = np.array([-dist_val, dist_val*0.53, 0.0, 0.0, -dist_val*0.18], dtype=np.float64)
    m1, m2 = cv2.initUndistortRectifyMap(K, dist, None, K, (w,h), cv2.CV_32FC1)
    return cv2.remap(frame, m1, m2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

# 52. Funhouse Mirror
def funhouse_mirror(frame):
    h, w = frame.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    xs_shifted = xs + w*0.08 * np.sin(2*np.pi*3.0/h * ys)
    return cv2.remap(frame, xs_shifted, ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

# 53. Melting Face
def melting_face(frame):
    h, w = frame.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    t = (ys / h)**2
    wave = np.sin(xs * 2*np.pi / (w/4.0)) * 8.0
    ys_shifted = ys - h*0.18*t + wave*t
    return cv2.remap(frame, xs, ys_shifted, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

# 54. Bobblehead
def bobblehead(frame):
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray)
    if len(faces) == 0:
        return frame
    out = frame.copy()
    for (fx, fy, fw, fh) in faces:
        cx, cy = fx+fw//2, fy+fh//2
        nw, nh = int(fw*1.7), int(fh*1.7)
        x1, y1 = max(0, cx-nw//2), max(0, cy-nh//2)
        x2, y2 = min(w, x1+nw), min(h, y1+nh)
        tw, th = x2-x1, y2-y1
        if tw < 2 or th < 2: continue
        out[y1:y2, x1:x2] = cv2.resize(frame[fy:fy+fh, fx:fx+fw], (tw, th))
    return out

# 55. Tiny Planet
def tiny_planet(frame):
    h, w = frame.shape[:2]
    side = min(h, w)
    sq = cv2.resize(frame, (side, side))
    flipped = cv2.flip(sq, 0)
    ys, xs = np.mgrid[0:side, 0:side].astype(np.float32)
    cx = cy = side/2.0
    dx, dy = xs-cx, ys-cy
    r = np.sqrt(dx**2+dy**2)/(side/2.0)
    theta = np.arctan2(dy, dx)
    src_x = ((theta/(2*np.pi)) % 1.0) * side
    src_y = np.clip(r*side, 0, side-1)
    result = cv2.remap(flipped, src_x.astype(np.float32), src_y.astype(np.float32),
                       cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
    return cv2.resize(result, (w, h))

# 56. Kaleidoscope
def kaleidoscope(frame):
    h, w = frame.shape[:2]
    hh, hw = h//2, w//2
    tl = frame[0:hh, 0:hw]
    top = np.concatenate([tl, cv2.flip(tl, 1)], axis=1)
    bottom = np.concatenate([cv2.flip(tl, 0), cv2.flip(tl, -1)], axis=1)
    return cv2.resize(np.concatenate([top, bottom], axis=0), (w, h))

# 57. Zoom Punch
class ZoomPunch:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        pulse = 0.5 + 0.45*abs(math.sin(time.monotonic()*3.0))
        cw, ch = max(20, int(w*pulse)), max(20, int(h*pulse))
        x1, y1 = (w-cw)//2, (h-ch)//2
        return cv2.resize(frame[y1:y1+ch, x1:x1+cw], (w, h))

# 58. Earthquake Shake
class EarthquakeShake:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        dx = int(np.random.uniform(-18, 18))
        dy = int(np.random.uniform(-18, 18))
        M = np.float32([[1,0,dx],[0,1,dy]])
        return cv2.warpAffine(frame, M, (w, h), borderMode=cv2.BORDER_REFLECT)

# 59. Static TV Glitch
class StaticTVGlitch:
    def __call__(self, frame):
        out = frame.copy()
        h, w = out.shape[:2]
        for _ in range(np.random.randint(6, 20)):
            y = np.random.randint(0, h)
            t = np.random.randint(1, 5)
            y2 = min(h, y+t)
            shift = np.random.randint(-40, 40)
            out[y:y2,:,:] = np.roll(frame[y:y2,:,:], shift, axis=1)
        if np.random.rand() < 0.4:
            ch = np.random.randint(0, 3)
            out[:,:,ch] = np.roll(out[:,:,ch], np.random.randint(-15, 15), axis=1)
        return out

# 60. VHS Rewind
class VHSRewind:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        out = frame.astype(np.float32)
        scanline = np.zeros((h, w, 1), dtype=np.float32)
        scanline[::2,:,:] = 0.55
        out = out * (1.0 - scanline*0.4)
        out_b = out.astype(np.uint8)
        b, g, r = cv2.split(out_b)
        r = np.roll(r, 5, axis=1)
        b = np.roll(b, -5, axis=1)
        result = cv2.merge([b, g, r])
        noise = np.random.randint(-12, 12, (h, w, 1), dtype=np.int16)
        return np.clip(result.astype(np.int16)+noise, 0, 255).astype(np.uint8)

# 61. Deep Fry
def deep_fry(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] = np.clip(hsv[:,:,1]*3.5, 0, 255)
    hsv[:,:,2] = np.clip(hsv[:,:,2]*1.4, 0, 255)
    saturated = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    kernel = np.array([[-1,-1,-1],[-1,11,-1],[-1,-1,-1]], dtype=np.float32)
    sharpened = cv2.filter2D(saturated, -1, kernel)
    noise = np.random.randint(-30, 30, sharpened.shape, dtype=np.int16)
    return np.clip(sharpened.astype(np.int16)+noise, 0, 255).astype(np.uint8)

# 62. Minecraft Pixelate
def minecraft_pixelate(frame):
    h, w = frame.shape[:2]
    block = max(2, int(get_param("Minecraft Pixelate", "block", 16)))
    small = cv2.resize(frame, (max(1, w//block), max(1, h//block)), interpolation=cv2.INTER_LINEAR)
    return cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)

# 63. Thermal Imaging
def thermal_imaging(frame):
    return cv2.applyColorMap(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLORMAP_JET)

# 64. Predator Cloak
def predator_cloak(frame):
    edges = cv2.Canny(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 80, 180)
    edges_d = cv2.dilate(edges, np.ones((3,3), np.uint8), iterations=2)
    glow = np.zeros_like(frame)
    glow[:,:,1] = edges_d
    glow[:,:,2] = (edges_d*0.5).astype(np.uint8)
    return cv2.addWeighted(frame, 0.25, glow, 0.9, 0)

# 65. Matrix Rain
class MatrixRain:
    def __init__(self):
        self._cols = None
        self._drops = None
        self._last = 0.0
        self._chars = list("0123456789ABCDEFZ")
    def __call__(self, frame):
        h, w = frame.shape[:2]
        col_w = 14
        num = w // col_w
        if self._cols != num:
            self._cols = num
            self._drops = np.random.randint(0, h//14, size=num).tolist()
        overlay = frame.copy()
        now = time.monotonic()
        if now - self._last > 0.07:
            self._last = now
            for i in range(self._cols):
                ch = self._chars[np.random.randint(0, len(self._chars))]
                x = i * col_w
                y = self._drops[i] * col_w
                cv2.putText(overlay, ch, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0,255,70), 1, cv2.LINE_AA)
                if y > h and np.random.rand() > 0.975:
                    self._drops[i] = 0
                else:
                    self._drops[i] += 1
        return cv2.addWeighted(frame, 0.55, overlay, 0.75, 0)

# 66. Googly Eyes
def googly_eyes(frame):
    out = frame.copy()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray)
    for (fx, fy, fw, fh) in faces:
        eyes = _eye_cascade.detectMultiScale(gray[fy:fy+fh, fx:fx+fw], 1.1, 3, minSize=(20,20))
        for (ex, ey, ew, eh) in eyes:
            cx, cy = fx+ex+ew//2, fy+ey+eh//2
            r = max(ew, eh)//2 + 6
            cv2.circle(out, (cx, cy), r, (255,255,255), -1)
            cv2.circle(out, (cx, cy), r, (0,0,0), 2)
            pr = max(4, r//3)
            ox = np.random.randint(-r//4, r//4)
            oy = np.random.randint(-r//4, r//4)
            cv2.circle(out, (cx+ox, cy+oy), pr, (0,0,0), -1)
            cv2.circle(out, (cx+ox-2, cy+oy-2), max(1, pr//3), (255,255,255), -1)
    return out

# 67. Spinning Vortex
class SpinningVortex:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        strength = 2.5 * math.sin(time.monotonic()*1.2)
        cx, cy = w/2.0, h/2.0
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        dx, dy = xs-cx, ys-cy
        r = np.sqrt(dx**2+dy**2)
        max_r = math.sqrt(cx**2+cy**2)
        angle = strength*(1.0 - np.clip(r/max_r, 0, 1))
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        return cv2.remap(frame, (cx+cos_a*dx-sin_a*dy).astype(np.float32),
                         (cy+sin_a*dx+cos_a*dy).astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

# 68. Fisheye Reverse (Pincushion)
def fisheye_reverse(frame):
    h, w = frame.shape[:2]
    fx = fy = max(w,h)*0.8
    K = np.array([[fx,0,w/2.0],[0,fy,h/2.0],[0,0,1]], dtype=np.float64)
    dist = np.array([0.45, -0.15, 0.0, 0.0, 0.05], dtype=np.float64)
    m1, m2 = cv2.initUndistortRectifyMap(K, dist, None, K, (w,h), cv2.CV_32FC1)
    return cv2.remap(frame, m1, m2, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

# 69. Stretch Horizontal
def stretch_horizontal(frame):
    h, w = frame.shape[:2]
    nw = int(w*2.2)
    stretched = cv2.resize(frame, (nw, h))
    x = (nw-w)//2
    return stretched[:, x:x+w]

# 70. Stretch Vertical
def stretch_vertical(frame):
    h, w = frame.shape[:2]
    nh = int(h*2.2)
    stretched = cv2.resize(frame, (w, nh))
    y = (nh-h)//2
    return stretched[y:y+h, :]

# 71. Swirl Center
def swirl_center_warp(frame):
    h, w = frame.shape[:2]
    cx, cy = w/2.0, h/2.0
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = xs-cx, ys-cy
    r = np.sqrt(dx**2+dy**2)
    max_r = math.sqrt(cx**2+cy**2)
    angle = 3.0*(1.0-np.clip(r/max_r, 0, 1))
    cos_a, sin_a = np.cos(angle).astype(np.float32), np.sin(angle).astype(np.float32)
    return cv2.remap(frame, cx+cos_a*dx-sin_a*dy, cy+sin_a*dx+cos_a*dy,
                     cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

# 72. Underwater Ripple
class UnderwaterRipple:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        t = time.monotonic()
        amp = get_param("Underwater Ripple", "amp", 8.0)
        ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
        dx = amp*np.sin(2*np.pi/(h/4.0)*ys + t*2.5)
        dy = amp*np.sin(2*np.pi/(w/5.0)*xs + t*2.0)
        return cv2.remap(frame, (xs+dx).astype(np.float32), (ys+dy).astype(np.float32),
                         cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

# 73. Shatter Glass
class ShatterGlass:
    def __init__(self):
        self._lines = None
    def __call__(self, frame):
        h, w = frame.shape[:2]
        if self._lines is None:
            self._lines = []
            for _ in range(3):
                cx, cy = np.random.randint(w//4, 3*w//4), np.random.randint(h//4, 3*h//4)
                for _ in range(np.random.randint(5, 10)):
                    angle = np.random.uniform(0, 2*np.pi)
                    length = np.random.randint(40, max(w,h)//2)
                    self._lines.append(((cx, cy), (int(cx+length*math.cos(angle)), int(cy+length*math.sin(angle)))))
        out = frame.copy()
        for p1, p2 in self._lines:
            cv2.line(out, p1, p2, (200,220,255), 1, cv2.LINE_AA)
            mid = ((p1[0]+p2[0])//2, (p1[1]+p2[1])//2)
            cv2.line(out, p1, mid, (255,255,255), 1, cv2.LINE_AA)
        return out

# 74. Drunk Sway
class DrunkSway:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        amount = get_param("Drunk Sway", "amount", 8.0)
        angle = amount * math.sin(time.monotonic()*0.9)
        M = cv2.getRotationMatrix2D((w/2, h/2), angle, 1.0)
        return cv2.warpAffine(frame, M, (w, h), borderMode=cv2.BORDER_REFLECT)

# 75. Comic Book
def comic_book(frame):
    h, w = frame.shape[:2]
    small = cv2.resize(frame, (w//2, h//2))
    quantized = cv2.resize((small//64)*64+32, (w, h), interpolation=cv2.INTER_NEAREST)
    edges = cv2.dilate(cv2.Canny(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 80, 160), np.ones((2,2), np.uint8))
    out = quantized.copy()
    out[edges > 0] = [0, 0, 0]
    return out

# 76. Oil Painting
def oil_painting(frame):
    # edgePreservingFilter with RECURS_FILTER (flags=2) is OpenCL-accelerated
    # and purpose-built for this effect — single pass is sufficient
    return cv2.edgePreservingFilter(frame, flags=2, sigma_s=50, sigma_r=0.45)

# 77. Watercolor Bleed
def watercolor_bleed(frame):
    # cv2.stylization is purpose-built, OpenCL-accelerated, and faster than
    # the bilateral+median+Canny approach
    return cv2.stylization(frame, sigma_s=45, sigma_r=0.35)

# 78. Pencil Sketch
def pencil_sketch(frame):
    gray, _ = cv2.pencilSketch(frame, sigma_s=60, sigma_r=0.07, shade_factor=0.05)
    return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

# 79. Neon Glow Edges
def neon_glow_edges(frame):
    edges = cv2.Canny(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 60, 140)
    glow = cv2.GaussianBlur(cv2.dilate(edges, np.ones((3,3), np.uint8), iterations=2), (15, 15), 0)
    color = np.zeros_like(frame)
    color[:,:,0] = (glow*0.3).astype(np.uint8)
    color[:,:,1] = glow
    color[:,:,2] = (glow*0.8).astype(np.uint8)
    return cv2.add((frame*0.3).astype(np.uint8), color)

# 80. Infrared Film
def infrared_film(frame):
    b, g, r = cv2.split(frame)
    g_b = np.clip(g.astype(np.int32)+40, 0, 255).astype(np.uint8)
    out = cv2.merge([r, g_b, b])
    hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] *= 0.5
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

# 81. Old Film Projector
class OldFilmProjector:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        sepia = np.clip(cv2.transform(frame, _SEPIA_KERNEL), 0, 255).astype(np.uint8)
        flicker = 1.0 + 0.15*np.random.randn()
        sepia = np.clip(sepia.astype(np.float32)*flicker, 0, 255).astype(np.uint8)
        grain = np.random.randint(-25, 25, (h, w, 3), dtype=np.int16)
        sepia = np.clip(sepia.astype(np.int16)+grain, 0, 255).astype(np.uint8)
        for _ in range(np.random.randint(0, 3)):
            x = np.random.randint(0, w)
            cv2.line(sepia, (x, 0), (x, h), (200,200,200), 1)
        return sepia

# 82. Mirror Ball
def mirror_ball(frame):
    h, w = frame.shape[:2]
    cx, cy = w/2.0, h/2.0
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = (xs-cx)/cx, (ys-cy)/cy
    r2 = dx**2+dy**2
    mask = r2 < 1.0
    dz = np.sqrt(np.maximum(0, 1-np.where(mask, r2, 1)))
    rx = dx-2*dz*dx; ry = dy-2*dz*dy
    src_x = np.clip((rx*0.5+0.5)*w, 0, w-1).astype(np.float32)
    src_y = np.clip((ry*0.5+0.5)*h, 0, h-1).astype(np.float32)
    ball = cv2.remap(frame, src_x, src_y, cv2.INTER_LINEAR)
    out = frame.copy()
    out[mask] = ball[mask]
    return out

# 83. Face Zoom Lock
def face_zoom_lock(frame):
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray)
    if len(faces) == 0:
        return cv2.GaussianBlur(frame, (31, 31), 0)
    fx, fy, fw, fh = max(faces, key=lambda f: f[2]*f[3])
    pad = int(max(fw, fh)*0.5)
    x1, y1 = max(0, fx-pad), max(0, fy-pad)
    x2, y2 = min(w, fx+fw+pad), min(h, fy+fh+pad)
    blurred = cv2.GaussianBlur(frame, (31, 31), 0)
    out = blurred.copy()
    out[y1:y2, x1:x2] = frame[y1:y2, x1:x2]
    return out

# 84. Confetti Explosion
class ConfettiExplosion:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        out = frame.copy()
        for _ in range(80):
            x, y = np.random.randint(0, w), np.random.randint(0, h)
            rw, rh = np.random.randint(4, 18), np.random.randint(4, 18)
            color = tuple(int(c) for c in np.random.randint(0, 255, 3))
            cv2.rectangle(out, (x, y), (x+rw, y+rh), color, -1)
        return cv2.addWeighted(frame, 0.6, out, 0.7, 0)

# 85. Eyes Wide
def eyes_wide(frame):
    out = frame.copy()
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray)
    for (fx, fy, fw, fh) in faces:
        eyes = _eye_cascade.detectMultiScale(gray[fy:fy+fh, fx:fx+fw], 1.1, 3, minSize=(20,20))
        for (ex, ey, ew, eh) in eyes:
            ecx, ecy = fx+ex+ew//2, fy+ey+eh//2
            r = max(ew, eh)
            bx1, by1 = max(0, ecx-r), max(0, ecy-r)
            bx2, by2 = min(w, ecx+r), min(h, ecy+r)
            bw, bh = bx2-bx1, by2-by1
            if bw < 4 or bh < 4: continue
            ys_b, xs_b = np.mgrid[0:bh, 0:bw].astype(np.float32)
            cxb, cyb = bw/2.0, bh/2.0
            ddx, ddy = (xs_b-cxb)/cxb, (ys_b-cyb)/cyb
            rr = np.sqrt(ddx**2+ddy**2)
            bulge = np.where(rr < 1.0, rr**0.45, rr)
            factor = np.where(rr > 1e-5, bulge/(rr+1e-5), 1.0)
            sx = np.clip(cxb+ddx*factor*cxb, 0, bw-1).astype(np.float32)
            sy = np.clip(cyb+ddy*factor*cyb, 0, bh-1).astype(np.float32)
            out[by1:by2, bx1:bx2] = cv2.remap(frame[by1:by2, bx1:bx2], sx, sy, cv2.INTER_LINEAR)
    return out

# 86. Shrinking Head
class ShrinkingHead:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = _detect_faces(gray)
        if len(faces) == 0: return frame
        scale = 0.7 + 0.3*math.sin(time.monotonic()*1.5)
        out = frame.copy()
        for (fx, fy, fw, fh) in faces:
            cx, cy = fx+fw//2, fy+fh//2
            nw, nh = max(4, int(fw*scale)), max(4, int(fh*scale))
            face = cv2.resize(frame[fy:fy+fh, fx:fx+fw], (nw, nh))
            x1, y1 = max(0, cx-nw//2), max(0, cy-nh//2)
            x2, y2 = min(w, x1+nw), min(h, y1+nh)
            aw, ah = x2-x1, y2-y1
            if aw < 2 or ah < 2: continue
            out[y1:y2, x1:x2] = cv2.resize(face, (aw, ah))
        return out

# 87. Pop Art Warhol
def pop_art_warhol(frame):
    h, w = frame.shape[:2]
    tile = cv2.resize(frame, (w//2, h//2))
    tints = [(1.0,0.3,0.3),(0.3,1.0,0.3),(0.3,0.3,1.0),(1.0,0.9,0.2)]
    panels = []
    for tb, tg, tr in tints:
        p = tile.astype(np.float32)
        p[:,:,0] = np.clip(p[:,:,0]*tb, 0, 255)
        p[:,:,1] = np.clip(p[:,:,1]*tg, 0, 255)
        p[:,:,2] = np.clip(p[:,:,2]*tr, 0, 255)
        panels.append(p.astype(np.uint8))
    top = np.concatenate([panels[0], panels[1]], axis=1)
    bottom = np.concatenate([panels[2], panels[3]], axis=1)
    return cv2.resize(np.concatenate([top, bottom], axis=0), (w, h))

# 88. Glitch Slice
class GlitchSlice:
    def __call__(self, frame):
        out = frame.copy()
        h, w = frame.shape[:2]
        for _ in range(np.random.randint(4, 14)):
            y = np.random.randint(0, h-1)
            t = np.random.randint(1, 12)
            y2 = min(h, y+t)
            out[y:y2,:,:] = np.roll(frame[y:y2,:,:], np.random.randint(-50, 50), axis=1)
        return out

# 89. Hologram
class Hologram:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        t = time.monotonic()
        blue = frame.astype(np.float32)
        blue[:,:,0] = np.clip(blue[:,:,0]*1.5, 0, 255)
        blue[:,:,1] = np.clip(blue[:,:,1]*0.6, 0, 255)
        blue[:,:,2] = np.clip(blue[:,:,2]*0.4, 0, 255)
        blue = blue.astype(np.uint8)
        scanline = np.ones((h, w, 1), dtype=np.float32)
        scanline[int(t*60)%2::2,:,:] = 0.55
        blue = (blue.astype(np.float32)*scanline).astype(np.uint8)
        flicker = 0.85 + 0.15*math.sin(t*17.3)
        blue = np.clip(blue.astype(np.float32)*flicker, 0, 255).astype(np.uint8)
        edges = cv2.GaussianBlur(cv2.Canny(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 80, 160), (9,9), 0)
        glow = np.zeros_like(frame)
        glow[:,:,0] = edges
        return cv2.add(blue, glow)

# 90. Rotating Cube
class RotatingCube:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        t = time.monotonic()
        angle = (t*40) % 360
        skew_x = w*0.25*math.sin(math.radians(angle))
        skew_y = h*0.15*math.sin(math.radians(angle*0.7))
        src = np.float32([[0,0],[w,0],[w,h],[0,h]])
        dst = np.float32([
            [w*0.1+skew_x, h*0.05+skew_y],
            [w*0.9+skew_x, h*0.05-skew_y],
            [w*0.9-skew_x, h*0.95+skew_y],
            [w*0.1-skew_x, h*0.95-skew_y],
        ])
        M = cv2.getPerspectiveTransform(src, dst)
        return cv2.warpPerspective(frame, M, (w, h), borderMode=cv2.BORDER_REFLECT)

# 91. Mirror Army
def mirror_army(frame):
    h, w = frame.shape[:2]
    cols, rows = 4, 3
    tw, th = w//cols, h//rows
    tile = cv2.resize(frame, (tw, th))
    canvas = np.zeros_like(frame)
    for r in range(rows):
        for c in range(cols):
            t = tile.copy()
            if c % 2 == 1: t = cv2.flip(t, 1)
            if r % 2 == 1: t = cv2.flip(t, 0)
            canvas[r*th:r*th+th, c*tw:c*tw+tw] = t
    return canvas

# 92. Squeeze Center
def squeeze_center(frame):
    h, w = frame.shape[:2]
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    cx = w/2.0
    norm = (xs/w)*np.pi
    src_x = cx + (xs-cx)*(0.35+0.65*np.abs(np.sin(norm)))
    return cv2.remap(frame, src_x.astype(np.float32), ys, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

# 93. Big Nose Warp
def big_nose_warp(frame):
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray)
    if len(faces) == 0: return frame
    out = frame.copy()
    for (fx, fy, fw, fh) in faces:
        ncx, ncy = fx+fw//2, fy+int(fh*0.62)
        r = int(fw*0.28)
        bx1, by1 = max(0, ncx-r), max(0, ncy-r)
        bx2, by2 = min(w, ncx+r), min(h, ncy+r)
        bw, bh = bx2-bx1, by2-by1
        if bw < 4 or bh < 4: continue
        ys_b, xs_b = np.mgrid[0:bh, 0:bw].astype(np.float32)
        cxb, cyb = bw/2.0, bh/2.0
        ddx, ddy = (xs_b-cxb)/(cxb+1e-5), (ys_b-cyb)/(cyb+1e-5)
        rr = np.sqrt(ddx**2+ddy**2)
        bulge = np.where(rr < 1.0, rr**0.35, rr)
        factor = np.where(rr > 1e-5, bulge/(rr+1e-5), 1.0)
        sx = np.clip(cxb+ddx*factor*cxb, 0, bw-1).astype(np.float32)
        sy = np.clip(cyb+ddy*factor*cyb, 0, bh-1).astype(np.float32)
        out[by1:by2, bx1:bx2] = cv2.remap(frame[by1:by2, bx1:bx2], sx, sy, cv2.INTER_LINEAR)
    return out

# 94. Emoji Face Replace
def emoji_face_replace(frame):
    out = frame.copy()
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = _detect_faces(gray)
    for (fx, fy, fw, fh) in faces:
        cx, cy = fx+fw//2, fy+fh//2
        r = max(fw, fh)//2
        cv2.circle(out, (cx, cy), r, (0,220,255), -1)
        cv2.circle(out, (cx, cy), r, (0,160,200), 3)
        er = max(4, r//6)
        for off in [-r//3, r//3]:
            cv2.circle(out, (cx+off, cy-r//5), er, (20,20,20), -1)
        cv2.ellipse(out, (cx, cy+r//8), (r//2, r//3), 0, 0, 180, (20,20,20), 3)
    return out

# 95. Cartoon Cel Shading
def cartoon_cel_shading(frame):
    n = 6
    quantized = (frame//(256//n))*(256//n)
    edges = cv2.dilate(cv2.Canny(cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (5,5), 0), 60, 140), np.ones((2,2), np.uint8))
    out = quantized.copy()
    out[edges > 0] = [0, 0, 0]
    return out

# 96. Dissolve Static
class DissolveStatic:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        alpha = (math.sin(time.monotonic()*1.5)+1.0)/2.0
        static = np.random.randint(0, 256, (h, w, 3), dtype=np.uint8)
        return cv2.addWeighted(frame, 1.0-alpha*0.8, static, alpha*0.8, 0)

# 97. Infinite Zoom Tunnel
class InfiniteZoomTunnel:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        t = time.monotonic()
        zoom = 1.0 + 0.4*((t*0.8) % 1.0)
        cw, ch = max(10, int(w/zoom)), max(10, int(h/zoom))
        x1, y1 = max(0, (w-cw)//2), max(0, (h-ch)//2)
        x2, y2 = min(w, x1+cw), min(h, y1+ch)
        inner = cv2.resize(frame[y1:y2, x1:x2], (w, h))
        mask = np.zeros((h, w), dtype=np.float32)
        mask[h//5:4*h//5, w//5:4*w//5] = 1.0
        mask = cv2.GaussianBlur(mask, (61, 61), 0)[:,:,np.newaxis]
        return (frame.astype(np.float32)*(1-mask) + inner.astype(np.float32)*mask).astype(np.uint8)

# 98. Wind Blow
def wind_blow(frame):
    length = max(3, int(get_param("Wind Blow", "length", 35)))
    kernel = np.zeros((1, length), dtype=np.float32)
    kernel[0,:] = 1.0/length
    return cv2.filter2D(frame, -1, kernel)

# 99. Dollar Store Beauty
def dollar_store_beauty(frame):
    # edgePreservingFilter for the smoothing + UMat bloom for the blur
    smooth = cv2.edgePreservingFilter(frame, flags=1, sigma_s=40, sigma_r=0.5)
    bloom = cv2.GaussianBlur(cv2.UMat(smooth), (25, 25), 0).get()
    out = cv2.addWeighted(smooth, 0.65, bloom, 0.55, 10)
    hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:,:,1] *= 0.7
    hsv[:,:,2] = np.clip(hsv[:,:,2]*1.15, 0, 255)
    return cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

# 100. Surveillance Cam
class SurveillanceCam:
    def __call__(self, frame):
        h, w = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        noise = np.random.randint(-30, 30, (h, w), dtype=np.int16)
        gray = np.clip(gray.astype(np.int16)+noise, 0, 255).astype(np.uint8)
        out = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        cv2.putText(out, datetime.now().strftime("%Y-%m-%d  %H:%M:%S"), (10, h-18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200,200,200), 1, cv2.LINE_AA)
        cv2.putText(out, "CAM-01", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1, cv2.LINE_AA)
        if int(time.monotonic()) % 2 == 0:
            cv2.circle(out, (w-24, 18), 8, (0,0,220), -1)
            cv2.putText(out, "REC", (w-70, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,0,220), 1, cv2.LINE_AA)
        return out


# ===========================================================================
# Registries — instantiate stateful filters, plain functions stay as-is
# ===========================================================================

USEFUL_FILTERS = {
    "Auto White Balance":       auto_white_balance,
    "Exposure Compensation":    exposure_compensation,
    "Noise Reduction":          noise_reduction,
    "Edge Sharpening":          edge_sharpening,
    "Soft Focus":               soft_focus,
    "Background Blur":          background_blur,
    "Chromatic Aberration Fix": chromatic_aberration_fix,
    "Vignette Removal":         vignette_removal,
    "Histogram Equalization":   histogram_equalization,
    "HDR Tone Mapping":         hdr_tone_mapping,
    "Color Temp Warm":          color_temperature_warm,
    "Color Temp Cool":          color_temperature_cool,
    "Saturation Boost":         saturation_boost,
    "Contrast Enhance":         contrast_enhance,
    "Shadow Lift":              shadow_lift,
    "Highlight Recovery":       highlight_recovery,
    "Chroma Key":               chroma_key,
    "Virtual Background":       virtual_background_replace,
    "Face Centering":           FaceCentering(),
    "Low Light Boost":          low_light_boost,
    "Stabilization":            Stabilization(),
    "Letterbox":                letterbox,
    "Mirror Horizontal":        mirror_horizontal,
    "Mirror Vertical":          mirror_vertical,
    "Auto Face Brightness":     AutoFaceBrightness(),
    "Grayscale":                grayscale,
    "Sepia Tone":               sepia_tone,
    "Red Eye Reduction":        red_eye_reduction,
    "Zoom Smooth":              ZoomSmooth(),
    "Colorblind Deuteranopia":  colorblind_deuteranopia,
    "Colorblind Protanopia":    colorblind_protanopia,
    "Colorblind Tritanopia":    colorblind_tritanopia,
    "High Contrast":            high_contrast_mode,
    "Blue Light Filter":        blue_light_filter,
    "Podcast Mode":             PodcastMode(),
    "Interview Mode":           interview_mode,
    "Glare Reduction":          screen_glare_reduction,
    "Noise Gate":               NoiseGate(),
    "Auto Rotate":              auto_rotate,
    "Timestamp":                timestamp_overlay,
    "FPS Counter":              FPSCounter(),
    "Resolution Scaler":        resolution_scaler,
    "Pillarbox Convert":        letterbox_to_pillarbox,
    "Night Vision":             night_vision,
    "Depth of Field":           depth_of_field,
    "Border Overlay":           border_overlay,
    "Watermark":                watermark_overlay,
    "Flip Portrait":            flip_to_portrait,
    "Cinematic Teal/Orange":    cinematic_teal_orange,
    "Sharpness + Clarity":      sharpness_clarity_boost,
}

FUNNY_FILTERS = {
    "Super Fisheye":            super_fisheye,
    "Funhouse Mirror":          funhouse_mirror,
    "Melting Face":             melting_face,
    "Bobblehead":               bobblehead,
    "Tiny Planet":              tiny_planet,
    "Kaleidoscope":             kaleidoscope,
    "Zoom Punch":               ZoomPunch(),
    "Earthquake Shake":         EarthquakeShake(),
    "Static TV Glitch":         StaticTVGlitch(),
    "VHS Rewind":               VHSRewind(),
    "Deep Fry":                 deep_fry,
    "Minecraft Pixelate":       minecraft_pixelate,
    "Thermal Imaging":          thermal_imaging,
    "Predator Cloak":           predator_cloak,
    "Matrix Rain":              MatrixRain(),
    "Googly Eyes":              googly_eyes,
    "Spinning Vortex":          SpinningVortex(),
    "Fisheye Reverse":          fisheye_reverse,
    "Stretch Horizontal":       stretch_horizontal,
    "Stretch Vertical":         stretch_vertical,
    "Swirl Center":             swirl_center_warp,
    "Underwater Ripple":        UnderwaterRipple(),
    "Shatter Glass":            ShatterGlass(),
    "Drunk Sway":               DrunkSway(),
    "Comic Book":               comic_book,
    "Oil Painting":             oil_painting,
    "Watercolor Bleed":         watercolor_bleed,
    "Pencil Sketch":            pencil_sketch,
    "Neon Glow Edges":          neon_glow_edges,
    "Infrared Film":            infrared_film,
    "Old Film":                 OldFilmProjector(),
    "Mirror Ball":              mirror_ball,
    "Face Zoom Lock":           face_zoom_lock,
    "Confetti Explosion":       ConfettiExplosion(),
    "Eyes Wide":                eyes_wide,
    "Shrinking Head":           ShrinkingHead(),
    "Pop Art Warhol":           pop_art_warhol,
    "Glitch Slice":             GlitchSlice(),
    "Hologram":                 Hologram(),
    "Rotating Cube":            RotatingCube(),
    "Mirror Army":              mirror_army,
    "Squeeze Center":           squeeze_center,
    "Big Nose Warp":            big_nose_warp,
    "Emoji Face Replace":       emoji_face_replace,
    "Cartoon Cel Shading":      cartoon_cel_shading,
    "Dissolve Static":          DissolveStatic(),
    "Infinite Zoom":            InfiniteZoomTunnel(),
    "Wind Blow":                wind_blow,
    "Dollar Store Beauty":      dollar_store_beauty,
    "Surveillance Cam":         SurveillanceCam(),
}

ALL_FILTERS = {**USEFUL_FILTERS, **FUNNY_FILTERS}
