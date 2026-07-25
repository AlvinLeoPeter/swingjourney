"""Annotated key-position images: skeleton + angle arcs + metric labels.

These four images are the shareable heart of a report, so they get real
drawing effort: title bar, per-position geometry (spine line, shoulder/hip
lines, lead-arm arc, head-sway marker) and a metric banner.
"""

import math
from pathlib import Path

import cv2

from .metrics import (
    L_ELBOW, L_HIP, L_SHOULDER, L_WRIST, NOSE, R_HIP, R_SHOULDER,
)
from .pose import draw_skeleton

FONT = cv2.FONT_HERSHEY_SIMPLEX
WHITE = (240, 244, 240)
YELLOW = (60, 210, 255)   # BGR
DIM = (20, 28, 22)

TITLES = {"p1": "P1 - Address", "p4": "P4 - Top", "p7": "P7 - Impact", "p10": "P10 - Finish"}


def _px(lms, i, w, h):
    return int(lms[i]["x"] * w), int(lms[i]["y"] * h)


def _mid_px(lms, i, j, w, h):
    a, b = _px(lms, i, w, h), _px(lms, j, w, h)
    return (a[0] + b[0]) // 2, (a[1] + b[1]) // 2


def _dashed_vline(img, x, y1, y2, color, dash=8):
    y = min(y1, y2)
    while y < max(y1, y2):
        cv2.line(img, (x, y), (x, min(y + dash, max(y1, y2))), color, 1, cv2.LINE_AA)
        y += dash * 2


def _arc(img, center, p_a, p_c, radius=36):
    a1 = math.degrees(math.atan2(p_a[1] - center[1], p_a[0] - center[0]))
    a2 = math.degrees(math.atan2(p_c[1] - center[1], p_c[0] - center[0]))
    sweep = (a2 - a1) % 360
    if sweep > 180:
        a1, sweep = a2, 360 - sweep
    cv2.ellipse(img, center, (radius, radius), 0, a1, a1 + sweep, YELLOW, 2, cv2.LINE_AA)


def _title_bar(img, text):
    h, w = img.shape[:2]
    bar = img[0:36, 0:w].copy()
    cv2.rectangle(img, (0, 0), (w, 36), DIM, -1)
    cv2.addWeighted(bar, 0.25, img[0:36, 0:w], 0.75, 0, img[0:36, 0:w])
    cv2.putText(img, text, (12, 25), FONT, 0.7, WHITE, 2, cv2.LINE_AA)


def _banner(img, lines):
    h, w = img.shape[:2]
    bh = 26 * len(lines) + 12
    bar = img[h - bh:h, 0:w].copy()
    cv2.rectangle(img, (0, h - bh), (w, h), DIM, -1)
    cv2.addWeighted(bar, 0.25, img[h - bh:h, 0:w], 0.75, 0, img[h - bh:h, 0:w])
    for i, line in enumerate(lines):
        cv2.putText(img, line, (12, h - bh + 26 * (i + 1)), FONT, 0.55, WHITE, 1, cv2.LINE_AA)


def _fmt(metrics, key, suffix=""):
    m = metrics.get(key)
    if not m or m.get("value") is None:
        return "n/a"
    return f"{m['value']}{suffix}"


def render_key_frames(frames_dir: Path, landmarks, key_positions, metrics, out_dir: Path) -> dict:
    """Returns {position: filename} for the four annotated images."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rendered = {}

    for pos in ("p1", "p4", "p7", "p10"):
        frame_no = key_positions[pos]
        img = cv2.imread(str(frames_dir / f"frame_{frame_no:04d}.jpg"))
        if img is None:
            continue
        h, w = img.shape[:2]
        lms = landmarks[frame_no] if frame_no < len(landmarks) else None

        if lms:
            draw_skeleton(img, lms)
            sh_mid = _mid_px(lms, L_SHOULDER, R_SHOULDER, w, h)
            hip_mid = _mid_px(lms, L_HIP, R_HIP, w, h)

            if pos in ("p1", "p7"):
                # spine line vs a vertical reference
                cv2.line(img, hip_mid, sh_mid, YELLOW, 2, cv2.LINE_AA)
                _dashed_vline(img, hip_mid[0], hip_mid[1], sh_mid[1] - 30, WHITE)

            if pos == "p4":
                # shoulder + hip lines to visualize the turn
                cv2.line(img, _px(lms, L_SHOULDER, w, h), _px(lms, R_SHOULDER, w, h), YELLOW, 2, cv2.LINE_AA)
                cv2.line(img, _px(lms, L_HIP, w, h), _px(lms, R_HIP, w, h), YELLOW, 2, cv2.LINE_AA)
                # lead arm arc at the elbow
                elbow = _px(lms, L_ELBOW, w, h)
                _arc(img, elbow, _px(lms, L_SHOULDER, w, h), _px(lms, L_WRIST, w, h))

            if pos == "p7" and landmarks[key_positions["p1"]]:
                # where the head started vs where it is now
                p1_lms = landmarks[key_positions["p1"]]
                nose_then = _px(p1_lms, NOSE, w, h)
                nose_now = _px(lms, NOSE, w, h)
                _dashed_vline(img, nose_then[0], nose_then[1] - 40, nose_then[1] + 40, WHITE)
                cv2.circle(img, nose_now, 5, YELLOW, -1, cv2.LINE_AA)

        _title_bar(img, TITLES[pos])
        _banner(img, {
            "p1": [f"Spine tilt {_fmt(metrics, 'spine_tilt_address', ' deg')}"],
            "p4": [
                f"Shoulder turn {_fmt(metrics, 'shoulder_turn_p4', ' deg')} (est)  "
                f"Hip turn {_fmt(metrics, 'hip_turn_p4', ' deg')} (est)",
                f"Lead arm {_fmt(metrics, 'lead_arm_angle_p4', ' deg')}",
            ],
            "p7": [
                f"Spine tilt {_fmt(metrics, 'spine_tilt_impact', ' deg')}  "
                f"Head sway {_fmt(metrics, 'head_sway', '%')}",
                f"Hip slide {_fmt(metrics, 'hip_slide', '%')}",
            ],
            "p10": [f"Tempo {_fmt(metrics, 'tempo_ratio')}:1"],
        }[pos])

        filename = f"key_{pos}.jpg"
        cv2.imwrite(str(out_dir / filename), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        rendered[pos] = filename

    return rendered
