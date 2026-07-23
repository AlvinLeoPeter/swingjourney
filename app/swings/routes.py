import uuid
from datetime import date

from flask import (
    Blueprint, flash, jsonify, redirect, render_template, request,
    send_from_directory, url_for,
)
from flask_login import current_user, login_required

from .. import db, tasks
from ..config import DERIVED_DIR, UPLOAD_DIR
from ..models import CLUBS, SWING_TYPES, Session, Swing

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
