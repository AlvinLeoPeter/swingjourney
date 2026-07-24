"""Auto-detection tests on a synthetic wrist trajectory shaped like a swing."""

from app.analysis.positions import detect_positions

FPS = 60.0


def frame_with_wrists(x, y):
    lm = [{"x": 0.5, "y": 0.5, "z": 0.0, "v": 1.0} for _ in range(33)]
    lm[15] = {"x": x, "y": y, "z": 0.0, "v": 1.0}
    lm[16] = {"x": x, "y": y, "z": 0.0, "v": 1.0}
    return lm


def synthetic_swing():
    """Address still (0-59), backswing up (60-119), pause at top (120-125),
    downswing fast (126-140), impact bottom (140), follow-through (141-180),
    still finish (181-239)."""
    frames = []
    for _ in range(60):                    # address: hands still, low
        frames.append(frame_with_wrists(0.50, 0.60))
    for i in range(60):                    # backswing: rise to top over 1s
        t = (i + 1) / 60
        frames.append(frame_with_wrists(0.50 - 0.15 * t, 0.60 - 0.35 * t))
    for _ in range(6):                     # brief pause at the top
        frames.append(frame_with_wrists(0.35, 0.25))
    for i in range(15):                    # downswing: fast drop over 0.25s
        t = (i + 1) / 15
        frames.append(frame_with_wrists(0.35 + 0.15 * t, 0.25 + 0.37 * t))
    for i in range(40):                    # follow-through: decelerating rise
        t = (i + 1) / 40
        frames.append(frame_with_wrists(0.50 + 0.20 * t, 0.62 - 0.40 * t))
    for _ in range(59):                    # finish: hands still, high
        frames.append(frame_with_wrists(0.70, 0.22))
    return frames


def test_detects_swing_shape():
    result = detect_positions(synthetic_swing(), FPS)
    assert result is not None
    # Address ends at ~59, top ~120-126, impact ~140, finish ~181
    assert 40 <= result["p1"] <= 65
    assert 115 <= result["p4"] <= 130
    assert 135 <= result["p7"] <= 145
    assert 175 <= result["p10"] <= 200
    assert result["confidence"] >= 0.8


def test_too_short_video_returns_none():
    assert detect_positions(synthetic_swing()[:30], FPS) is None


def test_no_movement_returns_none():
    still = [frame_with_wrists(0.5, 0.6) for _ in range(240)]
    assert detect_positions(still, FPS) is None


def test_missing_frames_lower_confidence():
    swing = synthetic_swing()
    for i in range(60, 120, 3):  # drop a third of backswing frames
        swing[i] = None
    result = detect_positions(swing, FPS)
    if result is not None:
        full = detect_positions(synthetic_swing(), FPS)
        assert result["confidence"] <= full["confidence"]
