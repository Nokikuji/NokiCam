import cv2
import numpy as np
import json
import sys

CHECKERBOARD = (9, 6)   # inner corners (cols, rows)
SQUARE_SIZE  = 25.0     # mm — measure your printed checkerboard


def calibrate_from_webcam(cam_index=0):
    objp = np.zeros((CHECKERBOARD[0] * CHECKERBOARD[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:CHECKERBOARD[0], 0:CHECKERBOARD[1]].T.reshape(-1, 2)
    objp *= SQUARE_SIZE

    obj_points, img_points = [], []
    cap = cv2.VideoCapture(cam_index)

    if not cap.isOpened():
        print(f"Error: cannot open camera {cam_index}")
        sys.exit(1)

    print("=== NokiCam Lens Calibration ===")
    print(f"Checkerboard: {CHECKERBOARD[0]}×{CHECKERBOARD[1]} inner corners, {SQUARE_SIZE}mm squares")
    print("SPACE = capture frame (when corners detected)  |  Q = finish (need ≥15 frames)")
    print()

    frame = None
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Error: failed to read frame")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Faster detection with flags
        flags = cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
        found, corners = cv2.findChessboardCorners(gray, CHECKERBOARD, flags)

        display = frame.copy()
        if found:
            # Refine corner positions to sub-pixel accuracy
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
            cv2.drawChessboardCorners(display, CHECKERBOARD, corners, found)

        count_text = f"Captured: {len(obj_points)}/15+"
        status_text = "Corners FOUND — press SPACE" if found else "Searching for checkerboard..."
        color = (0, 255, 0) if found else (0, 100, 255)

        cv2.putText(display, count_text,  (10, 30),  cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        cv2.putText(display, status_text, (10, 65),  cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

        cv2.imshow("NokiCam Calibration", display)
        key = cv2.waitKey(1) & 0xFF

        if key == ord(' ') and found:
            obj_points.append(objp)
            img_points.append(corners)
            print(f"  Captured frame {len(obj_points)}")

        elif key == ord('q'):
            if len(obj_points) < 15:
                print(f"Only {len(obj_points)} frames captured — need at least 15. Keep going.")
            else:
                break

    cap.release()
    cv2.destroyAllWindows()

    if frame is None or len(obj_points) < 15:
        print("Calibration aborted — not enough frames.")
        sys.exit(1)

    h, w = frame.shape[:2]
    print(f"\nRunning calibration on {len(obj_points)} frames at {w}×{h}...")

    rms, mtx, dist, _, _ = cv2.calibrateCamera(obj_points, img_points, (w, h), None, None)

    config = {
        "camera_matrix": mtx.tolist(),
        "dist_coeffs": dist.tolist(),
        "frame_size": [w, h],
    }
    with open("config.json", "w") as f:
        json.dump(config, f, indent=2)

    print(f"\nCalibration complete!")
    print(f"  RMS reprojection error: {rms:.4f}  (good if < 1.0, excellent if < 0.5)")
    print(f"  Saved to config.json")

    if rms > 1.0:
        print("\n  WARNING: RMS > 1.0 — consider recalibrating with more frames and better lighting.")


if __name__ == "__main__":
    cam = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    calibrate_from_webcam(cam)
