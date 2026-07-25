"""Orchestration helpers that connect the pure analysis package to the DB."""

import json

from . import db
from .analysis.metrics import METRICS_VERSION, compute_metrics
from .config import DERIVED_DIR
from .models import Analysis, Swing


def load_landmarks(swing_id: int) -> dict:
    with open(DERIVED_DIR / str(swing_id) / "landmarks.json") as fh:
        return json.load(fh)


def apply_key_positions(swing: Swing, frames: dict, method: str, confidence: float) -> Analysis:
    """Store key positions on the swing's analysis and recompute metrics.
    Caller commits."""
    analysis = swing.latest_analysis
    if analysis is None:
        analysis = Analysis(swing_id=swing.id)
        db.session.add(analysis)

    analysis.key_positions = {**frames, "method": method, "confidence": confidence}

    data = load_landmarks(swing.id)
    result = compute_metrics(
        data["landmarks"], frames, fps=swing.fps, swing_type=swing.swing_type
    )
    analysis.metrics = {"metrics": result["metrics"], "notes": result["notes"]}
    analysis.quality = data["quality"]
    analysis.model_version = METRICS_VERSION

    # Annotated key-frame images (skeleton + arcs + labels)
    from .analysis.annotate import render_key_frames

    swing_dir = DERIVED_DIR / str(swing.id)
    render_key_frames(
        swing_dir / "frames",
        data["landmarks"],
        frames,
        result["metrics"],
        swing_dir / "keyframes",
    )
    return analysis


def generate_coaching_for(swing: Swing) -> bool:
    """Call Claude with the analysis metrics; store notes on the analysis.
    Returns False when the swing isn't eligible. Caller commits."""
    from .analysis.coach import generate_coaching

    analysis = swing.latest_analysis
    if (
        analysis is None
        or not analysis.metrics
        or swing.swing_type != "full"
    ):
        return False

    try:
        analysis.coaching = generate_coaching(
            metrics=analysis.metrics["metrics"],
            swing_meta={
                "club": swing.club,
                "swing_type": swing.swing_type,
                "date": swing.created_at.date().isoformat(),
                "camera_angle": swing.camera_angle,
            },
            quality=analysis.quality or {},
        )
    except Exception as exc:
        analysis.coaching = {"error": str(exc)}
    return True
