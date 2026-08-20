import sqlite3

import config
import db


def test_legacy_generated_practice_table_is_upgraded_without_data_loss(
    tmp_path, monkeypatch
):
    database_path = tmp_path / "legacy-practice.db"
    conn = sqlite3.connect(database_path)
    conn.executescript(
        """
        CREATE TABLE practice_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            selection_mode TEXT NOT NULL DEFAULT 'weaknesses',
            requested_count INTEGER NOT NULL,
            actual_count INTEGER NOT NULL DEFAULT 0,
            topic TEXT NOT NULL DEFAULT '',
            difficulty TEXT NOT NULL DEFAULT 'mixed',
            calculator_policy TEXT NOT NULL DEFAULT 'any',
            language TEXT NOT NULL DEFAULT 'en',
            status TEXT NOT NULL DEFAULT 'ready',
            selection_explanation TEXT NOT NULL DEFAULT '',
            analysis_paper_id INTEGER,
            submitted_at TEXT,
            source_mode TEXT NOT NULL DEFAULT 'generated',
            generation_model TEXT NOT NULL DEFAULT '',
            curriculum_id TEXT NOT NULL DEFAULT 'general-mathematics',
            curriculum_level TEXT NOT NULL DEFAULT 'grade-9',
            subject TEXT NOT NULL DEFAULT 'mathematics',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE generated_practice_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            practice_set_id INTEGER NOT NULL,
            order_index INTEGER NOT NULL,
            topic TEXT NOT NULL,
            skill TEXT NOT NULL,
            difficulty TEXT NOT NULL DEFAULT 'standard',
            calculator_policy TEXT NOT NULL DEFAULT 'any',
            prompt_en TEXT NOT NULL,
            prompt_zh TEXT NOT NULL,
            solution_en TEXT NOT NULL,
            solution_zh TEXT NOT NULL,
            final_answer_en TEXT NOT NULL DEFAULT '',
            final_answer_zh TEXT NOT NULL DEFAULT '',
            maximum_marks REAL NOT NULL DEFAULT 1,
            validation_notes TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(practice_set_id, order_index)
        );

        INSERT INTO generated_practice_questions
        (practice_set_id, order_index, topic, skill, prompt_en, prompt_zh,
         solution_en, solution_zh, model, created_at)
        VALUES
        (7, 1, 'Algebra', 'linear equations', 'Question', '题目',
        'Solution', '解答', 'legacy-generator', '2026-08-01T00:00:00Z');

        INSERT INTO practice_sets
        (id, student_id, title, selection_mode, requested_count, actual_count,
         status, source_mode, created_at, updated_at)
        VALUES
        (8, 1, 'Broken empty worksheet', 'mixed', 10, 10, 'ready',
         'generated', '2026-08-20T00:00:00Z', '2026-08-20T00:00:00Z');
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "DB_PATH", str(database_path))
    db.init_db()

    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(generated_practice_questions)"
        ).fetchall()
    }
    row = conn.execute(
        "SELECT * FROM generated_practice_questions WHERE id = 1"
    ).fetchone()
    empty_set = conn.execute(
        "SELECT id FROM practice_sets WHERE id = 8"
    ).fetchone()
    conn.close()

    assert {
        "generation_model",
        "validation_model",
        "validation_status",
    }.issubset(columns)
    assert row["generation_model"] == "legacy-generator"
    assert row["validation_model"] == ""
    assert row["validation_status"] == "validated"
    assert empty_set is None
