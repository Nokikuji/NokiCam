import sys
import os
import json
import glob
import time
import threading
import cv2
import numpy as np
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QSlider, QComboBox, QPushButton, QFrame, QSizePolicy,
    QGraphicsOpacityEffect, QFileDialog, QDialog, QTabWidget,
    QScrollArea, QCheckBox,
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, pyqtSlot, QPropertyAnimation,
    QEasingCurve, QSize, QRect, pyqtProperty,
)
from PyQt5.QtGui import QImage, QPixmap, QFont, QPainter, QColor, QPen
from virtual_cam import VirtualCamera
from processor import build_undistort_maps, process_frame, BackgroundProcessor
from filter_pipeline import FilterPipeline
from filters import USEFUL_FILTERS, FUNNY_FILTERS, FILTER_PARAMS_SPEC, set_param
try:
    from gpu_detect import detect_gpu, configure_opencv
    _gpu_info = detect_gpu()
    configure_opencv(_gpu_info)
except Exception:
    cv2.ocl.setUseOpenCL(True)
    cv2.setNumThreads(0)
    cv2.setUseOptimized(True)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(SCRIPT_DIR, "settings.json")
AUTOSTART_DIR = os.path.expanduser("~/.config/autostart")
AUTOSTART_FILE = os.path.join(AUTOSTART_DIR, "nokicam.desktop")
LAUNCHER_SCRIPT = os.path.join(SCRIPT_DIR, "nokicam-launch.sh")


# ── Samsung One UI inspired dark theme ───────────────────────────────────────
DARK_STYLE = """
    QMainWindow {
        background-color: #121212;
    }
    QWidget {
        background-color: transparent;
        color: #e0e0e0;
        font-family: "Noto Sans", "Segoe UI", "SF Pro Display", sans-serif;
    }
    QWidget#centralWidget {
        background-color: #121212;
    }
    QWidget#panelCard {
        background-color: #1c1c1e;
        border-radius: 16px;
    }
    QLabel {
        color: #e0e0e0;
        background: transparent;
    }
    QLabel#preview {
        background-color: #000000;
        border-radius: 16px;
    }
    QLabel#sectionTitle {
        color: #6e9fff;
        font-size: 10px;
        font-weight: bold;
        letter-spacing: 2px;
        padding-top: 2px;
    }
    QLabel#valueLabel {
        color: #ffffff;
        font-size: 15px;
        font-weight: bold;
    }
    QLabel#statusOn {
        color: #4caf50;
        font-size: 11px;
    }
    QLabel#statusOff {
        color: #f44336;
        font-size: 11px;
    }
    QLabel#hint {
        color: #4a4a4a;
        font-size: 10px;
    }
    QLabel#fpsLabel {
        color: #4a4a4a;
        font-size: 10px;
    }
    QSlider {
        height: 32px;
    }
    QSlider::groove:horizontal {
        border: none;
        height: 4px;
        background: #2c2c2e;
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #6e9fff;
        width: 22px;
        height: 22px;
        margin: -9px 0;
        border-radius: 11px;
    }
    QSlider::handle:horizontal:hover {
        background: #8bb4ff;
    }
    QSlider::sub-page:horizontal {
        background: #6e9fff;
        border-radius: 2px;
    }
    QComboBox {
        background-color: #2c2c2e;
        color: #e0e0e0;
        border: none;
        border-radius: 12px;
        padding: 10px 14px;
        font-size: 13px;
    }
    QComboBox::drop-down {
        border: none;
        width: 28px;
    }
    QComboBox QAbstractItemView {
        background-color: #2c2c2e;
        color: #e0e0e0;
        selection-background-color: #6e9fff;
        selection-color: #ffffff;
        border: none;
        border-radius: 12px;
        padding: 4px;
    }
    QPushButton#quit {
        background-color: #2c2c2e;
        color: #888888;
        border: none;
        border-radius: 14px;
        padding: 12px 16px;
        font-size: 13px;
        font-weight: 600;
    }
    QPushButton#quit:hover {
        background-color: #f44336;
        color: #ffffff;
    }
    QPushButton#fileBtn {
        background-color: #2c2c2e;
        color: #e0e0e0;
        border: none;
        border-radius: 12px;
        padding: 10px 14px;
        font-size: 12px;
    }
    QPushButton#fileBtn:hover {
        background-color: #3a3a3c;
    }
    QLabel#bgFileLabel {
        color: #6a6a6a;
        font-size: 10px;
    }
    QFrame#separator {
        background-color: #2c2c2e;
        border: none;
    }
"""

FOCAL_LABELS = {
    1.0: "24mm  Wide",
    1.5: "35mm  Street",
    2.0: "50mm  Natural",
    2.5: "60mm  Portrait",
    3.0: "75mm  Tight",
}


# ── Samsung-style toggle switch ──────────────────────────────────────────────
class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)

    def __init__(self, label="", checked=False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self._label = label
        self._knob_x = 26.0 if checked else 4.0
        self.setFixedHeight(48)
        self.setCursor(Qt.PointingHandCursor)

        self._anim = QPropertyAnimation(self, b"knob_x")
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.OutBack)

    def get_knob_x(self):
        return self._knob_x

    def set_knob_x(self, val):
        self._knob_x = val
        self.update()

    knob_x = pyqtProperty(float, get_knob_x, set_knob_x)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = checked
        target = 26.0 if checked else 4.0
        self._anim.stop()
        self._anim.setStartValue(self._knob_x)
        self._anim.setEndValue(target)
        self._anim.start()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.setChecked(self._checked)
        self.toggled.emit(self._checked)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # Label text
        p.setPen(QColor("#cccccc"))
        p.setFont(QFont("Noto Sans", 12))
        p.drawText(QRect(0, 0, w - 56, h), Qt.AlignVCenter | Qt.AlignLeft, self._label)

        # Track
        track_w, track_h = 48, 28
        track_x = w - track_w - 2
        track_y = (h - track_h) // 2

        if self._checked:
            track_color = QColor("#6e9fff")
        else:
            track_color = QColor("#3a3a3c")

        p.setBrush(track_color)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(track_x, track_y, track_w, track_h, track_h // 2, track_h // 2)

        # Knob
        knob_r = 20
        knob_y = (h - knob_r) // 2
        knob_actual_x = track_x + self._knob_x

        p.setBrush(QColor("#ffffff"))
        # Subtle shadow
        p.setPen(QPen(QColor(0, 0, 0, 30), 1))
        p.drawEllipse(int(knob_actual_x), knob_y, knob_r, knob_r)

        p.end()


# ── Settings persistence ─────────────────────────────────────────────────────
def load_settings():
    defaults = {
        "zoom": 20, "dist": 35, "cam_index": 0, "autostart": False,
        "bg_mode": 0, "bg_blur": 21, "bg_file": "", "bg_invert": False,
    }
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH) as f:
                saved = json.load(f)
            defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_settings(zoom_val, dist_val, cam_index, autostart, bg_mode=0, bg_blur=21, bg_file="", bg_invert=False):
    data = {
        "zoom": zoom_val,
        "dist": dist_val,
        "cam_index": cam_index,
        "autostart": autostart,
        "bg_mode": bg_mode,
        "bg_blur": bg_blur,
        "bg_file": bg_file,
        "bg_invert": bg_invert,
    }
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)


# ── Autostart ────────────────────────────────────────────────────────────────
def is_autostart_enabled():
    return os.path.exists(AUTOSTART_FILE)


def set_autostart(enabled):
    if enabled:
        os.makedirs(AUTOSTART_DIR, exist_ok=True)
        with open(AUTOSTART_FILE, "w") as f:
            f.write(f"""[Desktop Entry]
Name=NokiCam
Comment=Webcam lens corrector — starts on login
Exec={LAUNCHER_SCRIPT}
Icon=camera-web
Terminal=false
Type=Application
X-GNOME-Autostart-enabled=true
""")
    else:
        if os.path.exists(AUTOSTART_FILE):
            os.remove(AUTOSTART_FILE)


def load_config(path="config.json"):
    if not os.path.exists(path):
        print(f"Error: {path} not found.")
        sys.exit(1)
    with open(path) as f:
        cfg = json.load(f)
    return (
        np.array(cfg["camera_matrix"]),
        np.array(cfg["dist_coeffs"]),
        tuple(cfg["frame_size"]),
    )


def find_cameras():
    cameras = []
    for dev in sorted(glob.glob("/dev/video*")):
        idx = dev.replace("/dev/video", "")
        if not idx.isdigit():
            continue
        idx = int(idx)
        if idx == 10:
            continue
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            cameras.append((idx, f"Camera {idx}"))
            cap.release()
    if not cameras:
        cameras.append((0, "Camera 0"))
    return cameras


def focal_label_for(zoom):
    mm = zoom * 25
    closest = min(FOCAL_LABELS.keys(), key=lambda k: abs(k - zoom))
    if abs(closest - zoom) < 0.15:
        return FOCAL_LABELS[closest]
    return f"~{mm:.0f}mm"


# ── Threaded camera reader ───────────────────────────────────────────────────
class CameraReader:
    def __init__(self, cam_index, w, h):
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self._running = True
        self._open(cam_index, w, h)
        self.w = w
        self.h = h
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _open(self, cam_index, w, h):
        if self.cap and self.cap.isOpened():
            self.cap.release()
        _backend = cv2.CAP_DSHOW if __import__('platform').system() == 'Windows' else cv2.CAP_V4L2
        self.cap = cv2.VideoCapture(cam_index, _backend)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def switch(self, cam_index):
        with self.lock:
            self._pending_switch = cam_index

    def grab(self):
        with self.lock:
            return self.frame

    def stop(self):
        self._running = False

    def _loop(self):
        self._pending_switch = None
        while self._running:
            # Handle camera switch on the reader thread
            with self.lock:
                pending = self._pending_switch
                self._pending_switch = None
            if pending is not None:
                self._open(pending, self.w, self.h)
                with self.lock:
                    self.frame = None

            if self.cap and self.cap.isOpened():
                ret, frame = self.cap.read()
                if ret:
                    with self.lock:
                        self.frame = frame
            else:
                time.sleep(0.01)
        if self.cap:
            self.cap.release()


# ── Processing worker ────────────────────────────────────────────────────────
class ProcessWorker(QThread):
    frame_ready = pyqtSignal(np.ndarray, np.ndarray)
    fps_update = pyqtSignal(int)

    def __init__(self, reader, frame_size, camera_matrix, dist_coeffs, zoom, k1):
        super().__init__()
        self.reader = reader
        self.w, self.h = frame_size
        self.camera_matrix = camera_matrix
        self.dist_coeffs = dist_coeffs
        self.zoom = zoom
        self.k1 = k1
        self._running = True
        self._maps_dirty = True
        self.map1 = None
        self.map2 = None
        self.preview_w = 960
        self.preview_h = 540
        self.bg_processor = BackgroundProcessor()
        self.filter_pipeline = FilterPipeline()

    def update_zoom(self, zoom):
        self.zoom = zoom
        self._maps_dirty = True

    def update_k1(self, k1):
        self.k1 = k1
        self._maps_dirty = True

    def set_bg_mode(self, mode):
        self.bg_processor.mode = mode

    def set_bg_blur(self, val):
        self.bg_processor.set_blur_strength(val)

    def load_bg_image(self, path):
        return self.bg_processor.load_image(path, self.w, self.h)

    def load_bg_gif(self, path):
        return self.bg_processor.load_gif(path, self.w, self.h)

    def stop(self):
        self._running = False

    def _rebuild_maps(self):
        modified = self.dist_coeffs.copy()
        modified.flat[0] = self.k1
        map1, map2 = build_undistort_maps(
            (self.w, self.h), self.camera_matrix, modified, self.zoom
        )
        # Upload remap LUTs to GPU (OpenCL) so cv2.remap runs on GPU
        self.map1 = cv2.UMat(map1)
        self.map2 = cv2.UMat(map2)
        self._maps_dirty = False

    def run(self):
        self._rebuild_maps()
        frame_count = 0
        t0 = time.monotonic()

        while self._running:
            frame = self.reader.grab()
            if frame is None:
                time.sleep(0.002)
                continue

            if self._maps_dirty:
                self._rebuild_maps()

            # ── GPU: upload + remap on OpenCL ───────────────────────────────
            gpu_frame = cv2.UMat(frame)
            gpu_undistorted = cv2.remap(gpu_frame, self.map1, self.map2,
                                        cv2.INTER_LINEAR)

            # ── Background effect runs at full res (segmentation needs it) ──
            cpu_full = gpu_undistorted.get()
            cpu_full = self.bg_processor.process(cpu_full)

            # ── Downscale BEFORE filters — filters run at preview res (4× faster) ──
            small_bgr = cv2.resize(cpu_full, (self.preview_w, self.preview_h),
                                   interpolation=cv2.INTER_AREA)

            # ── Filters run at preview resolution (960×540) ──────────────────
            filtered = self.filter_pipeline.process(small_bgr)

            # ── Convert for Qt preview ───────────────────────────────────────
            preview_rgb = cv2.cvtColor(filtered, cv2.COLOR_BGR2RGB)

            # ── Virtual cam needs full-res RGB — upscale if vcam is active ──
            # (reuse cpu_full if no filters active, else upscale filtered)
            if self.filter_pipeline.active_filters:
                full_rgb = cv2.cvtColor(
                    cv2.resize(filtered, (self.w, self.h), interpolation=cv2.INTER_LINEAR),
                    cv2.COLOR_BGR2RGB
                )
            else:
                full_rgb = cv2.cvtColor(cpu_full, cv2.COLOR_BGR2RGB)

            self.frame_ready.emit(preview_rgb, full_rgb)

            frame_count += 1
            elapsed = time.monotonic() - t0
            if elapsed >= 1.0:
                self.fps_update.emit(int(frame_count / elapsed))
                frame_count = 0
                t0 = time.monotonic()


# ── Preview label that never lets the pixmap drive layout ─────────────────────
class PreviewLabel(QLabel):
    scale_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fixed_hint = QSize(320, 180)
        self._scale = 1.0

    def get_scale(self):
        return self._scale

    def set_scale(self, val):
        self._scale = val
        self.scale_changed.emit()

    preview_scale = pyqtProperty(float, get_scale, set_scale)

    def sizeHint(self):
        return self._fixed_hint

    def minimumSizeHint(self):
        return self._fixed_hint


# ── Animated button ──────────────────────────────────────────────────────────
class AnimatedButton(QPushButton):
    """Button with Samsung-style press animation."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._scale_anim = QPropertyAnimation(self, b"geometry")
        self._scale_anim.setDuration(150)
        self._scale_anim.setEasingCurve(QEasingCurve.OutBack)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        geo = self.geometry()
        shrink = QRect(geo.x() + 2, geo.y() + 1, geo.width() - 4, geo.height() - 2)
        self._scale_anim.stop()
        self._scale_anim.setStartValue(geo)
        self._scale_anim.setEndValue(shrink)
        self._scale_anim.setDuration(80)
        self._scale_anim.setEasingCurve(QEasingCurve.InQuad)
        self._scale_anim.start()

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        geo = self.geometry()
        restore = QRect(geo.x() - 2, geo.y() - 1, geo.width() + 4, geo.height() + 2)
        self._scale_anim.stop()
        self._scale_anim.setStartValue(geo)
        self._scale_anim.setEndValue(restore)
        self._scale_anim.setDuration(300)
        self._scale_anim.setEasingCurve(QEasingCurve.OutBack)
        self._scale_anim.start()


# ── Filters dialog ──────────────────────────────────────────────────────────
_FILTERS_DIALOG_STYLE = """
    QDialog { background-color: #1c1c1e; }
    QTabWidget::pane { border: none; background: #1c1c1e; }
    QTabBar::tab {
        background: #2c2c2e; color: #aaa; padding: 10px 20px;
        border: none; border-radius: 8px; margin: 2px;
        font-size: 12px; font-weight: 600;
    }
    QTabBar::tab:selected { background: #6e9fff; color: #fff; }
    QScrollArea { background: transparent; border: none; }
    QCheckBox {
        color: #e0e0e0; font-size: 13px; padding: 6px 4px; spacing: 8px;
    }
    QCheckBox::indicator {
        width: 20px; height: 20px; border-radius: 4px;
        border: 2px solid #4a4a4a; background: #2c2c2e;
    }
    QCheckBox::indicator:checked { background: #6e9fff; border-color: #6e9fff; }
    QLabel#paramLabel { color: #6e9fff; font-size: 10px; font-weight: bold;
        letter-spacing: 1px; padding-left: 28px; }
    QLabel#paramValue { color: #ffffff; font-size: 12px; font-weight: bold; }
    QSlider { height: 28px; }
    QSlider::groove:horizontal {
        border: none; height: 4px; background: #2c2c2e; border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #6e9fff; width: 18px; height: 18px;
        margin: -7px 0; border-radius: 9px;
    }
    QSlider::sub-page:horizontal { background: #6e9fff; border-radius: 2px; }
    QPushButton#clearBtn {
        background: #2c2c2e; color: #f44336; border: none;
        border-radius: 10px; padding: 8px; font-size: 12px;
    }
    QPushButton#clearBtn:hover { background: #f44336; color: #fff; }
    QFrame#paramBox {
        background: #242426; border-radius: 8px;
        margin-left: 24px; margin-right: 4px;
    }
"""


class FiltersDialog(QDialog):
    """Two-tab dialog for toggling filters on/off, with sliders for tunable filters."""

    filter_changed = pyqtSignal()

    def __init__(self, pipeline, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.setWindowTitle("Filters")
        self.setMinimumSize(380, 540)
        self.setStyleSheet(_FILTERS_DIALOG_STYLE)
        self._checkboxes = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        tabs = QTabWidget()
        tabs.addTab(self._build_filter_list(USEFUL_FILTERS), "Useful (50)")
        tabs.addTab(self._build_filter_list(FUNNY_FILTERS), "Funny (50)")
        layout.addWidget(tabs)

        clear_btn = QPushButton("Clear All Filters")
        clear_btn.setObjectName("clearBtn")
        clear_btn.clicked.connect(self._clear_all)
        layout.addWidget(clear_btn)

    def _build_filter_list(self, filter_dict):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        vbox = QVBoxLayout(container)
        vbox.setSpacing(4)
        vbox.setContentsMargins(4, 4, 4, 4)

        for name in filter_dict:
            cb = QCheckBox(name)
            cb.setChecked(name in self.pipeline.active_filters)

            # Build param widgets (hidden until filter is enabled)
            param_box = None
            if name in FILTER_PARAMS_SPEC:
                param_box = self._build_param_box(name, FILTER_PARAMS_SPEC[name])
                param_box.setVisible(cb.isChecked())

            cb.toggled.connect(lambda checked, n=name, pb=param_box: self._on_toggle(n, checked, pb))
            vbox.addWidget(cb)
            if param_box:
                vbox.addWidget(param_box)

            self._checkboxes.append(cb)

        vbox.addStretch()
        scroll.setWidget(container)
        return scroll

    def _build_param_box(self, filter_name, specs):
        """Build a card with sliders for each tunable parameter."""
        box = QFrame()
        box.setObjectName("paramBox")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(8, 6, 8, 6)
        box_layout.setSpacing(2)

        for label_text, key, default, mn, mx, step, display_scale in specs:
            lbl = QLabel(label_text.upper())
            lbl.setObjectName("paramLabel")
            box_layout.addWidget(lbl)

            # Convert float range to integer slider
            int_min = int(round(mn / step))
            int_max = int(round(mx / step))
            int_default = int(round(default / step))

            slider = QSlider(Qt.Horizontal)
            slider.setRange(int_min, int_max)
            slider.setValue(int_default)

            val_label = QLabel(self._format_value(default * display_scale, display_scale))
            val_label.setObjectName("paramValue")
            val_label.setAlignment(Qt.AlignRight)

            row = QHBoxLayout()
            row.addWidget(slider, stretch=1)
            row.addWidget(val_label)
            box_layout.addLayout(row)

            slider.valueChanged.connect(
                lambda v, fn=filter_name, k=key, s=step, ds=display_scale, vl=val_label:
                    self._on_slider(fn, k, v * s, ds, vl)
            )

        return box

    def _format_value(self, val, display_scale):
        if display_scale == 100:
            return f"{val:.0f}%"
        elif display_scale == 10:
            return f"{val:.1f}"
        else:
            return f"{val:.0f}"

    def _on_slider(self, filter_name, key, value, display_scale, val_label):
        set_param(filter_name, key, value)
        val_label.setText(self._format_value(value * display_scale, display_scale))

    def _on_toggle(self, name, checked, param_box):
        self.pipeline.set_active(name, checked)
        if param_box:
            param_box.setVisible(checked)
        self.filter_changed.emit()

    def _clear_all(self):
        self.pipeline.clear()
        for cb in self._checkboxes:
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self.filter_changed.emit()


class NokiCam(QMainWindow):
    def __init__(self, config_path="config.json", virtual_cam_device="/dev/video10"):
        super().__init__()
        self.setWindowTitle("NokiCam")
        self.setMinimumSize(700, 400)
        self.resize(1100, 620)

        self.virtual_cam_device = virtual_cam_device
        self.camera_matrix, self.dist_coeffs, self.frame_size = load_config(config_path)
        self.w, self.h = self.frame_size
        self.vcam = None
        self._last_pixmap = None
        self._preview_scale = 1.0  # 1.0 = fill available space
        self._preview_anim = None

        # Load saved settings
        self.settings = load_settings()
        self.current_zoom = self.settings["zoom"] / 10.0
        self.current_k1 = -self.settings["dist"] / 100.0
        self.current_cam = self.settings["cam_index"]

        self._build_ui()
        self._start_vcam()

        # Start reader and processor threads
        self.reader = CameraReader(self.current_cam, self.w, self.h)
        self.worker = ProcessWorker(
            self.reader, self.frame_size, self.camera_matrix, self.dist_coeffs,
            self.current_zoom, self.current_k1,
        )
        self.worker.frame_ready.connect(self._on_frame)
        self.worker.fps_update.connect(self._on_fps)
        self.worker.start()

        # Apply saved background settings
        saved_bg_mode = self.settings.get("bg_mode", 0)
        if saved_bg_mode > 0:
            mode_data = self.bg_combo.itemData(saved_bg_mode)
            self.worker.set_bg_mode(mode_data)
            self.worker.set_bg_blur(self.settings.get("bg_blur", 21))
            self.worker.bg_processor.invert_mask = self.settings.get("bg_invert", False)
            if self._bg_file_path and mode_data in (BackgroundProcessor.MODE_IMAGE, BackgroundProcessor.MODE_GIF):
                self._load_bg_file(self._bg_file_path, mode_data)

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("centralWidget")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # ── Left: preview ────────────────────────────────────────────────
        self.preview = PreviewLabel()
        self.preview.setObjectName("preview")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.preview.setMinimumSize(320, 180)
        root.addWidget(self.preview, stretch=3)

        # ── Right: controls card ─────────────────────────────────────────
        panel_card = QWidget()
        panel_card.setObjectName("panelCard")
        panel = QVBoxLayout(panel_card)
        panel.setSpacing(6)
        panel.setContentsMargins(16, 16, 16, 16)

        # Title
        title = QLabel("NokiCam")
        title.setFont(QFont("Noto Sans", 20, QFont.Bold))
        title.setStyleSheet("color: #6e9fff;")
        panel.addWidget(title)

        self.vcam_status = QLabel("Starting...")
        self.vcam_status.setObjectName("statusOff")
        panel.addWidget(self.vcam_status)

        self.fps_label = QLabel("")
        self.fps_label.setObjectName("fpsLabel")
        panel.addWidget(self.fps_label)

        panel.addSpacing(8)
        self._add_separator(panel)

        # Camera input
        section = QLabel("CAMERA")
        section.setObjectName("sectionTitle")
        panel.addWidget(section)

        self.camera_combo = QComboBox()
        self.cameras = find_cameras()
        selected_idx = 0
        for i, (idx, name) in enumerate(self.cameras):
            self.camera_combo.addItem(name, idx)
            if idx == self.current_cam:
                selected_idx = i
        self.camera_combo.setCurrentIndex(selected_idx)
        self.camera_combo.currentIndexChanged.connect(self._on_camera_changed)
        panel.addWidget(self.camera_combo)

        panel.addSpacing(4)
        self._add_separator(panel)

        # Focal length
        section = QLabel("FOCAL LENGTH")
        section.setObjectName("sectionTitle")
        panel.addWidget(section)

        self.focal_value = QLabel(focal_label_for(self.current_zoom))
        self.focal_value.setObjectName("valueLabel")
        panel.addWidget(self.focal_value)

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 40)
        self.zoom_slider.setValue(self.settings["zoom"])
        self.zoom_slider.valueChanged.connect(self._on_zoom_changed)
        panel.addWidget(self.zoom_slider)

        hint = QLabel("wider                         tighter")
        hint.setObjectName("hint")
        hint.setAlignment(Qt.AlignCenter)
        panel.addWidget(hint)

        panel.addSpacing(4)
        self._add_separator(panel)

        # Distortion
        section = QLabel("BARREL FIX")
        section.setObjectName("sectionTitle")
        panel.addWidget(section)

        self.dist_value = QLabel(f"{self.settings['dist'] / 100.0:.2f}")
        self.dist_value.setObjectName("valueLabel")
        panel.addWidget(self.dist_value)

        self.dist_slider = QSlider(Qt.Horizontal)
        self.dist_slider.setRange(0, 60)
        self.dist_slider.setValue(self.settings["dist"])
        self.dist_slider.valueChanged.connect(self._on_dist_changed)
        panel.addWidget(self.dist_slider)

        hint2 = QLabel("less                            more")
        hint2.setObjectName("hint")
        hint2.setAlignment(Qt.AlignCenter)
        panel.addWidget(hint2)

        panel.addSpacing(4)
        self._add_separator(panel)

        # Background mode
        section = QLabel("BACKGROUND")
        section.setObjectName("sectionTitle")
        panel.addWidget(section)

        self.bg_combo = QComboBox()
        self.bg_combo.addItem("Off", BackgroundProcessor.MODE_OFF)
        self.bg_combo.addItem("Blur", BackgroundProcessor.MODE_BLUR)
        self.bg_combo.addItem("Image", BackgroundProcessor.MODE_IMAGE)
        self.bg_combo.addItem("GIF", BackgroundProcessor.MODE_GIF)
        self.bg_combo.setCurrentIndex(self.settings.get("bg_mode", 0))
        self.bg_combo.currentIndexChanged.connect(self._on_bg_mode_changed)
        panel.addWidget(self.bg_combo)

        # Invert toggle (cut person instead of background)
        self.invert_toggle = ToggleSwitch("Invert cutout", self.settings.get("bg_invert", False))
        self.invert_toggle.toggled.connect(self._on_invert_toggled)
        panel.addWidget(self.invert_toggle)

        # Blur strength slider (only visible in blur mode)
        self.blur_label = QLabel("BLUR STRENGTH")
        self.blur_label.setObjectName("sectionTitle")
        panel.addWidget(self.blur_label)

        self.blur_slider = QSlider(Qt.Horizontal)
        self.blur_slider.setRange(5, 81)
        self.blur_slider.setSingleStep(2)
        self.blur_slider.setValue(self.settings.get("bg_blur", 21))
        self.blur_slider.valueChanged.connect(self._on_blur_changed)
        panel.addWidget(self.blur_slider)

        self.blur_value_label = QLabel(str(self.settings.get("bg_blur", 21)))
        self.blur_value_label.setObjectName("valueLabel")
        panel.addWidget(self.blur_value_label)

        # File picker button (for image/gif modes)
        self.bg_file_btn = AnimatedButton("Choose file...")
        self.bg_file_btn.setObjectName("fileBtn")
        self.bg_file_btn.clicked.connect(self._on_bg_file_pick)
        panel.addWidget(self.bg_file_btn)

        self.bg_file_label = QLabel("")
        self.bg_file_label.setObjectName("bgFileLabel")
        self.bg_file_label.setWordWrap(True)
        panel.addWidget(self.bg_file_label)

        # Store the background file path
        self._bg_file_path = self.settings.get("bg_file", "")
        if self._bg_file_path:
            self.bg_file_label.setText(os.path.basename(self._bg_file_path))

        # Set initial visibility based on saved mode
        self._update_bg_controls_visibility(self.settings.get("bg_mode", 0))

        panel.addSpacing(4)
        self._add_separator(panel)

        # Filters button
        section = QLabel("FILTERS")
        section.setObjectName("sectionTitle")
        panel.addWidget(section)

        self.filters_btn = AnimatedButton("Open Filters...")
        self.filters_btn.setObjectName("fileBtn")
        self.filters_btn.clicked.connect(self._open_filters_dialog)
        panel.addWidget(self.filters_btn)

        self.active_filters_label = QLabel("No filters active")
        self.active_filters_label.setObjectName("hint")
        panel.addWidget(self.active_filters_label)

        panel.addSpacing(4)
        self._add_separator(panel)

        # Autostart toggle
        self.autostart_toggle = ToggleSwitch("Start on login", is_autostart_enabled())
        self.autostart_toggle.toggled.connect(self._on_autostart_toggled)
        panel.addWidget(self.autostart_toggle)

        panel.addSpacing(4)
        self._add_separator(panel)

        # Window size
        section = QLabel("PREVIEW SIZE")
        section.setObjectName("sectionTitle")
        panel.addWidget(section)

        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        smaller_btn = AnimatedButton("−")
        smaller_btn.setObjectName("quit")
        smaller_btn.setFixedHeight(36)
        smaller_btn.clicked.connect(lambda: self._animate_preview_scale(False))
        size_row.addWidget(smaller_btn)

        bigger_btn = AnimatedButton("+")
        bigger_btn.setObjectName("quit")
        bigger_btn.setFixedHeight(36)
        bigger_btn.clicked.connect(lambda: self._animate_preview_scale(True))
        size_row.addWidget(bigger_btn)
        panel.addLayout(size_row)

        panel.addStretch()

        # Quit
        quit_btn = AnimatedButton("Quit")
        quit_btn.setObjectName("quit")
        quit_btn.clicked.connect(self.close)
        panel.addWidget(quit_btn)

        panel_card.setFixedWidth(280)
        root.addWidget(panel_card, stretch=0)

    def _add_separator(self, layout):
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFixedHeight(1)
        layout.addWidget(sep)

    def _start_vcam(self):
        try:
            self.vcam = VirtualCamera(width=self.w, height=self.h, fps=30)
            if self.vcam.is_active:
                self.vcam_status.setText(f"Virtual cam: {self.vcam.device_name}")
                self.vcam_status.setObjectName("statusOn")
            else:
                self.vcam_status.setText("Preview only (no virtual cam driver)")
                self.vcam_status.setObjectName("statusOff")
            self.vcam_status.setStyle(self.vcam_status.style())
        except Exception as e:
            self.vcam_status.setText("Virtual cam unavailable")
            self.vcam_status.setObjectName("statusOff")
            self.vcam_status.setStyle(self.vcam_status.style())
            print(f"[VirtualCam] Error: {e}")
            self.vcam = None

    def _on_camera_changed(self, index):
        cam_idx = self.camera_combo.currentData()
        self.current_cam = cam_idx
        self.reader.switch(cam_idx)

    @pyqtSlot(int)
    def _on_fps(self, fps):
        self.fps_label.setText(f"{fps} fps")

    def _on_zoom_changed(self, val):
        self.current_zoom = max(1.0, val / 10.0)
        self.focal_value.setText(focal_label_for(self.current_zoom))
        self.worker.update_zoom(self.current_zoom)

    def _on_dist_changed(self, val):
        self.current_k1 = -val / 100.0
        self.dist_value.setText(f"{val / 100.0:.2f}")
        self.worker.update_k1(self.current_k1)

    def _on_autostart_toggled(self, checked):
        set_autostart(checked)

    def _on_invert_toggled(self, checked):
        self.worker.bg_processor.invert_mask = checked

    def _open_filters_dialog(self):
        dlg = FiltersDialog(self.worker.filter_pipeline, self)
        dlg.filter_changed.connect(self._update_filter_label)
        dlg.exec_()

    def _update_filter_label(self):
        active = self.worker.filter_pipeline.active_filters
        n = len(active)
        if n == 0:
            self.active_filters_label.setText("No filters active")
        elif n <= 3:
            self.active_filters_label.setText(", ".join(active))
        else:
            self.active_filters_label.setText(f"{n} filters active")

    def _on_bg_mode_changed(self, index):
        mode = self.bg_combo.currentData()
        self.worker.set_bg_mode(mode)
        self._update_bg_controls_visibility(index)
        # Auto-load saved file when switching to image/gif mode
        if mode in (BackgroundProcessor.MODE_IMAGE, BackgroundProcessor.MODE_GIF) and self._bg_file_path:
            self._load_bg_file(self._bg_file_path, mode)

    def _update_bg_controls_visibility(self, index):
        mode = self.bg_combo.itemData(index)
        is_blur = mode == BackgroundProcessor.MODE_BLUR
        is_file = mode in (BackgroundProcessor.MODE_IMAGE, BackgroundProcessor.MODE_GIF)
        self.blur_label.setVisible(is_blur)
        self.blur_slider.setVisible(is_blur)
        self.blur_value_label.setVisible(is_blur)
        self.bg_file_btn.setVisible(is_file)
        self.bg_file_label.setVisible(is_file)

    def _on_blur_changed(self, val):
        val = val | 1  # force odd
        self.blur_slider.blockSignals(True)
        self.blur_slider.setValue(val)
        self.blur_slider.blockSignals(False)
        self.blur_value_label.setText(str(val))
        self.worker.set_bg_blur(val)

    def _on_bg_file_pick(self):
        mode = self.bg_combo.currentData()
        if mode == BackgroundProcessor.MODE_GIF:
            filt = "GIF files (*.gif)"
        else:
            filt = "Images (*.png *.jpg *.jpeg *.bmp *.webp);;GIF files (*.gif);;All files (*)"
        path, _ = QFileDialog.getOpenFileName(self, "Select background", "", filt)
        if path:
            self._bg_file_path = path
            self.bg_file_label.setText(os.path.basename(path))
            self._load_bg_file(path, mode)

    def _load_bg_file(self, path, mode):
        if not os.path.exists(path):
            return
        if mode == BackgroundProcessor.MODE_GIF or path.lower().endswith(".gif"):
            self.worker.load_bg_gif(path)
        else:
            self.worker.load_bg_image(path)

    @pyqtSlot(np.ndarray, np.ndarray)
    def _on_frame(self, preview_rgb, full_rgb):
        if self.vcam:
            try:
                self.vcam.send(full_rgb)
            except Exception:
                pass

        h, w, ch = preview_rgb.shape
        img = QImage(preview_rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(img)

        # Scale to fit preview label, applying user scale factor
        label_size = self.preview.size()
        scale = self.preview._scale
        target_w = int(label_size.width() * scale)
        target_h = int(label_size.height() * scale)
        target_size = QSize(target_w, target_h)
        self._last_pixmap = pixmap.scaled(
            target_size, Qt.KeepAspectRatio, Qt.FastTransformation
        )
        self.preview.setPixmap(self._last_pixmap)

    def _animate_preview_scale(self, grow):
        current = self.preview._scale
        if grow:
            target = min(current + 0.15, 1.0)
        else:
            target = max(current - 0.15, 0.25)

        anim = QPropertyAnimation(self.preview, b"preview_scale")
        anim.setDuration(350)
        anim.setStartValue(current)
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.OutBack)
        anim.start()
        self._preview_anim = anim

    def closeEvent(self, event):
        save_settings(
            self.zoom_slider.value(),
            self.dist_slider.value(),
            self.current_cam,
            self.autostart_toggle.isChecked(),
            bg_mode=self.bg_combo.currentIndex(),
            bg_blur=self.blur_slider.value(),
            bg_file=self._bg_file_path,
            bg_invert=self.invert_toggle.isChecked(),
        )
        self.worker.stop()
        self.reader.stop()
        self.worker.wait(2000)
        if self.vcam:
            self.vcam.close()
        event.accept()


# ── Splash / loading screen ───────────────────────────────────────────────────
class SplashScreen(QWidget):
    """Dark loading window shown while NokiCam initialises."""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setFixedSize(420, 220)
        self.setStyleSheet("background:#1c1c1e; border-radius:18px;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(10)

        title = QLabel("NokiCam")
        title.setStyleSheet("color:#ffffff; font-size:28px; font-weight:700; letter-spacing:1px;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        self._status = QLabel("Starting up…")
        self._status.setStyleSheet("color:#aaaaaa; font-size:13px;")
        self._status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._status)

        layout.addSpacing(8)

        self._bar = QSlider(Qt.Horizontal)
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setEnabled(False)
        self._bar.setStyleSheet("""
            QSlider::groove:horizontal {
                height:6px; background:#2c2c2e; border-radius:3px;
            }
            QSlider::sub-page:horizontal {
                background:#6e9fff; border-radius:3px;
            }
            QSlider::handle:horizontal {
                width:0px; height:0px; margin:0;
            }
        """)
        layout.addWidget(self._bar)

        self._detail = QLabel("")
        self._detail.setStyleSheet("color:#666666; font-size:11px;")
        self._detail.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._detail)

        layout.addStretch()

        # Centre on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2,
        )
        self.show()
        QApplication.processEvents()

    def set_progress(self, pct: int, status: str, detail: str = ""):
        self._bar.setValue(max(0, min(100, pct)))
        self._status.setText(status)
        self._detail.setText(detail)
        QApplication.processEvents()


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NokiCam: webcam lens corrector")
    parser.add_argument("--cam",    type=int,   default=None,           help="Camera index override")
    parser.add_argument("--device", type=str,   default="/dev/video10", help="Virtual camera device")
    parser.add_argument("--config", type=str,   default="config.json",  help="Path to config.json")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_STYLE)

    splash = SplashScreen()

    splash.set_progress(10, "Detecting GPU…")
    try:
        from gpu_detect import detect_gpu, configure_opencv
        info = detect_gpu()
        configure_opencv(info)
        gpu_name = info.name
    except Exception:
        gpu_name = "CPU"
    splash.set_progress(25, "GPU ready", gpu_name)

    splash.set_progress(40, "Loading image processing…")
    # processor is already imported at top; just force-import to measure time
    import processor  # noqa: F401
    splash.set_progress(55, "Loading filters…")
    import filters  # noqa: F401

    splash.set_progress(70, "Checking segmentation model…")
    # Hook into model download to show progress
    import urllib.request as _ur
    import processor as _proc
    model_path = _proc.MODEL_PATH
    if not os.path.exists(model_path):
        splash.set_progress(72, "Downloading background removal model…",
                            "Only needed once (~3 MB)")
        downloaded = [0]
        total = [1]

        def _hook(count, block_size, total_size):
            total[0] = total_size or 1
            downloaded[0] = count * block_size
            pct = int(72 + 18 * min(downloaded[0] / total[0], 1.0))
            mb = downloaded[0] / 1_000_000
            splash.set_progress(pct, "Downloading background removal model…",
                                f"{mb:.1f} MB / {total[0]/1_000_000:.1f} MB")

        try:
            _ur.urlretrieve(_proc.MODEL_URL, model_path, reporthook=_hook)
        except Exception:
            pass
    splash.set_progress(90, "Initialising virtual camera…")

    splash.set_progress(95, "Opening window…")
    window = NokiCam(config_path=args.config, virtual_cam_device=args.device)

    splash.set_progress(100, "Ready!")
    QApplication.processEvents()
    # Brief pause so user sees 100%
    import time as _time
    _time.sleep(0.4)

    splash.close()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
