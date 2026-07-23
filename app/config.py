import os
from pathlib import Path

# instance/ holds everything that isn't code: the sqlite db and uploaded videos.
# On Railway we'll mount a persistent volume here.
INSTANCE_DIR = Path(__file__).resolve().parent.parent / "instance"
UPLOAD_DIR = INSTANCE_DIR / "uploads"
DERIVED_DIR = INSTANCE_DIR / "derived"  # per-swing frames/overlays/landmarks
POSE_MODEL_PATH = INSTANCE_DIR / "models" / "pose_landmarker_full.task"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret")
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{INSTANCE_DIR / 'swingjourney.db'}"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 200 * 1024 * 1024  # 200 MB upload cap
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
