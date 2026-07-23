"""Metrics math tests on synthetic landmarks with known geometry.

Coordinate system reminder: normalized image coords, x grows right,
y grows DOWN. The synthetic golfer faces the camera, target to image right
(hands finish right of the hips), i.e. right-handed and not mirrored.
"""

import math

import pytest

from app.analysis.metrics import compute_metrics


def make_frame(overrides=None):
    """A neutral standing pose. 33 landmarks, all fully visible."""
    lm = [{"x": 0.5, "y": 0.5, "z": 0.0, "v": 1.0} for _ in range(33)]

    def put(i, x, y):
        lm[i] = {"x": x, "y": y, "z": 0.0, "v": 1.0}

    put(0, 0.50, 0.20)          # nose
    put(11, 0.60, 0.35)         # left shoulder  (image right = golfer's left)
    put(12, 0.40, 0.35)         # right shoulder
    put(13, 0.65, 0.45)         # left elbow
    put(14, 0.35, 0.45)         # right elbow
    put(15, 0.62, 0.55)         # left wrist
    put(16, 0.38, 0.55)         # right wrist
    put(23, 0.56, 0.55)         # left hip
    put(24, 0.44, 0.55)         # right hip
    put(27, 0.56, 0.90)         # left ankle
    put(28, 0.44, 0.90)         # right ankle
    for i, (x, y) in (overrides or {}).items():
        put(i, x, y)
    return lm


def landmarks_for(frames_map, total):
    """Sparse frame dict -> dense per-frame list (None elsewhere)."""
    return [frames_map.get(i) for i in range(total)]


# Finish frame with hands to the image-right of hips -> target is image right
FINISH = make_frame({15: (0.75, 0.30), 16: (0.75, 0.30)})
KEYS = {"p1": 0, "p4": 30, "p7": 40, "p10": 60}


def build(p1=None, p4=None, p7=None):
    frames = {
        0: p1 if p1 is not None else make_frame(),
        30: p4 if p4 is not None else make_frame(),
        40: p7 if p7 is not None else make_frame(),
        60: FINISH,
    }
    return landmarks_for(frames, 61)


def test_tempo_ratio_classic_3_to_1():
    result = compute_metrics(build(), KEYS, fps=30.0)
    assert result["metrics"]["tempo_ratio"]["value"] == 3.0


def test_short_game_gets_tempo_only():
    result = compute_metrics(build(), KEYS, fps=30.0, swing_type="chip")
    assert list(result["metrics"].keys()) == ["tempo_ratio"]
    assert any("coming soon" in n for n in result["notes"])


def test_shoulder_turn_from_foreshortening():
    # Address shoulder width 0.2; at the top it shrinks to 0.1 -> acos(0.5)=60°
    top = make_frame({11: (0.55, 0.35), 12: (0.45, 0.35)})
    result = compute_metrics(build(p4=top), KEYS, fps=30.0)
    assert result["metrics"]["shoulder_turn_p4"]["value"] == pytest.approx(60.0, abs=0.1)


def test_no_turn_means_zero_degrees():
    result = compute_metrics(build(), KEYS, fps=30.0)
    assert result["metrics"]["shoulder_turn_p4"]["value"] == pytest.approx(0.0, abs=0.1)


def test_spine_tilt_vertical_is_zero():
    result = compute_metrics(build(), KEYS, fps=30.0)
    assert result["metrics"]["spine_tilt_address"]["value"] == pytest.approx(0.0, abs=0.1)


def test_spine_tilt_away_from_target_is_positive():
    # Shift shoulders to image LEFT (away from target at image right):
    # atan2(dx=-0.05, dy=0.2) ≈ -14° from vertical, sign flips to positive
    tilted = make_frame({11: (0.55, 0.35), 12: (0.35, 0.35)})
    result = compute_metrics(build(p7=tilted), KEYS, fps=30.0)
    expected = math.degrees(math.atan2(0.05, 0.20))
    assert result["metrics"]["spine_tilt_impact"]["value"] == pytest.approx(expected, abs=0.2)
    assert result["metrics"]["spine_tilt_impact"]["value"] > 0


def test_head_sway_toward_target():
    # Nose moves +0.07 in x (toward target); height = 0.7 -> 10%
    impact = make_frame({0: (0.57, 0.20)})
    result = compute_metrics(build(p7=impact), KEYS, fps=30.0)
    assert result["metrics"]["head_sway"]["value"] == pytest.approx(10.0, abs=0.1)


def test_lead_arm_straight_is_180():
    # Shoulder-elbow-wrist collinear
    top = make_frame({11: (0.60, 0.35), 13: (0.65, 0.45), 15: (0.70, 0.55)})
    result = compute_metrics(build(p4=top), KEYS, fps=30.0)
    assert result["metrics"]["lead_arm_angle_p4"]["value"] == pytest.approx(180.0, abs=0.5)


def test_low_visibility_flags_metric():
    bad = make_frame()
    for i in (11, 12):
        bad[i]["v"] = 0.2  # shoulders barely visible at the top
    result = compute_metrics(build(p4=bad), KEYS, fps=30.0)
    m = result["metrics"]["shoulder_turn_p4"]
    assert m["value"] is None
    assert m["confidence"] == "low"


def test_missing_pose_frame_survives():
    frames = {0: make_frame(), 40: make_frame(), 60: FINISH}  # no pose at p4
    result = compute_metrics(landmarks_for(frames, 61), KEYS, fps=30.0)
    assert result["metrics"]["shoulder_turn_p4"]["value"] is None
    assert any("P4" in n for n in result["notes"])
