"""Swing metrics from face-on 2D pose landmarks.

Honesty rules baked in:
- Every metric checks the visibility of the landmarks it uses at the frames
  it uses; below threshold it's flagged "low" confidence.
- Rotation at the top is *estimated* from shoulder/hip line foreshortening
  (2D can't measure true rotation) and is labeled as an estimate.
- Lengths are reported as % of the golfer's pixel height — we never invent
  centimeters we can't know.
- Full metric suite only for full swings; everything else gets tempo only.

Assumes a right-handed golfer for the lead arm (noted on the report).
Target direction is inferred from where the hands finish (P10).
"""

import math

NOSE = 0
L_SHOULDER, R_SHOULDER = 11, 12
L_ELBOW, R_ELBOW = 13, 14
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
L_ANKLE, R_ANKLE = 27, 28

VIS_THRESHOLD = 0.5
METRICS_VERSION = "metrics-v1"


def _visible(lms, idxs):
    return all(lms[i]["v"] >= VIS_THRESHOLD for i in idxs)


def _mid(lms, i, j):
    return ((lms[i]["x"] + lms[j]["x"]) / 2, (lms[i]["y"] + lms[j]["y"]) / 2)


def _angle_at(lms, a, b, c):
    """Angle at point b (degrees) formed by segments b->a and b->c."""
    ax, ay = lms[a]["x"] - lms[b]["x"], lms[a]["y"] - lms[b]["y"]
    cx, cy = lms[c]["x"] - lms[b]["x"], lms[c]["y"] - lms[b]["y"]
    dot = ax * cx + ay * cy
    na, nc = math.hypot(ax, ay), math.hypot(cx, cy)
    if na == 0 or nc == 0:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, dot / (na * nc)))))


def _pixel_height(lms):
    """Nose to mid-ankle distance, our body-scale unit (normalized coords)."""
    ankle_mid = _mid(lms, L_ANKLE, R_ANKLE)
    return math.hypot(lms[NOSE]["x"] - ankle_mid[0], lms[NOSE]["y"] - ankle_mid[1])


def _turn_estimate(width_now, width_ref):
    """Foreshortening-based rotation estimate: width shrinks with turn."""
    if width_ref <= 1e-6:
        return None
    ratio = max(-1.0, min(1.0, width_now / width_ref))
    return math.degrees(math.acos(ratio))


def _metric(value, unit, label, benchmark, confidence="ok", note=None):
    m = {
        "value": None if value is None else round(value, 1),
        "unit": unit,
        "label": label,
        "benchmark": benchmark,
        "confidence": confidence,
    }
    if note:
        m["note"] = note
    if value is None:
        m["confidence"] = "low"
        m["note"] = note or "Landmarks not visible enough to measure this."
    return m


def compute_metrics(landmarks, key_positions, fps, swing_type="full"):
    """landmarks: per-frame list (None where no pose detected).
    key_positions: {"p1": frame, "p4": frame, "p7": frame, "p10": frame}.
    Returns {"metrics": {...}, "notes": [...]}"""

    p1, p4 = key_positions["p1"], key_positions["p4"]
    p7, p10 = key_positions["p7"], key_positions["p10"]
    out = {}
    notes = []

    # --- Tempo: pure frame arithmetic, works for every swing type ---
    backswing = (p4 - p1) / fps
    downswing = (p7 - p4) / fps
    out["tempo_ratio"] = _metric(
        backswing / downswing if downswing > 0 else None,
        ":1", "Tempo ratio (backswing : downswing)", "~3:1",
        note=f"Backswing {backswing:.2f}s, downswing {downswing:.2f}s.",
    )

    if swing_type != "full":
        notes.append("Short-game metric suite coming soon — tempo only for now.")
        return {"metrics": out, "notes": notes, "version": METRICS_VERSION}

    at = {}
    for name, frame in (("p1", p1), ("p4", p4), ("p7", p7), ("p10", p10)):
        at[name] = landmarks[frame] if frame < len(landmarks) else None
        if at[name] is None:
            notes.append(f"No pose detected on the {name.upper()} frame — some metrics unavailable.")

    # Target direction from where the hands finish (also tells us lead side)
    target_sign = None
    if at["p10"] and at["p1"] and _visible(at["p10"], [L_WRIST, R_WRIST, L_HIP, R_HIP]):
        wrist_mid_x = (at["p10"][L_WRIST]["x"] + at["p10"][R_WRIST]["x"]) / 2
        hip_mid_x = _mid(at["p10"], L_HIP, R_HIP)[0]
        target_sign = 1.0 if wrist_mid_x > hip_mid_x else -1.0

    def toward_target(dx):
        """Convert an image-x displacement to signed 'toward target' value."""
        if target_sign is None:
            return None
        return dx * target_sign

    # --- Shoulder & hip turn at the top (foreshortening estimate) ---
    for key, label, a, b, bench in (
        ("shoulder_turn_p4", "Shoulder turn at top (est.)", L_SHOULDER, R_SHOULDER, "~90°"),
        ("hip_turn_p4", "Hip turn at top (est.)", L_HIP, R_HIP, "~45°"),
    ):
        value, conf = None, "low"
        if at["p1"] and at["p4"] and _visible(at["p1"], [a, b]) and _visible(at["p4"], [a, b]):
            w1 = abs(at["p1"][a]["x"] - at["p1"][b]["x"])
            w4 = abs(at["p4"][a]["x"] - at["p4"][b]["x"])
            value = _turn_estimate(w4, w1)
            conf = "ok"
        out[key] = _metric(
            value, "°", label, bench, conf,
            note="Estimated from line foreshortening — 2D face-on limit.",
        )

    # --- Spine tilt (side bend): mid-hip -> mid-shoulder vs vertical ---
    def spine_tilt(lms):
        if lms is None or not _visible(lms, [L_SHOULDER, R_SHOULDER, L_HIP, R_HIP]):
            return None
        sx, sy = _mid(lms, L_SHOULDER, R_SHOULDER)
        hx, hy = _mid(lms, L_HIP, R_HIP)
        # angle from vertical; sign = shoulders leaning away from target
        tilt = math.degrees(math.atan2(sx - hx, hy - sy))
        away = toward_target(-math.sin(math.radians(tilt)))
        signed = abs(tilt) if (away is None or away >= 0) else -abs(tilt)
        return signed

    tilt1, tilt7 = spine_tilt(at["p1"]), spine_tilt(at["p7"])
    out["spine_tilt_address"] = _metric(
        tilt1, "°", "Spine tilt at address (side bend)", "5–10° away from target (driver)",
        note="Positive = leaning away from target.",
    )
    out["spine_tilt_impact"] = _metric(
        tilt7, "°", "Spine tilt at impact (side bend)", "more than address",
        note="Positive = leaning away from target.",
    )

    # --- Head sway: nose x drift, address -> impact, % of pixel height ---
    value = None
    if at["p1"] and at["p7"] and _visible(at["p1"], [NOSE, L_ANKLE, R_ANKLE]) and _visible(at["p7"], [NOSE]):
        height = _pixel_height(at["p1"])
        if height > 1e-6:
            drift = toward_target(at["p7"][NOSE]["x"] - at["p1"][NOSE]["x"])
            if drift is not None:
                value = 100.0 * drift / height
    out["head_sway"] = _metric(
        value, "% of height", "Head sway, address → impact", "small (under ~5%)",
        note="Positive = toward target.",
    )

    # --- Lead arm angle at the top (left arm; assumes right-handed) ---
    value, conf = None, "low"
    if at["p4"] and _visible(at["p4"], [L_SHOULDER, L_ELBOW, L_WRIST]):
        value = _angle_at(at["p4"], L_SHOULDER, L_ELBOW, L_WRIST)
        conf = "ok"
    out["lead_arm_angle_p4"] = _metric(
        value, "°", "Lead arm angle at top", "close to 180° (straight)", conf,
        note="Left arm — assumes a right-handed golfer.",
    )

    # --- Hip slide: mid-hip x drift, address -> impact ---
    value = None
    if at["p1"] and at["p7"] and _visible(at["p1"], [L_HIP, R_HIP, L_ANKLE, R_ANKLE]) and _visible(at["p7"], [L_HIP, R_HIP]):
        height = _pixel_height(at["p1"])
        if height > 1e-6:
            drift = toward_target(_mid(at["p7"], L_HIP, R_HIP)[0] - _mid(at["p1"], L_HIP, R_HIP)[0])
            if drift is not None:
                value = 100.0 * drift / height
    out["hip_slide"] = _metric(
        value, "% of height", "Hip slide, address → impact", "a little toward target",
        note="Positive = toward target. A rough sequence proxy, not a pressure plate.",
    )

    if target_sign is None:
        notes.append("Could not infer target direction from the finish — direction signs unavailable.")

    return {"metrics": out, "notes": notes, "version": METRICS_VERSION}
