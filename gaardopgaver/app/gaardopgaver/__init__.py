"""Gårdopgaver – et lille ticket-system til landejendommen."""

import os
import secrets
from pathlib import Path

from flask import Flask, abort, g, redirect, render_template, request, session, url_for

from . import auth, db, ha, schedule, settings, tickets
from .constants import CATEGORIES, PRIORITIES, STATUS_LABELS
from .dates import fmt_date, fmt_datetime, fmt_hours, fmt_time

# Endpoints der kan nås uden at være logget ind.
PUBLIC_ENDPOINTS = {"static", "auth.login", "auth.setup", "schedule.ical_feed"}


def create_app(test_config=None):
    app = Flask(__name__)

    data_dir = Path(os.environ.get("GAARD_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
    app.config.from_mapping(
        DATA_DIR=str(data_dir),
        DATABASE=str(data_dir / "gaard.db"),
        CSRF_ENABLED=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 90,  # forbliv logget ind i 90 dage
        # Sat af Home Assistant-appen (se Dockerfile): ingress, automatisk login og sensorer.
        HA_MODE=os.environ.get("GAARD_HA") == "1",
        HA_PORT=int(os.environ.get("GAARD_PORT", "8099")),
    )
    if test_config:
        app.config.update(test_config)

    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY"] = (
        os.environ.get("GAARD_SECRET_KEY")
        or app.config.get("SECRET_KEY")
        or _load_or_create_secret(Path(app.config["DATA_DIR"]) / "secret_key")
    )

    db.init_app(app)
    with app.app_context():
        db.init_db()

    app.register_blueprint(auth.bp)
    app.register_blueprint(tickets.bp)
    app.register_blueprint(schedule.bp)
    app.register_blueprint(settings.bp)
    app.cli.add_command(auth.reset_password_command)
    if app.config["HA_MODE"]:
        ha.init_app(app)

    app.jinja_env.filters.update(
        dato=fmt_date, dato_tid=fmt_datetime, tid=fmt_time, timer=fmt_hours
    )
    app.jinja_env.globals.update(
        PRIORITIES=PRIORITIES,
        STATUS_LABELS=STATUS_LABELS,
        CATEGORIES=CATEGORIES,
        HA_MODE=app.config["HA_MODE"],
        csrf_token=_csrf_token,
    )

    errors = {
        400: ("Ugyldig forespørgsel", "Noget i forespørgslen var forkert."),
        403: ("Ingen adgang", "Du har ikke rettighed til at gøre dette."),
        404: ("Ikke fundet", "Siden eller opgaven findes ikke (længere)."),
    }
    for code, (title, message) in errors.items():
        app.register_error_handler(code, _error_handler(code, title, message))

    @app.before_request
    def load_user_and_guard():
        g.user = None
        user_id = session.get("user_id")
        if user_id is not None:
            g.user = db.query(
                "SELECT * FROM users WHERE id = ? AND active = 1", (user_id,), one=True
            )
            if g.user is None:
                session.clear()
        if app.config["HA_MODE"]:
            ha.guard_request()

        if request.method == "POST" and app.config["CSRF_ENABLED"]:
            sent = request.form.get("csrf_token", "")
            if not sent or not secrets.compare_digest(sent, session.get("csrf_token", "")):
                abort(400, "Formularen er udløbet. Gå tilbage, genindlæs siden og prøv igen.")

        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if not db.has_users():
            return redirect(url_for("auth.setup"))
        if g.user is None:
            return redirect(url_for("auth.login", next=request.script_root + request.full_path))
        return None

    return app


def _error_handler(code, title, message):
    def handler(exc):
        # Brug fejlteksten fra abort(), hvis der er givet en (fx udløbet formular).
        custom = exc.description and exc.description != type(exc).description
        text = exc.description if custom else message
        return render_template("error.html", title=title, message=text), code

    return handler


def _csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def _load_or_create_secret(path: Path) -> str:
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_hex(32)
    path.write_text(key)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return key
