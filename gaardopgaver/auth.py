"""Login, første opsætning, brugeradministration og profil."""

import secrets
from functools import wraps

import click
from flask.cli import with_appcontext
from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .dates import now_str

bp = Blueprint("auth", __name__)

MIN_PASSWORD_LENGTH = 6


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user or not g.user["is_admin"]:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def safe_target(target, default):
    """Brug kun interne stier som omdirigeringsmål."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return default


def create_user(username, name, password, is_admin=False) -> int:
    return db.execute(
        "INSERT INTO users (username, name, password_hash, is_admin, ical_token, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            username.strip(),
            name.strip(),
            generate_password_hash(password),
            1 if is_admin else 0,
            secrets.token_urlsafe(24),
            now_str(),
        ),
    )


def _validate_new_user(form, require_password=True):
    errors = []
    username = form.get("username", "").strip()
    name = form.get("name", "").strip()
    password = form.get("password", "")
    if not username:
        errors.append("Brugernavn skal udfyldes.")
    elif " " in username:
        errors.append("Brugernavn må ikke indeholde mellemrum.")
    elif db.query("SELECT 1 FROM users WHERE username = ?", (username,), one=True):
        errors.append("Brugernavnet er allerede i brug.")
    if not name:
        errors.append("Navn skal udfyldes.")
    if require_password or password:
        errors.extend(_password_errors(password, form.get("password2", "")))
    return errors


def _password_errors(password, password2):
    if len(password) < MIN_PASSWORD_LENGTH:
        return [f"Adgangskoden skal være mindst {MIN_PASSWORD_LENGTH} tegn."]
    if password != password2:
        return ["De to adgangskoder er ikke ens."]
    return []


def _log_in(user_id):
    session.clear()
    session.permanent = True
    session["user_id"] = user_id


@bp.route("/opsaetning", methods=["GET", "POST"])
def setup():
    """Første start: opret den første bruger (administrator)."""
    if db.has_users():
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        errors = _validate_new_user(request.form)
        if not errors:
            user_id = create_user(
                request.form["username"], request.form["name"], request.form["password"], is_admin=True
            )
            if request.form.get("examples"):
                from .tickets import create_example_tickets

                create_example_tickets(user_id)
            _log_in(user_id)
            flash("Velkommen! Systemet er klar. Opret flere brugere under ‘Brugere’.", "success")
            return redirect(url_for("tickets.dashboard"))
        for e in errors:
            flash(e, "error")
    return render_template("setup.html", form=request.form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if not db.has_users():
        return redirect(url_for("auth.setup"))
    if request.method == "POST":
        user = db.query(
            "SELECT * FROM users WHERE username = ? AND active = 1",
            (request.form.get("username", "").strip(),),
            one=True,
        )
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            _log_in(user["id"])
            return redirect(safe_target(request.args.get("next"), url_for("tickets.dashboard")))
        flash("Forkert brugernavn eller adgangskode.", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))


@bp.route("/profil", methods=["GET", "POST"])
def profile():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "password":
            if not check_password_hash(g.user["password_hash"], request.form.get("current", "")):
                flash("Den nuværende adgangskode er forkert.", "error")
            else:
                errors = _password_errors(request.form.get("password", ""), request.form.get("password2", ""))
                if errors:
                    for e in errors:
                        flash(e, "error")
                else:
                    db.execute(
                        "UPDATE users SET password_hash = ? WHERE id = ?",
                        (generate_password_hash(request.form["password"]), g.user["id"]),
                    )
                    flash("Adgangskoden er ændret.", "success")
        elif action == "new_token":
            db.execute(
                "UPDATE users SET ical_token = ? WHERE id = ?", (secrets.token_urlsafe(24), g.user["id"])
            )
            flash("Nyt kalender-link oprettet. Det gamle link virker ikke længere.", "success")
        return redirect(url_for("auth.profile"))
    return render_template("profile.html")


@bp.route("/brugere")
@admin_required
def users():
    rows = db.query("SELECT * FROM users ORDER BY active DESC, name")
    return render_template("users.html", users=rows)


@bp.route("/brugere/ny", methods=["GET", "POST"])
@admin_required
def user_new():
    if request.method == "POST":
        errors = _validate_new_user(request.form)
        if not errors:
            create_user(
                request.form["username"],
                request.form["name"],
                request.form["password"],
                is_admin=bool(request.form.get("is_admin")),
            )
            flash(f"Brugeren {request.form['name'].strip()} er oprettet.", "success")
            return redirect(url_for("auth.users"))
        for e in errors:
            flash(e, "error")
    return render_template("user_form.html", user=None, form=request.form)


@bp.route("/brugere/<int:user_id>", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    user = db.query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if user is None:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        is_admin = 1 if request.form.get("is_admin") else 0
        active = 1 if request.form.get("active") else 0
        errors = []
        if not name:
            errors.append("Navn skal udfyldes.")
        if user_id == g.user["id"] and (not is_admin or not active):
            errors.append("Du kan ikke fjerne dine egne administratorrettigheder eller deaktivere dig selv.")
        password = request.form.get("password", "")
        if password:
            errors.extend(_password_errors(password, request.form.get("password2", "")))
        if not errors:
            db.execute(
                "UPDATE users SET name = ?, is_admin = ?, active = ? WHERE id = ?",
                (name, is_admin, active, user_id),
            )
            if password:
                db.execute(
                    "UPDATE users SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(password), user_id),
                )
            flash("Brugeren er gemt.", "success")
            return redirect(url_for("auth.users"))
        for e in errors:
            flash(e, "error")
    return render_template("user_form.html", user=user, form=request.form)


@click.command("nulstil-kode")
@with_appcontext
@click.argument("username")
@click.password_option("--kode", prompt="Ny adgangskode")
def reset_password_command(username, kode):
    """Sæt en ny adgangskode for en bruger (hvis man er låst ude)."""
    user = db.query("SELECT id FROM users WHERE username = ?", (username,), one=True)
    if user is None:
        raise click.ClickException(f"Ingen bruger med brugernavnet '{username}'.")
    db.execute(
        "UPDATE users SET password_hash = ?, active = 1 WHERE id = ?",
        (generate_password_hash(kode), user["id"]),
    )
    click.echo(f"Adgangskoden for {username} er ændret.")
