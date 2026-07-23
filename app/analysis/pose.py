"""MediaPipe Pose (Tasks API) over an extracted frame sequence.

Note: mediapipe >= 0.10.30 removed the legacy mp.solutions API, so we use
the PoseLandmarker task with a downloaded model file, and draw the skeleton
ourselves with OpenCV.

Produces:
- overlay_NNNN.jpg per frame (skeleton drawn on the image)
- landmarks.json: per-frame landmark list (normalized x/y/z + visibility)
  plus a quality summary that drives the honesty indicator on reports.
"""

import json
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python import vision

MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_full/float16/latest/pose_landmarker_full.task"
)

# BlazePose 33-landmark skeleton (body only; face detail skipped)
POSE_CONNECTIONS = [
    (11, 12), (11, 13), (13, 15), (12, 14), (14, 16),          # arms
    (15, 17), (15, 19), (15, 21), (17, 19),                    # left hand
    (16, 18), (16, 20), (16, 22), (18, 20),                    # right hand
    (11, 23), (12, 24), (23, 24),                              # torso
    (23, 25), (25, 27), (24, 26), (26, 28),                    # legs
    (27, 29), (29, 31), (27, 31), (28, 30), (30, 32), (28, 32),  # feet
]

# Landmarks that matter most for our metrics; quality is judged on these.
KEY_LANDMARKS = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28]

LINE_COLOR = (80, 220, 110)   # BGR green
JOINT_COLOR = (60, 160, 255)  # BGR orange


def ensure_model(model_path: Path) -> Path:
    """Download the pose model once if missing (e.g. first boot on Railway)."""
    if not model_path.exists():
        model_path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, model_path)
    return model_path


def draw_skeleton(img, lms) -> None:
    h, w = img.shape[:2]
    pts = [(int(lm["x"] * w), int(lm["y"] * h)) for lm in lms]
    for a, b in POSE_CONNECTIONS:
        cv2.line(img, pts[a], pts[b], LINE_COLOR, 2, cv2.LINE_AA)
    for i, p in enumerate(pts):
        if i >= 11:  # skip face points
            cv2.circle(img, p, 4, JOINT_COLOR, -1, cv2.LINE_AA)


def run_pose(frames_dir: Path, overlays_dir: Path, landmarks_path: Path,
             fps: float, model_path: Path) -> dict:
    overlays_dir.mkdir(parents=True, exist_ok=True)
    frame_files = sorted(frames_dir.glob("frame_*.jpg"))

    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(ensure_model(model_path))),
        running_mode=vision.RunningMode.VIDEO,  # tracks across frames
        min_pose_detection_confidence=0.5,
        min_tracking_confidence=0.5,
    )

    per_frame = []
    key_visibilities = []

    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        for idx, f in enumerate(frame_files):
            img = cv2.imread(str(f))
            mp_img = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB),
            )
            ts_ms = int(idx * 1000 / fps)
            result = landmarker.detect_for_video(mp_img, ts_ms)

            if result.pose_landmarks:
                lms = [
                    {"x": round(lm.x, 5), "y": round(lm.y, 5),
                     "z": round(lm.z, 5), "v": round(lm.visibility, 3)}
                    for lm in result.pose_landmarks[0]
                ]
                key_visibilities.append(
                    sum(lms[i]["v"] for i in KEY_LANDMARKS) / len(KEY_LANDMARKS)
                )
                draw_skeleton(img, lms)
            else:
                lms = None

            per_frame.append(lms)
            cv2.imwrite(
                str(overlays_dir / f.name.replace("frame_", "overlay_")),
                img,
                [cv2.IMWRITE_JPEG_QUALITY, 80],
            )

    detected = len(key_visibilities)
    total = len(frame_files)
    quality = {
        "detection_rate": round(detected / total, 3) if total else 0.0,
        "mean_key_visibility": round(sum(key_visibilities) / detected, 3) if detected else 0.0,
        "frames_total": total,
        "frames_detected": detected,
    }

    with open(landmarks_path, "w") as fh:
        json.dump({"landmarks": per_frame, "quality": quality}, fh)

    return quality
