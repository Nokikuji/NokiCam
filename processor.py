import os
import urllib.request
import cv2
import numpy as np
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision
from PIL import Image as PILImage

# NOTE: Do not set cv2.ocl / cv2.setNumThreads here — gpu_detect in main.py
# configures these globally at startup. Module-level overrides would undo that.

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(SCRIPT_DIR, "selfie_segmenter.tflite")
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_segmenter/float16/latest/selfie_segmenter.tflite"


def _ensure_model():
    """Download the selfie segmenter model if not present."""
    if not os.path.exists(MODEL_PATH):
        print(f"Downloading segmentation model to {MODEL_PATH}...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("Download complete.")


def build_undistort_maps(frame_size, camera_matrix, dist_coeffs, zoom_factor=2.0):
    """
    Pre-compute remap LUTs for fisheye correction + zoom.
    Call once, reuse every frame for performance.
    """
    w, h = frame_size

    new_camera_matrix = camera_matrix.copy()
    new_camera_matrix[0, 0] *= zoom_factor  # fx
    new_camera_matrix[1, 1] *= zoom_factor  # fy
    new_camera_matrix[0, 2] = w / 2
    new_camera_matrix[1, 2] = h / 2

    map1, map2 = cv2.initUndistortRectifyMap(
        camera_matrix,
        dist_coeffs,
        None,
        new_camera_matrix,
        (w, h),
        cv2.CV_16SC2,
    )
    return map1, map2


def process_frame(frame, map1, map2):
    """Apply pre-computed remap."""
    return cv2.remap(frame, map1, map2, interpolation=cv2.INTER_LINEAR)


# ── Background segmentation ─────────────────────────────────────────────────

class BackgroundProcessor:
    """Handles person segmentation and background replacement."""

    # Background modes
    MODE_OFF = 0
    MODE_BLUR = 1
    MODE_IMAGE = 2
    MODE_GIF = 3

    def __init__(self):
        self._segmenter = None  # lazy init on first use
        self.mode = self.MODE_OFF
        self.blur_strength = 21  # must be odd
        self._bg_image = None      # pre-scaled BGR background image
        self._gif_frames = []      # list of pre-scaled BGR frames
        self._gif_index = 0
        self._gif_frame_skip = 2   # show each gif frame for N video frames
        self._gif_counter = 0
        self._target_size = None   # (w, h) to scale backgrounds to
        self.threshold = 0.6       # segmentation confidence threshold
        self.invert_mask = False   # False = replace background, True = replace person
        self._timestamp_ms = 0
        self._last_mask = None     # cached mask for frame-skip
        self._seg_frame_count = 0

    def _init_segmenter(self):
        """Initialize the MediaPipe image segmenter (Tasks API)."""
        _ensure_model()
        base_options = mp_tasks.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.ImageSegmenterOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            output_category_mask=True,
        )
        self._segmenter = vision.ImageSegmenter.create_from_options(options)

    def set_blur_strength(self, val):
        """Set blur kernel size (will be forced to odd)."""
        self.blur_strength = val | 1  # ensure odd

    def load_image(self, path, frame_w, frame_h):
        """Load a static background image, scaled to frame size."""
        try:
            img = cv2.imread(path)
            if img is None:
                return False
            self._bg_image = cv2.resize(img, (frame_w, frame_h))
            self._target_size = (frame_w, frame_h)
            return True
        except Exception:
            return False

    def load_gif(self, path, frame_w, frame_h):
        """Load an animated GIF, converting all frames to BGR and scaling."""
        try:
            pil_gif = PILImage.open(path)
            frames = []
            while True:
                rgba = pil_gif.convert("RGBA")
                arr = np.array(rgba)
                bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
                bgr = cv2.resize(bgr, (frame_w, frame_h))
                frames.append(bgr)
                try:
                    pil_gif.seek(pil_gif.tell() + 1)
                except EOFError:
                    break
            if not frames:
                return False
            self._gif_frames = frames
            self._gif_index = 0
            self._gif_counter = 0
            self._target_size = (frame_w, frame_h)
            return True
        except Exception:
            return False

    def process(self, frame_bgr):
        """
        Apply background effect to a BGR frame.
        Returns the composited BGR frame.
        """
        if self.mode == self.MODE_OFF:
            return frame_bgr

        # Lazy-init segmenter on first actual use
        if self._segmenter is None:
            self._init_segmenter()

        h, w = frame_bgr.shape[:2]

        # Run segmentation every other frame; reuse cached mask in between.
        # MediaPipe internally runs at ~256px, so full-res input gives no quality
        # benefit — only latency. Skipping alternating frames halves segmentation cost.
        self._seg_frame_count += 1
        run_seg = (
            self._seg_frame_count % 2 == 1
            or self._last_mask is None
            or self._last_mask.shape[:2] != (h, w)
        )

        if run_seg:
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            self._timestamp_ms += 33  # ~30fps
            result = self._segmenter.segment_for_video(mp_image, self._timestamp_ms)

            # category_mask: 0 = person, 255 = background
            cat_mask = result.category_mask.numpy_view()
            mask = (cat_mask == 0).astype(np.float32)

            if self.invert_mask:
                mask = 1.0 - mask

            # Resize mask if MediaPipe output differs from frame size
            if mask.shape[:2] != (h, w):
                mask = cv2.resize(mask, (w, h), interpolation=cv2.INTER_LINEAR)

            # Smooth edges
            mask = cv2.GaussianBlur(mask, (7, 7), 3)
            self._last_mask = mask
        else:
            mask = self._last_mask

        # Build background
        if self.mode == self.MODE_BLUR:
            bg = cv2.GaussianBlur(frame_bgr, (self.blur_strength, self.blur_strength), 0)

        elif self.mode == self.MODE_IMAGE:
            if self._bg_image is None:
                return frame_bgr
            bg = self._bg_image
            if bg.shape[:2] != (h, w):
                bg = cv2.resize(bg, (w, h))

        elif self.mode == self.MODE_GIF:
            if not self._gif_frames:
                return frame_bgr
            bg = self._gif_frames[self._gif_index]
            if bg.shape[:2] != (h, w):
                bg = cv2.resize(bg, (w, h))
            self._gif_counter += 1
            if self._gif_counter >= self._gif_frame_skip:
                self._gif_counter = 0
                self._gif_index = (self._gif_index + 1) % len(self._gif_frames)
        else:
            return frame_bgr

        # Composite using uint16 — avoids float32 allocations (2× less memory bandwidth).
        # alpha + (255 - alpha) = 255, so max value = 255*255 = 65025 < 65535 (safe).
        alpha = np.clip(mask * 255, 0, 255).astype(np.uint16)[:, :, np.newaxis]
        return (
            (frame_bgr.astype(np.uint16) * alpha
             + bg.astype(np.uint16) * (255 - alpha)) >> 8
        ).astype(np.uint8)
