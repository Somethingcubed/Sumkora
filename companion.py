"""Persistent daily-feed state for the optional student companion."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from db import connect, execute, query_one


LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
GROWTH_STAGES = (
    {"minimum": 0, "name_en": "New arrival", "name_zh": "初次登场"},
    {"minimum": 1, "name_en": "Opening act", "name_zh": "暖场新星"},
    {"minimum": 3, "name_en": "Rising star", "name_zh": "上升新星"},
    {"minimum": 7, "name_en": "Headliner", "name_zh": "领衔歌手"},
    {"minimum": 14, "name_en": "Global icon", "name_zh": "全球偶像"},
)


def local_today() -> date:
    return datetime.now(LOCAL_TIMEZONE).date()


def _decorate(row: dict, today: date) -> dict:
    feed_count = max(0, int(row.get("feed_count") or 0))
    stage_index = 0
    for index, stage in enumerate(GROWTH_STAGES):
        if feed_count >= stage["minimum"]:
            stage_index = index

    stage = GROWTH_STAGES[stage_index]
    next_stage = (
        GROWTH_STAGES[stage_index + 1]
        if stage_index + 1 < len(GROWTH_STAGES)
        else None
    )
    start = stage["minimum"]
    if next_stage:
        distance = max(1, next_stage["minimum"] - start)
        progress = round(100 * min(1, (feed_count - start) / distance))
        feeds_to_next = max(0, next_stage["minimum"] - feed_count)
    else:
        progress = 100
        feeds_to_next = 0

    last_fed = row.get("last_fed_date") or ""
    return {
        **row,
        "enabled": bool(row.get("enabled")),
        "feed_count": feed_count,
        "streak_count": max(0, int(row.get("streak_count") or 0)),
        "longest_streak": max(0, int(row.get("longest_streak") or 0)),
        "fed_today": last_fed == today.isoformat(),
        "stage_index": stage_index,
        "stage": stage,
        "next_stage": next_stage,
        "progress": progress,
        "feeds_to_next": feeds_to_next,
    }


def companion_state(student_id: int, *, today: date | None = None) -> dict:
    today = today or local_today()
    row = query_one(
        "SELECT * FROM student_companions WHERE student_id = ?",
        (student_id,),
    )
    if row:
        data = dict(row)
    else:
        data = {
            "student_id": student_id,
            "enabled": 0,
            "feed_count": 0,
            "streak_count": 0,
            "longest_streak": 0,
            "last_fed_date": None,
        }
    return _decorate(data, today)


def set_companion_enabled(student_id: int, enabled: bool) -> dict:
    now = datetime.now(LOCAL_TIMEZONE).isoformat()
    execute(
        """
        INSERT INTO student_companions
        (student_id, enabled, feed_count, streak_count, longest_streak,
         last_fed_date, created_at, updated_at)
        VALUES (?, ?, 0, 0, 0, NULL, ?, ?)
        ON CONFLICT(student_id) DO UPDATE SET
            enabled = excluded.enabled,
            updated_at = excluded.updated_at
        """,
        (student_id, 1 if enabled else 0, now, now),
    )
    return companion_state(student_id)


def feed_companion(student_id: int, *, today: date | None = None) -> dict:
    """Feed once per UTC+8 calendar day; repeated requests are idempotent."""
    today = today or local_today()
    today_text = today.isoformat()
    now = datetime.now(LOCAL_TIMEZONE).isoformat()
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM student_companions WHERE student_id = ?",
            (student_id,),
        ).fetchone()
        if not row or not row["enabled"]:
            conn.rollback()
            return companion_state(student_id, today=today)
        if row["last_fed_date"] == today_text:
            conn.rollback()
            return companion_state(student_id, today=today)

        previous_date = None
        if row["last_fed_date"]:
            try:
                previous_date = date.fromisoformat(row["last_fed_date"])
            except ValueError:
                previous_date = None
        streak = (
            int(row["streak_count"] or 0) + 1
            if previous_date == today - timedelta(days=1)
            else 1
        )
        longest = max(int(row["longest_streak"] or 0), streak)
        conn.execute(
            """
            UPDATE student_companions
            SET feed_count = feed_count + 1,
                streak_count = ?, longest_streak = ?,
                last_fed_date = ?, updated_at = ?
            WHERE student_id = ?
            """,
            (streak, longest, today_text, now, student_id),
        )
        conn.commit()
    finally:
        conn.close()
    return companion_state(student_id, today=today)
