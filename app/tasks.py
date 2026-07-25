"""In-process background queue.

Decision: ThreadPoolExecutor instead of Celery/Redis — zero extra infra,
fine for a single user. Trade-off: jobs die if the process restarts, so
init_app() re-queues anything left in "queued"/"processing" at startup.
Deployment rule this imposes: run gunicorn with exactly 1 worker.
"""

from concurrent.futures import ThreadPoolExecutor

from . import db
from .config import DERIVED_DIR, POSE_MODEL_PATH, UPLOAD_DIR

executor = ThreadPoolExecutor(max_workers=1)
_app = None


def init_app(app):
    global _app
    _app = app
    with app.app_context():
        from .models import Swing

        for swing in Swing.query.filter(Swing.status.in_(["queued", "processing"])).all():
            swing.status = "queued"
            executor.submit(process_swing, swing.id)
        db.session.commit()


def enqueue(swing_id: int):
    executor.submit(process_swing, swing_id)


def process_swing(swing_id: int):
    from .models import Swing

    with _app.app_context():
        swing = db.session.get(Swing, swing_id)
        if swing is None:
            return
        swing.status = "processing"
        db.session.commit()

        try:
            # imports live inside the try so a broken dependency marks the
            # swing "failed" instead of vanishing into the executor
            from .analysis.frames import extract_frames
            from .analysis.pose import run_pose

            swing_dir = DERIVED_DIR / str(swing.id)
            info = extract_frames(UPLOAD_DIR / swing.video_path, swing_dir / "frames")
            swing.fps = info["fps"]
            swing.frame_count = info["frame_count"]
            swing.duration_s = info["duration_s"]
            db.session.commit()

            run_pose(
                swing_dir / "frames",
                swing_dir / "overlays",
                swing_dir / "landmarks.json",
                fps=info["fps"],
                model_path=POSE_MODEL_PATH,
            )

            _auto_detect(swing, swing_dir)

            swing.status = "ready"
            swing.error = None
        except Exception as exc:  # keep the row honest instead of crashing the worker
            _app.logger.exception("processing swing %s failed", swing_id)
            swing.status = "failed"
            swing.error = str(exc)
        db.session.commit()


def _auto_detect(swing, swing_dir):
    """Try automatic key-position detection. High confidence -> full analysis
    with metrics, no tagging needed. Low confidence -> stash the guesses so
    the manual tag UI can prefill them. Never touches manual tags."""
    import json

    from .analysis.positions import AUTO_CONFIDENCE_MIN, detect_positions
    from .services import apply_key_positions

    landmarks_path = swing_dir / "landmarks.json"
    with open(landmarks_path) as fh:
        data = json.load(fh)

    result = detect_positions(data["landmarks"], fps=swing.fps)
    if result is None:
        return

    data["auto_positions"] = result
    with open(landmarks_path, "w") as fh:
        json.dump(data, fh)

    existing = swing.latest_analysis
    if existing and existing.key_positions and existing.key_positions.get("method") == "manual":
        return  # a human's tags outrank the robot's

    if result["confidence"] >= AUTO_CONFIDENCE_MIN:
        from .services import generate_coaching_for

        frames = {k: result[k] for k in ("p1", "p4", "p7", "p10")}
        apply_key_positions(swing, frames, method="auto", confidence=result["confidence"])
        db.session.commit()  # metrics visible even if the API call below is slow
        generate_coaching_for(swing)


def enqueue_coaching(swing_id: int):
    executor.submit(_coaching_job, swing_id)


def _coaching_job(swing_id: int):
    from .models import Swing
    from .services import generate_coaching_for

    with _app.app_context():
        swing = db.session.get(Swing, swing_id)
        if swing is not None:
            try:
                generate_coaching_for(swing)
            except Exception:
                _app.logger.exception("coaching for swing %s failed", swing_id)
            db.session.commit()
