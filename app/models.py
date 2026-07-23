from datetime import datetime, date

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from . import db

# Values the UI offers; stored as plain strings so adding one later is trivial.
SWING_TYPES = ["full", "pitch", "chip", "putt"]
CLUBS = [
    "Driver", "3W", "5W", "Hybrid",
    "3i", "4i", "5i", "6i", "7i", "8i", "9i",
    "PW", "GW", "SW", "LW", "Putter",
]


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="player")  # "coach" in Phase 2
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    sessions = db.relationship("Session", back_populates="user", lazy="dynamic")

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


class Session(db.Model):
    """A practice session: one trip to the range / one filming block."""

    __tablename__ = "sessions"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    swing_type = db.Column(db.String(20), nullable=False, default="full")
    club = db.Column(db.String(20), nullable=False, default="7i")
    notes = db.Column(db.Text, nullable=True)
    mode = db.Column(db.String(20), nullable=False, default="upload")  # "upload" | "range"
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    user = db.relationship("User", back_populates="sessions")
    swings = db.relationship("Swing", back_populates="session", lazy="dynamic")


class Swing(db.Model):
    __tablename__ = "swings"

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("sessions.id"), nullable=False)
    video_path = db.Column(db.String(500), nullable=False)  # relative to instance/uploads
    camera_angle = db.Column(db.String(20), nullable=False, default="face-on")
    # Copied from the session at upload so a swing survives session edits;
    # overridable per-swing on regular uploads.
    swing_type = db.Column(db.String(20), nullable=False, default="full")
    club = db.Column(db.String(20), nullable=False, default="7i")
    status = db.Column(db.String(20), nullable=False, default="queued")
    # queued -> processing -> ready | failed
    error = db.Column(db.Text, nullable=True)
    fps = db.Column(db.Float, nullable=True)
    duration_s = db.Column(db.Float, nullable=True)
    frame_count = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    session = db.relationship("Session", back_populates="swings")
    analyses = db.relationship("Analysis", back_populates="swing", lazy="dynamic")

    @property
    def latest_analysis(self):
        return self.analyses.order_by(Analysis.created_at.desc()).first()


class Analysis(db.Model):
    """One analysis run over a swing. Separate table so we can re-analyze
    old videos with a better pipeline without losing history."""

    __tablename__ = "analyses"

    id = db.Column(db.Integer, primary_key=True)
    swing_id = db.Column(db.Integer, db.ForeignKey("swings.id"), nullable=False)
    # {"p1": frame, "p4": frame, "p7": frame, "p10": frame,
    #  "method": "manual"|"auto", "confidence": 0..1}
    key_positions = db.Column(db.JSON, nullable=True)
    # {"tempo_ratio": {"value": 2.8, "unit": ":1"}, ...}
    metrics = db.Column(db.JSON, nullable=True)
    # landmark-visibility summary that drives the honesty indicator
    quality = db.Column(db.JSON, nullable=True)
    # {"strengths": [...], "fixes": [{"issue":..., "drill":...}], "one_liner": ...}
    coaching = db.Column(db.JSON, nullable=True)
    model_version = db.Column(db.String(50), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    swing = db.relationship("Swing", back_populates="analyses")
