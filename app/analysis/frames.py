"""Frame extraction: video file -> numbered JPEGs at a sane size/rate.

We cap at 720p and ~60fps. Pose estimation is happy at 30, but tempo ratio
is quantized by frame rate (a driver downswing is only ~8 frames at 30fps),
so we keep 60 when the source has it. Processing cost roughly doubles —
acceptable; revisit if Range Mode misses its 60-second target.
"""

from pathlib import Path

import cv2

MAX_HEIGHT = 720
MAX_FPS = 60.0
JPEG_QUALITY = [cv2.IMWRITE_JPEG_QUALITY, 80]


def extract_frames(video_path: Path, frames_dir: Path) -> dict:
    frames_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"Could not open video: {video_path.name}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    if src_fps <= 0:
        src_fps = 30.0

    # Keep every Nth frame so effective fps stays <= MAX_FPS
    step = max(1, round(src_fps / MAX_FPS))

    read_count = 0
    saved = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if read_count % step == 0:
            h, w = frame.shape[:2]
            if h > MAX_HEIGHT:
                scale = MAX_HEIGHT / h
                frame = cv2.resize(frame, (round(w * scale), MAX_HEIGHT))
            cv2.imwrite(str(frames_dir / f"frame_{saved:04d}.jpg"), frame, JPEG_QUALITY)
            saved += 1
        read_count += 1
    cap.release()

    if saved == 0:
        raise ValueError("No frames could be read from the video.")

    return {
        "fps": src_fps / step,          # fps of the *extracted* sequence
        "frame_count": saved,
        "duration_s": read_count / src_fps,
    }
