"""
filter_pipeline.py — Active filter registry and sequential pipeline executor.

Two-tier performance strategy:
  1. HALF_RES: run at half resolution (4× fewer pixels), upscale back.
  2. SKIP_FRAME: run every 2nd frame, show cached result in between.
     Invisible for static artistic effects where image barely changes.
"""

import cv2
import numpy as np
from filters import ALL_FILTERS

# Run at half resolution — fast enough for blur/denoise
_HALF_RES_FILTERS = frozenset({
    "Soft Focus",
    "Depth of Field",
    "Background Blur",
    "Noise Reduction",
    "Dollar Store Beauty",
    "Pencil Sketch",
    "Cartoon Cel Shading",
    "Comic Book",
    "Neon Glow Edges",
    "Stabilization",
    "Underwater Ripple",
    "Spinning Vortex",
})

# Run every 2nd frame — heavy artistic filters where temporal caching is invisible
_SKIP_FRAME_FILTERS = frozenset({
    "Oil Painting",
    "Watercolor Bleed",
})


class FilterPipeline:
    """Manages a set of active filters and applies them in order each frame."""

    def __init__(self):
        self._active: list[str] = []
        self._skip_cache: dict[str, np.ndarray] = {}  # last output for skip-frame filters
        self._frame_idx: int = 0

    @property
    def active_filters(self) -> list[str]:
        return list(self._active)

    def toggle(self, name: str) -> bool:
        if name in self._active:
            self._active.remove(name)
            return False
        if name in ALL_FILTERS:
            self._active.append(name)
            return True
        return False

    def set_active(self, name: str, active: bool):
        if active and name not in self._active and name in ALL_FILTERS:
            self._active.append(name)
        elif not active and name in self._active:
            self._active.remove(name)
            self._skip_cache.pop(name, None)

    def clear(self):
        self._active.clear()
        self._skip_cache.clear()

    def process(self, frame: np.ndarray) -> np.ndarray:
        """Apply all active filters in order with adaptive resolution and frame-skipping."""
        self._frame_idx += 1
        h, w = frame.shape[:2]
        half_w, half_h = max(1, w // 2), max(1, h // 2)

        # Manage half-res state to batch consecutive half-res filters efficiently
        half_frame = None
        is_half = False

        for name in self._active:
            fn = ALL_FILTERS.get(name)
            if fn is None:
                continue

            # Skip-frame path: return cached result every other frame
            if name in _SKIP_FRAME_FILTERS:
                if is_half:
                    frame = cv2.resize(half_frame, (w, h), interpolation=cv2.INTER_LINEAR)
                    is_half = False
                if self._frame_idx % 2 == 0 and name in self._skip_cache:
                    frame = self._skip_cache[name]
                else:
                    try:
                        # Run at half-res for skip-frame filters too
                        small = cv2.resize(frame, (half_w, half_h), interpolation=cv2.INTER_AREA)
                        result_small = fn(small)
                        frame = cv2.resize(result_small, (w, h), interpolation=cv2.INTER_LINEAR)
                        self._skip_cache[name] = frame
                    except Exception:
                        pass
                continue

            # Half-res path
            if name in _HALF_RES_FILTERS and h > 240:
                if not is_half:
                    half_frame = cv2.resize(frame, (half_w, half_h), interpolation=cv2.INTER_AREA)
                    is_half = True
                try:
                    half_frame = fn(half_frame)
                except Exception:
                    pass
                continue

            # Full-res path — upscale if we were in half-res mode
            if is_half:
                frame = cv2.resize(half_frame, (w, h), interpolation=cv2.INTER_LINEAR)
                is_half = False
            try:
                frame = fn(frame)
            except Exception:
                pass

        # Final upscale if still in half-res mode
        if is_half and half_frame is not None:
            frame = cv2.resize(half_frame, (w, h), interpolation=cv2.INTER_LINEAR)

        return frame
