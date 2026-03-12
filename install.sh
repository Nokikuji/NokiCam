#!/usr/bin/env bash
# NokiCam Installer — Linux (CachyOS / Arch)
# Checks before installing anything; safe to run multiple times.

set -euo pipefail

# ── colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[1;34m'
CYN='\033[0;36m'
RST='\033[0m'

ok()   { echo -e "  ${GRN}✔${RST}  $*"; }
skip() { echo -e "  ${BLU}–${RST}  $*"; }
info() { echo -e "  ${CYN}→${RST}  $*"; }
warn() { echo -e "  ${YLW}⚠${RST}  $*"; }
die()  { echo -e "\n  ${RED}✘  ERROR:${RST} $*\n"; exit 1; }

# ── header ─────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLU}╔══════════════════════════════════════════════╗${RST}"
echo -e "${BLU}║       NokiCam Installer — CachyOS/Arch       ║${RST}"
echo -e "${BLU}╚══════════════════════════════════════════════╝${RST}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── 1. Check distro ─────────────────────────────────────────────────────────
echo -e "${YLW}[1/7] Checking system...${RST}"
if ! command -v pacman &>/dev/null; then
    die "pacman not found. This installer is for CachyOS / Arch Linux only."
fi
ok "pacman found — Arch-based system confirmed"

# ── 2. Python 3.10+ ─────────────────────────────────────────────────────────
echo ""
echo -e "${YLW}[2/7] Checking Python...${RST}"

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
            PYTHON="$candidate"
            ok "Python $ver found at $(command -v "$candidate")"
            break
        else
            warn "Python $ver is too old (need 3.10+)"
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    info "Installing python via pacman..."
    sudo pacman -S --noconfirm python
    PYTHON=python3
    ok "Python installed"
fi

# pip
if ! "$PYTHON" -m pip --version &>/dev/null 2>&1; then
    info "Installing python-pip..."
    sudo pacman -S --noconfirm python-pip
    ok "pip installed"
else
    pip_ver=$("$PYTHON" -m pip --version | awk '{print $2}')
    ok "pip $pip_ver found"
fi

# ── 3. v4l2loopback kernel module ───────────────────────────────────────────
echo ""
echo -e "${YLW}[3/7] Checking v4l2loopback kernel module...${RST}"

V4L2_PKG_INSTALLED=false
V4L2_UTILS_INSTALLED=false

if pacman -Q v4l2loopback-dkms &>/dev/null 2>&1; then
    ok "v4l2loopback-dkms already installed"
    V4L2_PKG_INSTALLED=true
elif pacman -Q v4l2loopback &>/dev/null 2>&1; then
    ok "v4l2loopback (non-dkms) already installed"
    V4L2_PKG_INSTALLED=true
fi

if pacman -Q v4l2loopback-utils &>/dev/null 2>&1; then
    ok "v4l2loopback-utils already installed"
    V4L2_UTILS_INSTALLED=true
fi

if [[ "$V4L2_PKG_INSTALLED" == false ]]; then
    info "Installing v4l2loopback-dkms..."
    # CachyOS ships its own kernel; try the dkms package which rebuilds for any kernel
    if pacman -Si v4l2loopback-dkms &>/dev/null 2>&1; then
        sudo pacman -S --noconfirm v4l2loopback-dkms
    else
        warn "v4l2loopback-dkms not in repos — trying AUR via yay/paru..."
        if command -v yay &>/dev/null; then
            yay -S --noconfirm v4l2loopback-dkms
        elif command -v paru &>/dev/null; then
            paru -S --noconfirm v4l2loopback-dkms
        else
            die "Could not install v4l2loopback-dkms. Install yay or paru, then re-run."
        fi
    fi
    ok "v4l2loopback-dkms installed"
fi

if [[ "$V4L2_UTILS_INSTALLED" == false ]]; then
    info "Installing v4l2loopback-utils..."
    if pacman -Si v4l2loopback-utils &>/dev/null 2>&1; then
        sudo pacman -S --noconfirm v4l2loopback-utils
        ok "v4l2loopback-utils installed"
    else
        warn "v4l2loopback-utils not found in repos — skipping (non-critical)"
    fi
fi

# ── 4. Load the module ───────────────────────────────────────────────────────
echo ""
echo -e "${YLW}[4/7] Loading v4l2loopback module...${RST}"

MODULE_PARAMS="devices=1 video_nr=10 card_label=NokiCam exclusive_caps=1"

if lsmod | grep -q "^v4l2loopback"; then
    ok "v4l2loopback already loaded"
    # Check it has the right device
    if v4l2-ctl --list-devices 2>/dev/null | grep -q "NokiCam\|video10"; then
        ok "/dev/video10 (NokiCam) is available"
    else
        warn "Module loaded but /dev/video10 may not match expected params"
        warn "To reload with correct params run:"
        warn "  sudo modprobe -r v4l2loopback && sudo modprobe v4l2loopback $MODULE_PARAMS"
    fi
else
    info "Loading v4l2loopback with: $MODULE_PARAMS"
    sudo modprobe v4l2loopback $MODULE_PARAMS
    ok "v4l2loopback loaded → /dev/video10 (NokiCam)"
fi

# Persist across reboots
MODULES_LOAD="/etc/modules-load.d/v4l2loopback.conf"
MODPROBE_CONF="/etc/modprobe.d/v4l2loopback.conf"

if [[ -f "$MODULES_LOAD" ]]; then
    skip "Module auto-load already configured ($MODULES_LOAD)"
else
    echo "v4l2loopback" | sudo tee "$MODULES_LOAD" > /dev/null
    ok "Auto-load on boot configured ($MODULES_LOAD)"
fi

if [[ -f "$MODPROBE_CONF" ]]; then
    skip "Module options already configured ($MODPROBE_CONF)"
else
    echo "options v4l2loopback $MODULE_PARAMS" | sudo tee "$MODPROBE_CONF" > /dev/null
    ok "Module options persisted ($MODPROBE_CONF)"
fi

# ── 5. Python packages (venv) ────────────────────────────────────────────────
echo ""
echo -e "${YLW}[5/7] Setting up Python virtual environment + packages...${RST}"

REQ_FILE="$SCRIPT_DIR/requirements.txt"
[[ -f "$REQ_FILE" ]] || die "requirements.txt not found in $SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"

# Create venv if it doesn't exist
if [[ -d "$VENV_DIR" ]]; then
    skip "Virtual environment already exists ($VENV_DIR)"
else
    info "Creating virtual environment at $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created"
fi

check_venv_pkg() {
    local pkg="$1"
    local display="$2"
    if "$VENV_PYTHON" -c "import $pkg" &>/dev/null 2>&1; then
        installed=$("$VENV_PYTHON" -c "import $pkg; print(getattr($pkg, '__version__', 'ok'))" 2>/dev/null || echo "ok")
        ok "$display $installed"
        return 0
    fi
    return 1
}

need_pip_install=false
check_venv_pkg cv2         "opencv-python" || need_pip_install=true
check_venv_pkg numpy       "numpy"         || need_pip_install=true
check_venv_pkg pyvirtualcam "pyvirtualcam" || need_pip_install=true

if [[ "$need_pip_install" == true ]]; then
    info "Installing packages into venv..."
    "$VENV_PIP" install --upgrade pip -q
    "$VENV_PIP" install -r "$REQ_FILE"
    ok "Python packages installed into venv"
else
    skip "All Python packages already present in venv"
fi

# Write a thin activation helper so users just type: source activate.sh
ACTIVATE_HELPER="$SCRIPT_DIR/activate.sh"
cat > "$ACTIVATE_HELPER" <<ACTIVEOF
#!/usr/bin/env bash
# Source this file to activate the NokiCam venv:  source activate.sh
source "$(dirname "\${BASH_SOURCE[0]}")/.venv/bin/activate"
echo "NokiCam venv active. Run: python main.py"
ACTIVEOF
chmod +x "$ACTIVATE_HELPER"
ok "Activation helper written → activate.sh"

# ── 6. Desktop entry (application launcher) ─────────────────────────────────
echo ""
echo -e "${YLW}[6/7] Installing application launcher entry...${RST}"

LAUNCHER_SCRIPT="$SCRIPT_DIR/nokicam-launch.sh"
cat > "$LAUNCHER_SCRIPT" <<LAUNCHEOF
#!/usr/bin/env bash
# NokiCam launcher — activates venv then starts the app
cd "$SCRIPT_DIR"
source "$SCRIPT_DIR/.venv/bin/activate"
exec python "$SCRIPT_DIR/main.py" "\$@"
LAUNCHEOF
chmod +x "$LAUNCHER_SCRIPT"
ok "Launcher script written → nokicam-launch.sh"

DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/nokicam.desktop"
mkdir -p "$DESKTOP_DIR"

# Pick the best available icon — prefer a camera-specific one
ICON="camera-video"
for candidate in camera-web camera camera-video-symbolic video-display; do
    if gtk-update-icon-cache --help &>/dev/null || true; then
        # Just pick in priority order; desktop env resolves it
        ICON="$candidate"
        break
    fi
done

cat > "$DESKTOP_FILE" <<DESKTOPEOF
[Desktop Entry]
Name=NokiCam
Comment=Fisheye correction & 50mm lens simulator for webcam
Exec=$LAUNCHER_SCRIPT
Icon=$ICON
Terminal=false
Type=Application
Categories=Video;AudioVideo;Utility;
Keywords=webcam;camera;fisheye;lens;virtual;
StartupNotify=false
DESKTOPEOF

# Notify the desktop environment about the new entry
if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

ok "Desktop entry installed → $DESKTOP_FILE"
skip "NokiCam will appear in your application launcher"

# ── 7. Quick smoke test ──────────────────────────────────────────────────────
echo ""
echo -e "${YLW}[7/7] Smoke test...${RST}"

"$VENV_PYTHON" - <<'PYEOF'
import cv2, numpy as np, pyvirtualcam
print(f"  opencv        {cv2.__version__}")
print(f"  numpy         {np.__version__}")
print(f"  pyvirtualcam  ok")
PYEOF

if [[ -e /dev/video10 ]]; then
    ok "/dev/video10 exists — virtual camera ready"
else
    warn "/dev/video10 not present (module may need a moment, or reboot required)"
fi

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GRN}╔══════════════════════════════════════════════╗${RST}"
echo -e "${GRN}║           Installation complete!            ║${RST}"
echo -e "${GRN}╚══════════════════════════════════════════════╝${RST}"
echo ""
echo -e "  ${CYN}Ready to go!${RST} Default config for common webcams is included."
echo ""
echo -e "  ${CYN}1.${RST} Launch NokiCam from your ${YLW}application launcher${RST} (search: NokiCam)"
echo -e "       or from terminal: ${YLW}bash nokicam-launch.sh${RST}"
echo ""
echo -e "  ${CYN}2.${RST} In Zoom / Meet / OBS → select ${YLW}NokiCam${RST} as your camera"
echo ""
echo -e "  ${CYN}3.${RST} Use the on-screen sliders to fine-tune distortion + zoom live"
echo ""
echo -e "  ${BLU}Optional:${RST} For pixel-perfect calibration with your specific camera,"
echo -e "  print a 9×6 checkerboard pattern and run:"
echo -e "       ${YLW}source activate.sh && python calibrate.py${RST}"
echo ""
