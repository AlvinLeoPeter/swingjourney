from dotenv import load_dotenv

load_dotenv()  # read .env before anything touches os.environ

from flask import Flask, redirect, url_for
from flask_login import LoginManager, current_user
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
login_manager = LoginManager()


def create_app():
    from .config import Config, DERIVED_DIR, INSTANCE_DIR, UPLOAD_DIR

    INSTANCE_DIR.mkdir(exist_ok=True)
    UPLOAD_DIR.mkdir(exist_ok=True)
    DERIVED_DIR.mkdir(exist_ok=True)

    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    from . import models  # noqa: F401  (register models before create_all)

    from .auth.routes import bp as auth_bp
    from .swings.routes import bp as swings_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(swings_bp)

    @app.route("/")
    def index():
        if current_user.is_authenticated:
            return redirect(url_for("swings.list_swings"))
        return redirect(url_for("auth.login"))

    with app.app_context():
        db.create_all()

    # Start the background worker + re-queue unfinished swings. Guard against
    # the Flask debug reloader's watcher process starting a second worker.
    import os

    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not app.debug:
        from . import tasks

        tasks.init_app(app)

    return app


@login_manager.user_loader
def load_user(user_id):
    from .models import User

    return db.session.get(User, int(user_id))
