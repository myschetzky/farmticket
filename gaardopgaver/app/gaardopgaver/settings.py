"""Indstillinger (administratorer): valg af kalender, som planlagte tider synkroniseres til."""

import os

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from . import db
from .auth import admin_required
from .calendar_sync import SETTING_CALENDAR, HAClient, HAError, get_setting, get_status, list_calendars, set_setting

bp = Blueprint("settings", __name__)


def _client():
    factory = current_app.config.get("HA_CLIENT_FACTORY")
    if factory:
        return factory()
    token = os.environ.get("SUPERVISOR_TOKEN")
    return HAClient(token) if token else None


def _notify_sync():
    publisher = current_app.extensions.get("ha_publisher")
    if publisher:
        publisher.notify_change()


@bp.route("/indstillinger", methods=["GET", "POST"])
@admin_required
def settings():
    conn = db.get_db()
    client = _client() if current_app.config["HA_MODE"] else None
    calendars, error = [], None
    if client:
        try:
            calendars = list_calendars(client)
        except HAError as exc:
            error = str(exc)

    if request.method == "POST":
        if request.form.get("action") == "sync_now":
            _notify_sync()
            flash("Synkroniseringen er sat i gang. Genindlæs siden om lidt for at se status.", "success")
        else:
            choice = request.form.get("calendar", "")
            allowed = {c["entity_id"] for c in calendars if c["can_sync"]}
            if choice and choice not in allowed:
                flash("Den valgte kalender kan ikke bruges.", "error")
            else:
                set_setting(conn, SETTING_CALENDAR, choice)
                _notify_sync()
                if choice:
                    name = next(c["name"] for c in calendars if c["entity_id"] == choice)
                    flash(f"Planlagte tider lægges nu i kalenderen ‘{name}’.", "success")
                else:
                    flash("Kalendersynkronisering er slået fra. Gårdopgavers begivenheder fjernes fra kalenderen.",
                          "success")
        return redirect(url_for("settings.settings"))

    return render_template(
        "settings.html",
        available=client is not None,
        calendars=calendars,
        error=error,
        current=get_setting(conn, SETTING_CALENDAR, ""),
        status=get_status(conn),
    )
