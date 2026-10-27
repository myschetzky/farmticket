import re
from datetime import date, timedelta

import pytest

from gaardopgaver import create_app
from gaardopgaver.db import query


@pytest.fixture
def app(tmp_path):
    return create_app({"DATA_DIR": str(tmp_path), "DATABASE": str(tmp_path / "test.db"),
                       "SECRET_KEY": "test", "CSRF_ENABLED": False, "TESTING": True})


@pytest.fixture
def client(app):
    c = app.test_client()
    c.post("/opsaetning", data={"name": "Niklas", "username": "niklas", "password": "hemmelig",
                                "password2": "hemmelig", "examples": "1"})
    return c


def make_ticket(client, **kw):
    data = {"title": "Ny låge ved fold", "description": "", "category": "Hegn og stolper",
            "location": "Fold", "priority": "2", "estimate_hours": "1,5", "due_date": ""}
    data.update(kw)
    resp = client.post("/opgaver/ny", data=data)
    assert resp.status_code == 302
    return int(resp.headers["Location"].rstrip("/").split("/")[-1])


def test_first_run_redirects_to_setup(app):
    c = app.test_client()
    assert c.get("/").headers["Location"].startswith("/opsaetning")


def test_setup_creates_admin_and_examples(client, app):
    resp = client.get("/opgaver")
    html = resp.get_data(as_text=True)
    assert "Fejlfinde ridebanelys, der springer sikring" in html
    assert "Skifte knækkede stolper på ridebane" in html
    assert "julelys" in html
    with app.app_context():
        assert query("SELECT is_admin FROM users", one=True)["is_admin"] == 1
    # Opsætningssiden kan ikke bruges igen
    assert client.get("/opsaetning").status_code == 302


def test_login_required_and_login(client, app):
    anon = app.test_client()
    assert "/login" in anon.get("/opgaver").headers["Location"]
    bad = anon.post("/login", data={"username": "niklas", "password": "forkert"})
    assert "Forkert brugernavn" in bad.get_data(as_text=True)
    ok = anon.post("/login?next=/kalender", data={"username": "NIKLAS", "password": "hemmelig"})
    assert ok.headers["Location"] == "/kalender"
    evil = anon.post("/login?next=//evil.example", data={"username": "niklas", "password": "hemmelig"})
    assert evil.headers["Location"] == "/"


def test_create_edit_ticket_and_history(client, app):
    tid = make_ticket(client)
    html = client.get(f"/opgaver/{tid}").get_data(as_text=True)
    assert "Ny låge ved fold" in html and "1,5 t" in html

    resp = client.post(f"/opgaver/{tid}/rediger", data={
        "title": "Ny låge ved fold", "category": "Hegn og stolper", "location": "Fold",
        "priority": "1", "status": "i_gang", "estimate_hours": "2", "due_date": "", "description": "Akut nu"})
    assert resp.status_code == 302
    with app.app_context():
        t = query("SELECT * FROM tickets WHERE id = ?", (tid,), one=True)
        assert (t["priority"], t["status"], t["estimate_hours"]) == (1, "i_gang", 2.0)
        events = [r["body"] for r in query("SELECT body FROM comments WHERE ticket_id = ?", (tid,))]
    assert any("prioritet: Høj → Akut" in e for e in events)
    assert any("til ‘I gang’" in e for e in events)


def test_ticket_validation(client):
    resp = client.post("/opgaver/ny", data={"title": "", "category": "Forkert", "priority": "9"})
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Titel skal udfyldes" in html and "Vælg en kategori" in html and "Ugyldig prioritet" in html


def test_list_sorted_by_priority_and_filters(client):
    make_ticket(client, title="Lav ting", priority="4")
    make_ticket(client, title="Akut ting", priority="1")
    html = client.get("/opgaver").get_data(as_text=True)
    assert html.index("Akut ting") < html.index("Lav ting")
    html = client.get("/opgaver?prioritet=4").get_data(as_text=True)
    assert "Lav ting" in html and "Akut ting" not in html
    html = client.get("/opgaver?q=ridebane").get_data(as_text=True)
    assert "stolper" in html and "Lav ting" not in html


def test_schedule_slot_sets_status_and_shows_in_calendar(client, app):
    tid = make_ticket(client)
    day = (date.today() + timedelta(days=1)).isoformat()
    resp = client.post("/kalender/ny", data={"ticket_id": tid, "date": day, "start": "08:00",
                                              "end": "10:30", "user_id": "1", "note": "Tag skruer med"})
    assert resp.status_code == 302
    assert "er allerede sat på" not in client.get("/").get_data(as_text=True)
    with app.app_context():
        t = query("SELECT status, assignee_id FROM tickets WHERE id = ?", (tid,), one=True)
        assert t["status"] == "planlagt" and t["assignee_id"] == 1

    week = client.get(f"/kalender?dato={day}").get_data(as_text=True)
    assert "Ny låge ved fold" in week and "08:00–10:30" in week

    detail = client.get(f"/opgaver/{tid}").get_data(as_text=True)
    assert "2,5 t" in detail  # planlagt tid

    # Overlap giver en advarsel, men gemmes stadig
    resp = client.post("/kalender/ny", data={"ticket_id": tid, "date": day, "start": "09:00",
                                              "end": "11:00", "user_id": "1"}, follow_redirects=True)
    assert "er allerede sat på" in resp.get_data(as_text=True)


def test_slot_validation_edit_and_delete(client, app):
    tid = make_ticket(client)
    day = date.today().isoformat()
    bad = client.post("/kalender/ny", data={"ticket_id": tid, "date": day, "start": "10:00", "end": "09:00"})
    assert "Sluttidspunktet skal være efter" in bad.get_data(as_text=True)

    client.post("/kalender/ny", data={"ticket_id": tid, "date": day, "start": "10:00", "end": "11:00"})
    with app.app_context():
        slot_id = query("SELECT id FROM time_slots", one=True)["id"]
    client.post(f"/kalender/{slot_id}", data={"ticket_id": tid, "date": day, "start": "13:00", "end": "15:00"})
    with app.app_context():
        s = query("SELECT * FROM time_slots WHERE id = ?", (slot_id,), one=True)
        assert (s["starts_at"], s["ends_at"]) == (f"{day} 13:00", f"{day} 15:00")
    client.post(f"/kalender/{slot_id}/slet")
    with app.app_context():
        assert query("SELECT COUNT(*) AS n FROM time_slots", one=True)["n"] == 0


def test_dashboard_and_unplanned(client):
    html = client.get("/").get_data(as_text=True)
    assert "Mangler tid i kalenderen" in html
    assert "Fejlfinde ridebanelys" in html


def test_ical_feed(client, app):
    tid = make_ticket(client, title="Udtag, carport; terrasse")
    day = (date.today() + timedelta(days=2)).isoformat()
    client.post("/kalender/ny", data={"ticket_id": tid, "date": day, "start": "08:00", "end": "09:00", "user_id": "1"})
    with app.app_context():
        token = query("SELECT ical_token FROM users", one=True)["ical_token"]
    anon = app.test_client()
    resp = anon.get(f"/kalender/feed/{token}.ics")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200 and resp.mimetype == "text/calendar"
    assert "SUMMARY:Udtag\\, carport\\; terrasse" in body
    assert f"DTSTART:{day.replace('-', '')}T080000" in body
    assert anon.get("/kalender/feed/forkert.ics").status_code == 404


def test_status_quick_actions_and_closed(client, app):
    tid = make_ticket(client)
    client.post(f"/opgaver/{tid}/status", data={"status": "udfoert"})
    with app.app_context():
        t = query("SELECT status, closed_at FROM tickets WHERE id = ?", (tid,), one=True)
        assert t["status"] == "udfoert" and t["closed_at"]
    assert "Ny låge ved fold" not in client.get("/opgaver").get_data(as_text=True)
    assert "Ny låge ved fold" in client.get("/opgaver?status=alle").get_data(as_text=True)


def test_users_admin_and_permissions(client, app):
    resp = client.post("/brugere/ny", data={"name": "Mette", "username": "mette", "password": "123456",
                                            "password2": "123456"})
    assert resp.status_code == 302
    other = app.test_client()
    other.post("/login", data={"username": "mette", "password": "123456"})
    assert other.get("/brugere").status_code == 403
    tid = make_ticket(other, title="Mettes opgave")
    assert other.post(f"/opgaver/{tid}/slet").status_code == 403
    assert client.post(f"/opgaver/{tid}/slet").status_code == 302

    # Deaktiveret bruger bliver logget ud
    with app.app_context():
        uid = query("SELECT id FROM users WHERE username = 'mette'", one=True)["id"]
    client.post(f"/brugere/{uid}", data={"name": "Mette"})
    assert "/login" in other.get("/").headers["Location"]


def test_comment(client):
    tid = make_ticket(client)
    client.post(f"/opgaver/{tid}/kommentar", data={"body": "Sikringen sprang igen efter regn"})
    assert "Sikringen sprang igen" in client.get(f"/opgaver/{tid}").get_data(as_text=True)


def test_csrf_enforced(tmp_path):
    app = create_app({"DATA_DIR": str(tmp_path), "DATABASE": str(tmp_path / "t.db"), "SECRET_KEY": "x"})
    c = app.test_client()
    assert c.post("/opsaetning", data={"name": "A", "username": "a", "password": "123456",
                                       "password2": "123456"}).status_code == 400
    html = c.get("/opsaetning").get_data(as_text=True)
    token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
    resp = c.post("/opsaetning", data={"csrf_token": token, "name": "A", "username": "a",
                                       "password": "123456", "password2": "123456"})
    assert resp.status_code == 302
