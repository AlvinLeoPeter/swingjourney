"""Automatic key-position detection from wrist-midpoint trajectory.

The idea, in golf terms:
- The fastest the hands ever move is mid-downswing. Find that moment first —
  it anchors everything else.
- Impact (P7): just after peak speed, the hands reach the bottom of the arc
  (max y — remember image y grows downward).
- Top (P4): in the window before peak speed, the hands are at their highest.
- Address (P1): scanning backward from the top, the last moment the hands
  were still for a sustained stretch.
- Finish (P10): after impact, the first moment the hands go still again.

Every guess is scored; below AUTO_CONFIDENCE_MIN the caller should fall back
to manual tagging (auto guesses still prefill the tag UI).
"""

L_WRIST, R_WRIST = 15, 16

AUTO_CONFIDENCE_MIN = 0.6
STILL_FRACTION = 0.06         # "still" = speed under 6% of peak
DETECTION_VERSION = "autodetect-v1"


def _wrist_track(landmarks):
    """Per-frame wrist midpoint; None where pose missing."""
    track = []
    for lms in landmarks:
        if lms is None:
            track.append(None)
        else:
            track.append((
                (lms[L_WRIST]["x"] + lms[R_WRIST]["x"]) / 2,
                (lms[L_WRIST]["y"] + lms[R_WRIST]["y"]) / 2,
            ))
    return track


def _speeds(track, fps):
    """Speed per frame (normalized units/s), smoothed over 5 frames."""
    raw = [0.0] * len(track)
    for i in range(1, len(track)):
        a, b = track[i - 1], track[i]
        raw[i] = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 * fps if a and b else 0.0
    smoothed = []
    for i in range(len(raw)):
        window = raw[max(0, i - 2): i + 3]
        smoothed.append(sum(window) / len(window))
    return smoothed


def _argext(values, indices, key):
    best = None
    for i in indices:
        if values[i] is not None and (best is None or key(values[i], values[best])):
            best = i
    return best


def _last_still_run(speed, still_thresh, start, stop, min_run):
    """Last frame index in [start, stop) that ends a still run of min_run frames,
    scanning backward. Returns None if the hands never settle."""
    run = 0
    for i in range(stop - 1, start - 1, -1):
        run = run + 1 if speed[i] < still_thresh else 0
        if run >= min_run:
            return i + run - 1
    return None


def detect_positions(landmarks, fps):
    n = len(landmarks)
    if n < int(fps):  # under a second of video: nothing to find
        return None

    track = _wrist_track(landmarks)
    speed = _speeds(track, fps)
    ys = [p[1] if p else None for p in track]

    peak = max(range(n), key=lambda i: speed[i])
    peak_speed = speed[peak]
    if peak_speed <= 0:
        return None
    still_thresh = peak_speed * STILL_FRACTION

    # Impact: bottom of arc shortly after peak speed
    p7 = _argext(ys, range(peak, min(n, peak + int(0.3 * fps) + 1)), lambda a, b: a > b)

    # Top: highest hands in the ~2s window before peak speed
    p4_lo = max(0, peak - int(2.0 * fps))
    p4 = _argext(ys, range(p4_lo, peak), lambda a, b: a < b)

    if p4 is None or p7 is None or not p4 < p7:
        return None

    # Address: last sustained stillness before the backswing
    p1 = _last_still_run(
        speed, still_thresh,
        max(0, p4 - int(3.0 * fps)), p4, min_run=max(2, int(0.15 * fps)),
    )
    if p1 is None:
        p1 = max(0, p4 - int(1.0 * fps))  # crude fallback: 1s before the top

    # Finish: first sustained stillness after impact
    p10 = None
    p10_fallback = False
    run = 0
    for i in range(min(p7 + int(0.2 * fps), n - 1), n):
        run = run + 1 if speed[i] < still_thresh * 2 else 0
        if run >= max(2, int(0.2 * fps)):
            p10 = i - run + 1
            break
    if p10 is None:
        # Golfer never settles (walks off) — use highest hands after impact
        p10_fallback = True
        p10 = _argext(
            ys, range(min(p7 + int(0.3 * fps), n - 1), min(n, p7 + int(2.5 * fps))),
            lambda a, b: a < b,
        )
        if p10 is None:
            p10 = n - 1

    frames = {"p1": p1, "p4": p4, "p7": p7, "p10": p10}

    # --- Confidence: golf-shaped sanity checks ---
    checks = []
    ordered = [frames[k] for k in ("p1", "p4", "p7", "p10")]
    checks.append(ordered == sorted(ordered) and len(set(ordered)) == 4)

    backswing = (p4 - p1) / fps
    downswing = (p7 - p4) / fps
    checks.append(0.4 <= backswing <= 2.5)
    checks.append(0.1 <= downswing <= 0.8)

    # hands at the top must be above address and impact
    if ys[p4] is not None and ys[p1] is not None and ys[p7] is not None:
        checks.append(ys[p4] < ys[p1] and ys[p4] < ys[p7])
    else:
        checks.append(False)

    window = [landmarks[i] is not None for i in range(p1, p10 + 1)]
    detection_rate = sum(window) / len(window)
    checks.append(detection_rate > 0.8)

    confidence = sum(checks) / len(checks) * detection_rate
    if p10_fallback:
        confidence *= 0.85
    return {**frames, "confidence": round(confidence, 2), "method": "auto"}
