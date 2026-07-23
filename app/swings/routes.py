import json
import uuid
from datetime import date

from flask import (
    Blueprint, flash, jsonify, redirect, render_template, request,
    send_from_directory, url_for,
)
from flask_login import current_user, login_required

from .. import db, tasks
from ..config import DERIVED_DIR, UPLOAD_DIR
from ..models import CLUBS, SWING_TYPES, Analysis, Session, Swing

# The four key swing positions, in required chronological order
POSITIONS = [
    ("p1", "Address"),
    ("p4", "Top of backswing"),
    ("p7", "Impact"),
    ("p10", "Finish"),
]

bp = Blueprint("swings", __name__, url_prefix="/swings")

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm"}


@bp.route("/")
@login_required
def list_swings():
    swings = (
        Swing.query.join(Session)
        .filter(Session.user_id == current_user.id)
        .order_by(Swing.created_at.desc())
        .all()
    )
    return render_template("swings/list.html", swings=swings)


@bp.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    if request.method == "POST":
        file = request.files.get("video")
        if not file or not file.filename:
            flash("Pick a video file first.")
            return redirect(url_for("swings.upload"))

        ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_EXTENSIONS:
            flash("Only MP4, MOV or WEBM videos are supported.")
            return redirect(url_for("swings.upload"))

        swing_type = request.form.get("swing_type", "full")
        club = request.form.get("club", "7i")

        # MVP: one session per calendar day per user (range mode will
        # create its own explicit sessions later).
        session = (
            Session.query.filter_by(user_id=current_user.id, date=date.today(), mode="upload")
            .first()
        )
        if session is None:
            session = Session(
                user_id=current_user.id,
                date=date.today(),
                swing_type=swing_type,
                club=club,
                mode="upload",
            )
            db.session.add(session)
            db.session.flush()  # get session.id before commit

        filename = f"{uuid.uuid4().hex}{ext}"
        file.save(UPLOAD_DIR / filename)

        swing = Swing(
            session_id=session.id,
            video_path=filename,
            swing_type=swing_type,
            club=club,
            status="queued",
        )
        db.session.add(swing)
        db.session.commit()
        tasks.enqueue(swing.id)

        flash("Swing uploaded.")
        return redirect(url_for("swings.detail", swing_id=swing.id))

    return render_template(
        "swings/upload.html", swing_types=SWING_TYPES, clubs=CLUBS
    )


@bp.route("/<int:swing_id>")
@login_required
def detail(swing_id):
    swing = _get_own_swing(swing_id)
    return render_template("swings/detail.html", swing=swing)


@bp.route("/video/<path:filename>")
@login_required
def video(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@bp.route("/<int:swing_id>/overlay/<int:n>")
@login_required
def overlay_frame(swing_id, n):
    _get_own_swing(swing_id)
    return send_from_directory(
        DERIVED_DIR / str(swing_id) / "overlays", f"overlay_{n:04d}.jpg"
    )


@bp.route("/<int:swing_id>/status")
@login_required
def status(swing_id):
    swing = _get_own_swing(swing_id)
    return jsonify(
        status=swing.status, frame_count=swing.frame_count, error=swing.error
    )


@bp.route("/<int:swing_id>/tag", methods=["GET", "POST"])
@login_required
def tag(swing_id):
    swing = _get_own_swing(swing_id)
    if swing.status != "ready" or not swing.frame_count:
        flash("This swing isn't processed yet.")
        return redirect(url_for("swings.detail", swing_id=swing.id))

    analysis = swing.latest_analysis
    if request.method == "POST":
        try:
            frames = {key: int(request.form[key]) for key, _ in POSITIONS}
        except (KeyError, ValueError):
            flash("Tag all four positions before saving.")
            return redirect(url_for("swings.tag", swing_id=swing.id))

        ordered = [frames[key] for key, _ in POSITIONS]
        if ordered != sorted(ordered) or len(set(ordered)) != 4:
            flash("Positions must be in order: Address < Top < Impact < Finish.")
            return redirect(url_for("swings.tag", swing_id=swing.id))
        if ordered[0] < 0 or ordered[-1] >= swing.frame_count:
            flash("A tagged frame is outside the video.")
            return redirect(url_for("swings.tag", swing_id=swing.id))

        if analysis is None:
            analysis = Analysis(swing_id=swing.id)
            db.session.add(analysis)
        analysis.key_positions = {**frames, "method": "manual", "confidence": 1.0}

        # Metrics are pure math over already-extracted landmarks — instant.
        from ..analysis.metrics import METRICS_VERSION, compute_metrics

        with open(DERIVED_DIR / str(swing.id) / "landmarks.json") as fh:
            data = json.load(fh)
        result = compute_metrics(
            data["landmarks"], frames, fps=swing.fps, swing_type=swing.swing_type
        )
        analysis.metrics = {"metrics": result["metrics"], "notes": result["notes"]}
        analysis.quality = data["quality"]
        analysis.model_version = METRICS_VERSION
        db.session.commit()
        flash("Key positions saved — metrics computed.")
        return redirect(url_for("swings.detail", swing_id=swing.id))

    existing = (analysis.key_positions or {}) if analysis else {}
    return render_template(
        "swings/tag.html", swing=swing, positions=POSITIONS, existing=existing
    )


@bp.route("/<int:swing_id>/reprocess", methods=["POST"])
@login_required
def reprocess(swing_id):
    swing = _get_own_swing(swing_id)
    swing.status = "queued"
    swing.error = None
    db.session.commit()
    tasks.enqueue(swing.id)
    return redirect(url_for("swings.detail", swing_id=swing.id))


def _get_own_swing(swing_id) -> Swing:
    return (
        Swing.query.join(Session)
        .filter(Swing.id == swing_id, Session.user_id == current_user.id)
        .first_or_404()
    )
