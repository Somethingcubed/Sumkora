from datetime import date, timedelta

from fastapi.testclient import TestClient

from companion import companion_state, feed_companion, set_companion_enabled
from db import query_one
from main import app


client = TestClient(app)


def sign_up(username: str):
    client.cookies.clear()
    response = client.post(
        "/signup",
        data={
            "username": username,
            "password": "companion-pass",
            "password_confirmation": "companion-pass",
            "display_name": "",
        },
    )
    assert response.status_code == 200
    return query_one(
        "SELECT * FROM users WHERE username_normalized = ?",
        (username.lower(),),
    )


def test_companion_is_optional_and_daily_feed_route_is_idempotent():
    user = sign_up("CompanionRoute")
    settings = client.get("/student/settings")
    assert "Justin Bieber companion" in settings.text
    assert "There is no chat" in settings.text
    assert "Lou Stejskal" in settings.text
    assert "CC BY 2.0" in settings.text
    assert 'name="companion_enabled" value="1"' in settings.text
    assert 'class="justin-companion' not in client.get("/student").text

    enabled = client.post(
        "/student/settings/companion",
        data={"companion_enabled": "1"},
        follow_redirects=False,
    )
    assert enabled.status_code == 303
    dashboard = client.get("/student")
    assert 'id="justin-companion"' in dashboard.text
    assert "Give a snack" in dashboard.text
    assert "/static/images/justin-bieber-2015.jpg" in dashboard.text

    fed = client.post("/student/companion/feed", follow_redirects=False)
    assert fed.status_code == 303
    assert fed.headers["location"].startswith("/student?companion=fed")
    first = companion_state(user["id"])
    assert first["feed_count"] == 1
    assert first["streak_count"] == 1
    assert first["fed_today"] is True

    client.post("/student/companion/feed", follow_redirects=False)
    second = companion_state(user["id"])
    assert second["feed_count"] == 1
    assert "Fed for today" in client.get("/student").text

    disabled = client.post(
        "/student/settings/companion",
        data={"companion_enabled": "0"},
        follow_redirects=False,
    )
    assert disabled.status_code == 303
    assert 'id="justin-companion"' not in client.get("/student").text


def test_companion_growth_and_streak_use_consecutive_utc8_dates():
    user = sign_up("CompanionGrowth")
    set_companion_enabled(user["id"], True)
    first_day = date(2026, 8, 1)

    first = feed_companion(user["id"], today=first_day)
    duplicate = feed_companion(user["id"], today=first_day)
    second = feed_companion(user["id"], today=first_day + timedelta(days=1))
    gap = feed_companion(user["id"], today=first_day + timedelta(days=4))

    assert first["feed_count"] == 1
    assert duplicate["feed_count"] == 1
    assert second["feed_count"] == 2
    assert second["streak_count"] == 2
    assert second["longest_streak"] == 2
    assert gap["feed_count"] == 3
    assert gap["streak_count"] == 1
    assert gap["stage"]["name_en"] == "Rising star"
    assert gap["longest_streak"] == 2
