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

            swing.status = "ready"
            swing.error = None
        except Exception as exc:  # keep the row honest instead of crashing the worker
            _app.logger.exception("processing swing %s failed", swing_id)
            swing.status = "failed"
            swing.error = str(exc)
        db.session.commit()
