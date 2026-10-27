"""Kalender: ugevisning, tidsblokke på opgaver og iCal-feed til telefonens kalender."""

from datetime import date, datetime, timedelta

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from . import db
from .auth import safe_target
from .constants import OPEN_STATUSES, PRIORITIES, STATUS_LABELS
from .dates import (
    DT_FORMAT, WEEKDAYS_SHORT, fmt_date, fmt_time, now_str, parse_date, parse_dt, week_start,
)
from .tickets import get_ticket, log_event, set_status

bp = Blueprint("schedule", __name__)

DAY_FIRST_HOUR = 6
DAY_LAST_HOUR = 22
DEFAULT_SLOT_HOURS = 2

SLOT_SELECT = """
SELECT s.*, t.title, t.priority, t.status, t.location, u.name AS user_name
  FROM time_slots s
  JOIN tickets t ON t.id = s.ticket_id
  LEFT JOIN users u ON u.id = s.user_id
"""


@bp.route("/kalender")
def week():
    day = parse_date(request.args.get("dato")) or date.today()
    start = week_start(day)
    end = start + timedelta(days=7)
    user_filter = request.args.get("bruger", "")

    sql = SLOT_SELECT + " WHERE s.starts_at < ? AND s.ends_at > ?"
    params = [end.isoformat(), start.isoformat()]
    if user_filter.isdigit():
        sql += " AND s.user_id = ?"
        params.append(int(user_filter))
    slots = db.query(sql + " ORDER BY s.starts_at", params)

    first_hour, last_hour = DAY_FIRST_HOUR, DAY_LAST_HOUR
    for s in slots:
        st, en = parse_dt(s["starts_at"]), parse_dt(s["ends_at"])
        first_hour = min(first_hour, st.hour)
        last_hour = max(last_hour, en.hour + (1 if en.minute else 0))

    days = []
    for i in range(7):
        d = start + timedelta(days=i)
        day_slots = [s for s in slots if s["starts_at"][:10] == d.isoformat()]
        days.append(
            {
                "date": d,
                "label": f"{WEEKDAYS_SHORT[d.weekday()]} {d.day}/{d.month}",
                "is_today": d == date.today(),
                "slots": day_slots,
                "blocks": _layout(day_slots, first_hour, last_hour),
                "hours": sum(_duration_hours(s) for s in day_slots),
            }
        )

    unplanned = db.query(
        """SELECT t.id, t.title, t.priority, t.estimate_hours, t.due_date FROM tickets t
            WHERE t.status IN ('ny', 'planlagt', 'i_gang')
              AND NOT EXISTS (SELECT 1 FROM time_slots s WHERE s.ticket_id = t.id AND s.ends_at >= ?)
            ORDER BY t.priority, t.due_date IS NULL, t.due_date, t.created_at""",
        (now_str(),),
    )
    iso_year, iso_week, _ = start.isocalendar()
    return render_template(
        "calendar_week.html",
        days=days,
        hours=list(range(first_hour, last_hour)),
        first_hour=first_hour,
        last_hour=last_hour,
        week_no=iso_week,
        week_year=iso_year,
        start=start,
        end=end - timedelta(days=1),
        prev_week=(start - timedelta(days=7)).isoformat(),
        next_week=(start + timedelta(days=7)).isoformat(),
        this_week=date.today().isoformat(),
        # Planlæg som standard i dag, eller fra mandag hvis man kigger på en senere uge.
        plan_date=max(start, date.today()).isoformat(),
        users=db.active_users(),
        user_filter=user_filter,
        unplanned=unplanned,
    )


def _duration_hours(slot):
    return (parse_dt(slot["ends_at"]) - parse_dt(slot["starts_at"])).total_seconds() / 3600


def _layout(slots, first_hour, last_hour):
    """Placér blokke lodret efter klokkeslæt og side om side, hvis de overlapper."""
    total = (last_hour - first_hour) * 60
    blocks = []
    for s in slots:
        st, en = parse_dt(s["starts_at"]), parse_dt(s["ends_at"])
        top = st.hour * 60 + st.minute - first_hour * 60
        length = max((en - st).total_seconds() / 60, 30)
        blocks.append({"slot": s, "start": st, "end": en, "top": top / total * 100,
                       "height": length / total * 100})

    cluster, columns, cluster_end = [], [], None

    def finish():
        for b in cluster:
            b["width"] = 100 / len(columns)
            b["left"] = b["col"] * b["width"]

    for b in blocks:
        if cluster_end is not None and b["start"] >= cluster_end:
            finish()
            cluster, columns, cluster_end = [], [], None
        for i, col_end in enumerate(columns):
            if col_end <= b["start"]:
                b["col"] = i
                columns[i] = b["end"]
                break
        else:
            b["col"] = len(columns)
            columns.append(b["end"])
        cluster.append(b)
        cluster_end = b["end"] if cluster_end is None else max(cluster_end, b["end"])
    finish()
    return blocks


def _schedulable_tickets(include_id=None):
    placeholders = ", ".join("?" for _ in OPEN_STATUSES)
    return db.query(
        f"SELECT id, title, priority FROM tickets WHERE status IN ({placeholders}) OR id = ?"
        " ORDER BY priority, title",
        (*OPEN_STATUSES, include_id or 0),
    )


def _parse_slot_form(form):
    errors = []
    ticket_id = form.get("ticket_id", "")
    ticket = None
    if ticket_id.isdigit():
        ticket = db.query("SELECT * FROM tickets WHERE id = ?", (int(ticket_id),), one=True)
    if ticket is None:
        errors.append("Vælg en opgave.")

    day = parse_date(form.get("date"))
    start = end = None
    if day is None:
        errors.append("Vælg en dato.")
    else:
        try:
            start = datetime.combine(day, datetime.strptime(form.get("start", ""), "%H:%M").time())
            end = datetime.combine(day, datetime.strptime(form.get("end", ""), "%H:%M").time())
            if end <= start:
                errors.append("Sluttidspunktet skal være efter starttidspunktet.")
        except ValueError:
            errors.append("Angiv start- og sluttidspunkt som TT:MM.")

    user_id = form.get("user_id") or None
    if user_id is not None:
        if user_id.isdigit() and db.query("SELECT 1 FROM users WHERE id = ?", (user_id,), one=True):
            user_id = int(user_id)
        else:
            errors.append("Ugyldig person.")
            user_id = None

    data = {
        "ticket": ticket,
        "user_id": user_id,
        "starts_at": start.strftime(DT_FORMAT) if start else None,
        "ends_at": end.strftime(DT_FORMAT) if end else None,
        "note": form.get("note", "").strip(),
    }
    return data, errors


def _warn_overlaps(data, exclude_slot_id=None):
    if not data["user_id"]:
        return
    clashes = db.query(
        SLOT_SELECT + " WHERE s.user_id = ? AND s.starts_at < ? AND s.ends_at > ? AND s.id != ?",
        (data["user_id"], data["ends_at"], data["starts_at"], exclude_slot_id or 0),
    )
    for c in clashes:
        flash(
            f"Bemærk: {c['user_name']} er allerede sat på ‘{c['title']}’ "
            f"kl. {fmt_time(c['starts_at'])}–{fmt_time(c['ends_at'])} samme dag.",
            "warning",
        )


def _describe(data, user_name):
    text = f"{fmt_date(data['starts_at'])} kl. {fmt_time(data['starts_at'])}–{fmt_time(data['ends_at'])}"
    return f"{text} ({user_name})" if user_name else text


def _user_name(user_id):
    if not user_id:
        return None
    return db.query("SELECT name FROM users WHERE id = ?", (user_id,), one=True)["name"]


def _after_save_target(data):
    return safe_target(request.args.get("next"), url_for("schedule.week", dato=data["starts_at"][:10]))


@bp.route("/kalender/ny", methods=["GET", "POST"])
def slot_new():
    if request.method == "POST":
        data, errors = _parse_slot_form(request.form)
        if not errors:
            ticket = data["ticket"]
            slot_id = db.execute(
                "INSERT INTO time_slots (ticket_id, user_id, starts_at, ends_at, note, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticket["id"], data["user_id"], data["starts_at"], data["ends_at"], data["note"],
                 g.user["id"], now_str()),
            )
            log_event(ticket["id"], "Tid planlagt: " + _describe(data, _user_name(data["user_id"])) + ".")
            if ticket["assignee_id"] is None and data["user_id"]:
                db.execute("UPDATE tickets SET assignee_id = ? WHERE id = ?", (data["user_id"], ticket["id"]))
            if ticket["status"] == "ny":
                set_status(ticket, "planlagt")
            _warn_overlaps(data, exclude_slot_id=slot_id)
            flash("Tiden er lagt i kalenderen.", "success")
            return redirect(_after_save_target(data))
        for e in errors:
            flash(e, "error")
        form = request.form
    else:
        form = _prefill(request.args)
    return render_template(
        "slot_form.html", slot=None, form=form,
        tickets=_schedulable_tickets(form.get("ticket_id")), users=db.active_users(),
        cancel_url=safe_target(request.args.get("next"), url_for("schedule.week", dato=form.get("date"))),
    )


def _prefill(args):
    ticket_id = args.get("opgave", "")
    ticket = None
    if ticket_id.isdigit():
        ticket = db.query("SELECT * FROM tickets WHERE id = ?", (int(ticket_id),), one=True)
    day = parse_date(args.get("dato")) or date.today()
    try:
        start = datetime.strptime(args.get("fra", ""), "%H:%M")
    except ValueError:
        start = datetime.strptime("08:00", "%H:%M")
    hours = DEFAULT_SLOT_HOURS
    if ticket and ticket["estimate_hours"]:
        hours = min(ticket["estimate_hours"], 8)
    end = start + timedelta(hours=hours)
    if end.day != start.day:  # må ikke gå over midnat
        end = start.replace(hour=23, minute=59)
    user_id = ticket["assignee_id"] if ticket and ticket["assignee_id"] else g.user["id"]
    return {
        "ticket_id": str(ticket["id"]) if ticket else "",
        "date": day.isoformat(),
        "start": start.strftime("%H:%M"),
        "end": end.strftime("%H:%M"),
        "user_id": str(user_id),
        "note": "",
    }


def _get_slot(slot_id):
    slot = db.query(SLOT_SELECT + " WHERE s.id = ?", (slot_id,), one=True)
    if slot is None:
        abort(404)
    return slot


@bp.route("/kalender/<int:slot_id>", methods=["GET", "POST"])
def slot_edit(slot_id):
    slot = _get_slot(slot_id)
    if request.method == "POST":
        data, errors = _parse_slot_form(request.form)
        if not errors:
            db.execute(
                "UPDATE time_slots SET ticket_id = ?, user_id = ?, starts_at = ?, ends_at = ?, note = ?"
                " WHERE id = ?",
                (data["ticket"]["id"], data["user_id"], data["starts_at"], data["ends_at"], data["note"], slot_id),
            )
            if (slot["starts_at"], slot["ends_at"], slot["user_id"]) != (
                data["starts_at"], data["ends_at"], data["user_id"]
            ):
                log_event(data["ticket"]["id"], "Tid flyttet til " + _describe(data, _user_name(data["user_id"])) + ".")
            _warn_overlaps(data, exclude_slot_id=slot_id)
            flash("Tidsblokken er gemt.", "success")
            return redirect(_after_save_target(data))
        for e in errors:
            flash(e, "error")
        form = request.form
    else:
        form = {
            "ticket_id": str(slot["ticket_id"]),
            "date": slot["starts_at"][:10],
            "start": fmt_time(slot["starts_at"]),
            "end": fmt_time(slot["ends_at"]),
            "user_id": str(slot["user_id"] or ""),
            "note": slot["note"],
        }
    return render_template(
        "slot_form.html", slot=slot, form=form,
        tickets=_schedulable_tickets(slot["ticket_id"]), users=db.active_users(),
        cancel_url=safe_target(request.args.get("next"), url_for("schedule.week", dato=form.get("date"))),
    )


@bp.route("/kalender/<int:slot_id>/slet", methods=["POST"])
def slot_delete(slot_id):
    slot = _get_slot(slot_id)
    db.execute("DELETE FROM time_slots WHERE id = ?", (slot_id,))
    log_event(slot["ticket_id"], "Tid fjernet fra kalenderen: " + _describe(slot, slot["user_name"]) + ".")
    flash("Tidsblokken er fjernet fra kalenderen.", "success")
    return redirect(safe_target(request.args.get("next"), url_for("schedule.week", dato=slot["starts_at"][:10])))


# ---------- iCal-feed (abonnér fra telefon/Outlook/Google Kalender) ----------

def _ics_escape(text):
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line):
    """Linjer i iCal må højst være 75 bytes; længere linjer foldes."""
    out, current = [], b""
    for ch in line:
        enc = ch.encode("utf-8")
        if len(current) + len(enc) > 74:
            out.append(current.decode("utf-8"))
            current = b" "
        current += enc
    out.append(current.decode("utf-8"))
    return "\r\n".join(out)


def _ics_dt(value):
    return parse_dt(value).strftime("%Y%m%dT%H%M%S")


@bp.route("/kalender/feed/<token>.ics")
def ical_feed(token):
    user = db.query("SELECT * FROM users WHERE ical_token = ? AND active = 1", (token,), one=True)
    if user is None:
        abort(404)
    since = (date.today() - timedelta(days=90)).isoformat()
    sql = SLOT_SELECT + " WHERE s.ends_at >= ?"
    params = [since]
    if request.args.get("kun_mine"):
        sql += " AND s.user_id = ?"
        params.append(user["id"])
    slots = db.query(sql + " ORDER BY s.starts_at", params)

    stamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Gaardopgaver//DA",
        "CALSCALE:GREGORIAN",
        "X-WR-CALNAME:Gårdopgaver",
        "X-WR-TIMEZONE:Europe/Copenhagen",
    ]
    for s in slots:
        desc = [f"Prioritet: {PRIORITIES[s['priority']]}", f"Status: {STATUS_LABELS[s['status']]}"]
        if s["user_name"]:
            desc.append(f"Udføres af: {s['user_name']}")
        if s["note"]:
            desc.append(s["note"])
        if not current_app.config["HA_MODE"]:  # inde i Home Assistant giver et direkte link ingen mening
            desc.append(url_for("tickets.ticket_detail", ticket_id=s["ticket_id"], _external=True))
        lines += [
            "BEGIN:VEVENT",
            f"UID:slot-{s['id']}@gaardopgaver",
            f"DTSTAMP:{stamp}",
            f"DTSTART:{_ics_dt(s['starts_at'])}",
            f"DTEND:{_ics_dt(s['ends_at'])}",
            f"SUMMARY:{_ics_escape(s['title'])}",
            f"DESCRIPTION:{_ics_escape(chr(10).join(desc))}",
        ]
        if s["location"]:
            lines.append(f"LOCATION:{_ics_escape(s['location'])}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    body = "\r\n".join(_ics_fold(line) for line in lines) + "\r\n"
    return Response(body, mimetype="text/calendar", headers={"Cache-Control": "no-cache"})
