"""Opgaver (tickets): overblik, liste, oprettelse, redigering, status og kommentarer."""

from datetime import date, timedelta

from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from . import db
from .auth import admin_required, safe_target
from .constants import (
    CATEGORIES,
    CLOSED_STATUSES,
    DEFAULT_PRIORITY,
    EXAMPLE_TICKETS,
    OPEN_STATUSES,
    PRIORITIES,
    PRIORITY_HELP,
    STATUS_LABELS,
    STATUSES,
)
from .dates import fmt_date, now_str, parse_date

bp = Blueprint("tickets", __name__)

# Fælles SELECT med ansvarlig, næste planlagte tid og samlet planlagt tid.
TICKET_SELECT = """
SELECT t.*,
       a.name AS assignee_name,
       c.name AS creator_name,
       (SELECT MIN(s.starts_at) FROM time_slots s
         WHERE s.ticket_id = t.id AND s.ends_at >= :now) AS next_slot,
       (SELECT SUM((julianday(s.ends_at) - julianday(s.starts_at)) * 24) FROM time_slots s
         WHERE s.ticket_id = t.id) AS planned_hours
  FROM tickets t
  LEFT JOIN users a ON a.id = t.assignee_id
  LEFT JOIN users c ON c.id = t.created_by
"""
ORDER_BY = """
 ORDER BY CASE WHEN t.status IN ('udfoert', 'annulleret') THEN 1 ELSE 0 END,
          t.priority, t.due_date IS NULL, t.due_date, t.created_at
"""
OPEN_SQL = "t.status IN ({})".format(", ".join(f"'{s}'" for s in OPEN_STATUSES))


def get_ticket(ticket_id):
    row = db.query(TICKET_SELECT + " WHERE t.id = :id", {"now": now_str(), "id": ticket_id}, one=True)
    if row is None:
        abort(404)
    return row


def log_event(ticket_id, text, user_id=None):
    if user_id is None and g.get("user"):
        user_id = g.user["id"]
    db.execute(
        "INSERT INTO comments (ticket_id, user_id, body, is_event, created_at) VALUES (?, ?, ?, 1, ?)",
        (ticket_id, user_id, text, now_str()),
    )


def set_status(ticket, new_status):
    """Skift status, sæt/ryd 'lukket' tidspunkt og skriv det i historikken."""
    if new_status == ticket["status"]:
        return
    now = now_str()
    closed_at = now if new_status in CLOSED_STATUSES else None
    db.execute(
        "UPDATE tickets SET status = ?, closed_at = ?, updated_at = ? WHERE id = ?",
        (new_status, closed_at, now, ticket["id"]),
    )
    log_event(
        ticket["id"],
        f"Status ændret fra ‘{STATUS_LABELS[ticket['status']]}’ til ‘{STATUS_LABELS[new_status]}’.",
    )


def create_ticket(data, user_id) -> int:
    now = now_str()
    ticket_id = db.execute(
        "INSERT INTO tickets (title, description, category, location, priority, status, assignee_id,"
        " created_by, estimate_hours, due_date, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, 'ny', ?, ?, ?, ?, ?, ?)",
        (
            data["title"],
            data["description"],
            data["category"],
            data["location"],
            data["priority"],
            data["assignee_id"],
            user_id,
            data["estimate_hours"],
            data["due_date"],
            now,
            now,
        ),
    )
    log_event(ticket_id, "Opgaven blev oprettet.", user_id)
    return ticket_id


def create_example_tickets(user_id):
    today = date.today()
    for ex in EXAMPLE_TICKETS:
        due = None
        if "due_date_month_day" in ex:
            month, day = ex["due_date_month_day"]
            due_d = date(today.year, month, day)
            if due_d < today:
                due_d = due_d.replace(year=today.year + 1)
            due = due_d.isoformat()
        create_ticket({**ex, "assignee_id": None, "due_date": due}, user_id)


def parse_ticket_form(form, editing=False):
    errors = []
    title = form.get("title", "").strip()
    if not title:
        errors.append("Titel skal udfyldes.")
    category = form.get("category", "")
    if category not in CATEGORIES:
        errors.append("Vælg en kategori.")
    try:
        priority = int(form.get("priority", DEFAULT_PRIORITY))
        if priority not in PRIORITIES:
            raise ValueError
    except ValueError:
        errors.append("Ugyldig prioritet.")
        priority = DEFAULT_PRIORITY

    assignee_id = form.get("assignee_id") or None
    if assignee_id is not None:
        if not assignee_id.isdigit() or not db.query(
            "SELECT 1 FROM users WHERE id = ?", (assignee_id,), one=True
        ):
            errors.append("Ugyldig ansvarlig.")
            assignee_id = None
        else:
            assignee_id = int(assignee_id)

    estimate = form.get("estimate_hours", "").strip().replace(",", ".")
    estimate_hours = None
    if estimate:
        try:
            estimate_hours = float(estimate)
            if estimate_hours < 0:
                raise ValueError
        except ValueError:
            errors.append("Estimeret tid skal være et tal (timer), fx 2 eller 1,5.")

    due_raw = form.get("due_date", "").strip()
    due_date = None
    if due_raw:
        d = parse_date(due_raw)
        if d is None:
            errors.append("Ugyldig deadline.")
        else:
            due_date = d.isoformat()

    data = {
        "title": title,
        "description": form.get("description", "").strip(),
        "category": category,
        "location": form.get("location", "").strip(),
        "priority": priority,
        "assignee_id": assignee_id,
        "estimate_hours": estimate_hours,
        "due_date": due_date,
    }
    if editing:
        status = form.get("status", "")
        if status not in STATUS_LABELS:
            errors.append("Ugyldig status.")
        data["status"] = status
    return data, errors


def _form_context(**extra):
    locations = [
        r["location"]
        for r in db.query("SELECT DISTINCT location FROM tickets WHERE location != '' ORDER BY location")
    ]
    return dict(
        users=db.active_users(),
        statuses=STATUSES,
        priority_help=PRIORITY_HELP,
        locations=locations,
        **extra,
    )


@bp.route("/")
def dashboard():
    now = now_str()
    today = date.today()
    week_end = today + timedelta(days=7)
    slots = db.query(
        """SELECT s.*, t.title, t.priority, t.status, u.name AS user_name
             FROM time_slots s JOIN tickets t ON t.id = s.ticket_id
             LEFT JOIN users u ON u.id = s.user_id
            WHERE s.ends_at >= ? AND s.starts_at < ?
            ORDER BY s.starts_at""",
        (now, week_end.isoformat()),
    )
    today_slots = [s for s in slots if s["starts_at"][:10] <= today.isoformat()]
    later_slots = [s for s in slots if s["starts_at"][:10] > today.isoformat()]

    unplanned = db.query(
        TICKET_SELECT + f" WHERE {OPEN_SQL} AND t.status != 'venter'"
        " AND NOT EXISTS (SELECT 1 FROM time_slots s WHERE s.ticket_id = t.id AND s.ends_at >= :now)"
        + ORDER_BY + " LIMIT 15",
        {"now": now},
    )
    overdue = db.query(
        TICKET_SELECT + f" WHERE {OPEN_SQL} AND t.due_date < :today" + ORDER_BY,
        {"now": now, "today": today.isoformat()},
    )
    counts = {
        r["priority"]: r["n"]
        for r in db.query(f"SELECT priority, COUNT(*) AS n FROM tickets t WHERE {OPEN_SQL} GROUP BY priority")
    }
    waiting = db.query("SELECT COUNT(*) AS n FROM tickets WHERE status = 'venter'", one=True)["n"]
    return render_template(
        "dashboard.html",
        today=today,
        today_slots=today_slots,
        later_slots=later_slots,
        unplanned=unplanned,
        overdue=overdue,
        counts=counts,
        waiting=waiting,
    )


@bp.route("/opgaver")
def ticket_list():
    args = request.args
    where, params = [], {"now": now_str()}

    status = args.get("status", "aabne")
    if status == "aabne":
        where.append(OPEN_SQL)
    elif status in STATUS_LABELS:
        where.append("t.status = :status")
        params["status"] = status
    elif status != "alle":
        status = "aabne"
        where.append(OPEN_SQL)

    if args.get("prioritet", "").isdigit():
        where.append("t.priority = :priority")
        params["priority"] = int(args["prioritet"])
    if args.get("kategori") in CATEGORIES:
        where.append("t.category = :category")
        params["category"] = args["kategori"]

    assignee = args.get("ansvarlig", "")
    if assignee == "mig":
        where.append("t.assignee_id = :assignee")
        params["assignee"] = g.user["id"]
    elif assignee == "ingen":
        where.append("t.assignee_id IS NULL")
    elif assignee.isdigit():
        where.append("t.assignee_id = :assignee")
        params["assignee"] = int(assignee)

    q = args.get("q", "").strip()
    if q:
        where.append("(t.title LIKE :q OR t.description LIKE :q OR t.location LIKE :q)")
        params["q"] = f"%{q}%"

    sql = TICKET_SELECT + (" WHERE " + " AND ".join(where) if where else "") + ORDER_BY
    return render_template(
        "tickets_list.html",
        tickets=db.query(sql, params),
        users=db.active_users(),
        statuses=STATUSES,
        f={"status": status, "prioritet": args.get("prioritet", ""), "kategori": args.get("kategori", ""),
           "ansvarlig": assignee, "q": q},
        today=date.today().isoformat(),
    )


@bp.route("/opgaver/ny", methods=["GET", "POST"])
def ticket_new():
    if request.method == "POST":
        data, errors = parse_ticket_form(request.form)
        if not errors:
            ticket_id = create_ticket(data, g.user["id"])
            flash("Opgaven er oprettet.", "success")
            if request.form.get("plan_now"):
                return redirect(url_for("schedule.slot_new", opgave=ticket_id))
            return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))
        for e in errors:
            flash(e, "error")
        form = request.form
    else:
        form = {"priority": str(DEFAULT_PRIORITY)}
    return render_template("ticket_form.html", **_form_context(ticket=None, form=form))


@bp.route("/opgaver/<int:ticket_id>")
def ticket_detail(ticket_id):
    ticket = get_ticket(ticket_id)
    slots = db.query(
        """SELECT s.*, u.name AS user_name FROM time_slots s
             LEFT JOIN users u ON u.id = s.user_id
            WHERE s.ticket_id = ? ORDER BY s.starts_at""",
        (ticket_id,),
    )
    comments = db.query(
        """SELECT c.*, u.name AS user_name FROM comments c
             LEFT JOIN users u ON u.id = c.user_id
            WHERE c.ticket_id = ? ORDER BY c.created_at, c.id""",
        (ticket_id,),
    )
    return render_template(
        "ticket_detail.html",
        ticket=ticket,
        slots=slots,
        comments=comments,
        statuses=STATUSES,
        now=now_str(),
        today=date.today().isoformat(),
    )


@bp.route("/opgaver/<int:ticket_id>/rediger", methods=["GET", "POST"])
def ticket_edit(ticket_id):
    ticket = get_ticket(ticket_id)
    if request.method == "POST":
        data, errors = parse_ticket_form(request.form, editing=True)
        if not errors:
            _log_changes(ticket, data)
            db.execute(
                "UPDATE tickets SET title = ?, description = ?, category = ?, location = ?, priority = ?,"
                " assignee_id = ?, estimate_hours = ?, due_date = ?, updated_at = ? WHERE id = ?",
                (
                    data["title"], data["description"], data["category"], data["location"],
                    data["priority"], data["assignee_id"], data["estimate_hours"], data["due_date"],
                    now_str(), ticket_id,
                ),
            )
            set_status(ticket, data["status"])
            flash("Opgaven er gemt.", "success")
            return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id))
        for e in errors:
            flash(e, "error")
        form = request.form
    else:
        form = {k: ("" if ticket[k] is None else str(ticket[k])) for k in ticket.keys()}
        if ticket["estimate_hours"] is not None:
            form["estimate_hours"] = f"{ticket['estimate_hours']:g}".replace(".", ",")
    return render_template("ticket_form.html", **_form_context(ticket=ticket, form=form))


def _log_changes(old, new):
    changes = []
    if old["priority"] != new["priority"]:
        changes.append(f"prioritet: {PRIORITIES[old['priority']]} → {PRIORITIES[new['priority']]}")
    if old["assignee_id"] != new["assignee_id"]:
        names = {u["id"]: u["name"] for u in db.query("SELECT id, name FROM users")}
        changes.append(
            f"ansvarlig: {names.get(old['assignee_id'], 'ingen')} → {names.get(new['assignee_id'], 'ingen')}"
        )
    if old["due_date"] != new["due_date"]:
        before = fmt_date(old["due_date"], with_weekday=False) or "ingen"
        after = fmt_date(new["due_date"], with_weekday=False) or "ingen"
        changes.append(f"deadline: {before} → {after}")
    if changes:
        log_event(old["id"], "Ændret " + "; ".join(changes) + ".")


@bp.route("/opgaver/<int:ticket_id>/status", methods=["POST"])
def ticket_status(ticket_id):
    ticket = get_ticket(ticket_id)
    status = request.form.get("status", "")
    if status not in STATUS_LABELS:
        abort(400)
    set_status(ticket, status)
    flash(f"Status sat til ‘{STATUS_LABELS[status]}’.", "success")
    return redirect(safe_target(request.form.get("back"), url_for("tickets.ticket_detail", ticket_id=ticket_id)))


@bp.route("/opgaver/<int:ticket_id>/kommentar", methods=["POST"])
def ticket_comment(ticket_id):
    get_ticket(ticket_id)
    body = request.form.get("body", "").strip()
    if body:
        db.execute(
            "INSERT INTO comments (ticket_id, user_id, body, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, g.user["id"], body, now_str()),
        )
        db.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (now_str(), ticket_id))
    return redirect(url_for("tickets.ticket_detail", ticket_id=ticket_id) + "#kommentarer")


@bp.route("/opgaver/<int:ticket_id>/slet", methods=["POST"])
@admin_required
def ticket_delete(ticket_id):
    ticket = get_ticket(ticket_id)
    db.execute("DELETE FROM tickets WHERE id = ?", (ticket_id,))
    flash(f"Opgaven ‘{ticket['title']}’ er slettet.", "success")
    return redirect(url_for("tickets.ticket_list"))
