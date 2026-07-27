import os
import sqlite3
import hashlib
from datetime import datetime, timedelta

import bcrypt

import config

os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
os.makedirs(config.UPLOAD_DIR, exist_ok=True)


def connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db():
    conn = connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT,
            username_normalized TEXT,
            password_hash TEXT NOT NULL,
            name TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('teacher', 'student')),
            recovery_code_hash TEXT
        );

        CREATE TABLE IF NOT EXISTS classes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            teacher_id INTEGER NOT NULL REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS class_enrollments (
            class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            PRIMARY KEY (class_id, student_id)
        );

        CREATE TABLE IF NOT EXISTS assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_id INTEGER NOT NULL REFERENCES classes(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('past_paper', 'worksheet', 'practice')),
            due_date TEXT,
            total_marks INTEGER DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft', 'published')),
            question_paper_path TEXT,
            mark_scheme_path TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            topic TEXT NOT NULL,
            question_text TEXT NOT NULL DEFAULT '',
            max_marks INTEGER NOT NULL,
            mark_scheme_text TEXT NOT NULL DEFAULT '',
            page_number INTEGER DEFAULT 1,
            order_index INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
            student_id INTEGER NOT NULL REFERENCES users(id),
            file_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'grading', 'review', 'final')),
            uploaded_at TEXT NOT NULL,
            UNIQUE(assignment_id, student_id)
        );

        CREATE TABLE IF NOT EXISTS grade_drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            question_id INTEGER NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            ai_mark REAL,
            ai_confidence REAL,
            ai_notes TEXT,
            final_mark REAL,
            teacher_comment TEXT,
            risk_flags TEXT NOT NULL DEFAULT '',
            needs_exception_review INTEGER NOT NULL DEFAULT 0,
            auto_finalized_at TEXT,
            auto_finalize_reason TEXT,
            teacher_override_mark REAL,
            teacher_override_comment TEXT,
            teacher_override_at TEXT,
            teacher_override_by INTEGER REFERENCES users(id),
            UNIQUE(submission_id, question_id)
        );

        CREATE TABLE IF NOT EXISTS ocr_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            provider TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            text TEXT NOT NULL DEFAULT '',
            confidence REAL,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending', 'done', 'failed', 'skipped')),
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(submission_id, page_number, provider)
        );

        CREATE TABLE IF NOT EXISTS practice_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT NOT NULL,
            label TEXT NOT NULL,
            text TEXT NOT NULL,
            source TEXT DEFAULT 'seed'
        );

        CREATE TABLE IF NOT EXISTS user_roles (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role IN ('student', 'teacher', 'researcher', 'owner')),
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, role)
        );

        CREATE TABLE IF NOT EXISTS paper_packs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            syllabus_code TEXT NOT NULL DEFAULT '0606',
            syllabus_version TEXT NOT NULL DEFAULT '2025-2027',
            year INTEGER NOT NULL,
            examination_session TEXT NOT NULL,
            component TEXT NOT NULL,
            paper_number TEXT NOT NULL,
            calculator_policy TEXT NOT NULL CHECK(calculator_policy IN ('calculator', 'non-calculator', 'unknown')),
            maximum_marks INTEGER NOT NULL DEFAULT 80,
            question_paper_path TEXT,
            mark_scheme_path TEXT,
            grade_threshold_path TEXT,
            question_paper_hash TEXT,
            mark_scheme_hash TEXT,
            threshold_hash TEXT,
            provenance TEXT NOT NULL DEFAULT '',
            ingestion_status TEXT NOT NULL DEFAULT 'registered',
            parser_version TEXT NOT NULL DEFAULT 'paper-pack-v1',
            parsing_confidence REAL,
            raw_metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(syllabus_code, year, examination_session, component)
        );

        CREATE TABLE IF NOT EXISTS paper_questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_pack_id INTEGER NOT NULL REFERENCES paper_packs(id) ON DELETE CASCADE,
            parent_question_id INTEGER REFERENCES paper_questions(id) ON DELETE CASCADE,
            question_number TEXT NOT NULL,
            subpart TEXT NOT NULL DEFAULT '',
            source_pages TEXT NOT NULL DEFAULT '[]',
            prompt_text TEXT NOT NULL DEFAULT '',
            prompt_latex TEXT NOT NULL DEFAULT '',
            maximum_marks INTEGER NOT NULL DEFAULT 0,
            topic TEXT NOT NULL DEFAULT 'Unclassified',
            subtopic TEXT NOT NULL DEFAULT '',
            skills TEXT NOT NULL DEFAULT '[]',
            calculator_policy TEXT NOT NULL DEFAULT 'unknown',
            question_demand TEXT NOT NULL DEFAULT 'standard',
            parsing_confidence REAL,
            raw_source_text TEXT NOT NULL DEFAULT '',
            parser_version TEXT NOT NULL DEFAULT 'paper-pack-v1',
            order_index INTEGER NOT NULL DEFAULT 0,
            UNIQUE(paper_pack_id, question_number, subpart)
        );

        CREATE TABLE IF NOT EXISTS marking_criteria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_question_id INTEGER REFERENCES paper_questions(id) ON DELETE CASCADE,
            legacy_question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
            criterion_code TEXT NOT NULL,
            mark_type TEXT NOT NULL DEFAULT 'TOTAL',
            marks REAL NOT NULL DEFAULT 1,
            description TEXT NOT NULL DEFAULT '',
            dependencies TEXT NOT NULL DEFAULT '[]',
            follow_through_rules TEXT NOT NULL DEFAULT '',
            acceptable_forms TEXT NOT NULL DEFAULT '[]',
            alternative_methods TEXT NOT NULL DEFAULT '[]',
            raw_mark_scheme_text TEXT NOT NULL DEFAULT '',
            source_page INTEGER,
            source_confidence REAL,
            order_index INTEGER NOT NULL DEFAULT 0,
            version INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER NOT NULL DEFAULT 1,
            CHECK(paper_question_id IS NOT NULL OR legacy_question_id IS NOT NULL)
        );

        CREATE TABLE IF NOT EXISTS model_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER REFERENCES submissions(id) ON DELETE CASCADE,
            run_type TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            parser_version TEXT,
            status TEXT NOT NULL DEFAULT 'queued',
            request_metadata TEXT NOT NULL DEFAULT '{}',
            raw_response TEXT,
            usage_metadata TEXT NOT NULL DEFAULT '{}',
            warning_flags TEXT NOT NULL DEFAULT '[]',
            error TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            duration_ms INTEGER
        );

        CREATE TABLE IF NOT EXISTS criterion_decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
            criterion_id INTEGER NOT NULL REFERENCES marking_criteria(id) ON DELETE CASCADE,
            model_run_id INTEGER REFERENCES model_runs(id) ON DELETE SET NULL,
            awarded_marks REAL NOT NULL DEFAULT 0,
            available_marks REAL NOT NULL DEFAULT 0,
            decision TEXT NOT NULL DEFAULT 'uncertain',
            evidence_text TEXT NOT NULL DEFAULT '',
            evidence_page INTEGER,
            evidence_region TEXT NOT NULL DEFAULT '{}',
            rationale TEXT NOT NULL DEFAULT '',
            confidence REAL NOT NULL DEFAULT 0,
            extraction_confidence REAL,
            ambiguity TEXT NOT NULL DEFAULT '',
            possible_alternative_method TEXT NOT NULL DEFAULT '',
            deterministic_check TEXT NOT NULL DEFAULT '{}',
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            raw_provider_response TEXT,
            warning_flags TEXT NOT NULL DEFAULT '[]',
            is_current INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            UNIQUE(submission_id, criterion_id, model_run_id)
        );

        CREATE TABLE IF NOT EXISTS processing_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'processing', 'completed', 'failed')),
            current_stage TEXT NOT NULL DEFAULT 'validation',
            stage_index INTEGER NOT NULL DEFAULT 0,
            warnings TEXT NOT NULL DEFAULT '[]',
            failure_message TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            finished_at TEXT
        );

        CREATE TABLE IF NOT EXISTS skill_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_pack_id INTEGER REFERENCES paper_packs(id) ON DELETE SET NULL,
            submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
            question_id INTEGER REFERENCES questions(id) ON DELETE CASCADE,
            criterion_decision_id INTEGER REFERENCES criterion_decisions(id) ON DELETE CASCADE,
            observed_at TEXT NOT NULL,
            topic TEXT NOT NULL,
            subtopic TEXT NOT NULL DEFAULT '',
            skill TEXT NOT NULL,
            marks_earned REAL NOT NULL,
            marks_available REAL NOT NULL,
            success_fraction REAL NOT NULL,
            grading_confidence REAL NOT NULL DEFAULT 0.5,
            extraction_confidence REAL NOT NULL DEFAULT 0.5,
            question_demand TEXT NOT NULL DEFAULT 'standard',
            calculator_policy TEXT NOT NULL DEFAULT 'unknown',
            error_category TEXT,
            error_mechanism TEXT,
            evidence_weight REAL NOT NULL DEFAULT 1,
            model_version TEXT NOT NULL DEFAULT 'legacy-adapter-v1',
            UNIQUE(submission_id, question_id, skill)
        );

        CREATE TABLE IF NOT EXISTS student_skill_states (
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            skill TEXT NOT NULL,
            topic TEXT NOT NULL,
            evidence_count INTEGER NOT NULL,
            distinct_papers INTEGER NOT NULL,
            total_marks_earned REAL NOT NULL,
            total_marks_available REAL NOT NULL,
            all_time_estimate REAL NOT NULL,
            current_estimate REAL NOT NULL,
            uncertainty REAL NOT NULL,
            status TEXT NOT NULL,
            trend TEXT NOT NULL,
            first_observed TEXT NOT NULL,
            last_observed TEXT NOT NULL,
            calculation_version TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (student_id, skill)
        );

        CREATE TABLE IF NOT EXISTS human_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            criterion_decision_id INTEGER NOT NULL REFERENCES criterion_decisions(id) ON DELETE CASCADE,
            corrected_by INTEGER NOT NULL REFERENCES users(id),
            original_marks REAL NOT NULL,
            corrected_marks REAL NOT NULL,
            reason TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            research_question TEXT NOT NULL DEFAULT '',
            hypothesis TEXT NOT NULL DEFAULT '',
            dataset_selection TEXT NOT NULL DEFAULT '{}',
            independent_variable TEXT NOT NULL DEFAULT '',
            comparison_groups TEXT NOT NULL DEFAULT '[]',
            model_version TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            ocr_model TEXT NOT NULL DEFAULT '',
            confidence_threshold REAL,
            taxonomy_version TEXT NOT NULL DEFAULT '0606-v1',
            calculation_version TEXT NOT NULL DEFAULT 'beta-recency-v1',
            metrics TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT '',
            notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'planned',
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER REFERENCES users(id),
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS student_papers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            syllabus_code TEXT NOT NULL DEFAULT '0606',
            paper_number TEXT NOT NULL DEFAULT '',
            paper_year INTEGER,
            examination_session TEXT NOT NULL DEFAULT '',
            calculator_policy TEXT NOT NULL DEFAULT 'unknown',
            maximum_marks REAL NOT NULL DEFAULT 0,
            source_type TEXT NOT NULL DEFAULT 'custom',
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK(status IN ('draft', 'ready', 'processing', 'completed', 'failed', 'archived')),
            latest_version_number INTEGER NOT NULL DEFAULT 1,
            legacy_submission_id INTEGER REFERENCES submissions(id) ON DELETE SET NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS paper_analysis_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            paper_id INTEGER NOT NULL REFERENCES student_papers(id) ON DELETE CASCADE,
            version_number INTEGER NOT NULL,
            supersedes_version_id INTEGER REFERENCES paper_analysis_versions(id) ON DELETE SET NULL,
            question_paper_path TEXT NOT NULL,
            answer_script_path TEXT NOT NULL,
            mark_scheme_path TEXT,
            status TEXT NOT NULL DEFAULT 'review'
                CHECK(status IN ('review', 'queued', 'processing', 'completed', 'failed', 'cancelled')),
            current_stage TEXT NOT NULL DEFAULT 'metadata_review',
            stage_index INTEGER NOT NULL DEFAULT 0,
            detected_metadata TEXT NOT NULL DEFAULT '{}',
            confirmed_metadata TEXT NOT NULL DEFAULT '{}',
            question_plan TEXT NOT NULL DEFAULT '[]',
            ocr_model TEXT NOT NULL DEFAULT '',
            grading_model TEXT NOT NULL DEFAULT '',
            diagnosis_model TEXT NOT NULL DEFAULT '',
            ocr_prompt_version TEXT NOT NULL DEFAULT '',
            grading_prompt_version TEXT NOT NULL DEFAULT 'grading-0606-v1',
            parser_version TEXT NOT NULL DEFAULT 'self-service-parser-v1',
            confidence_threshold REAL NOT NULL DEFAULT 0.70,
            deterministic_checks INTEGER NOT NULL DEFAULT 1,
            image_resolution INTEGER NOT NULL DEFAULT 200,
            preprocessing_config TEXT NOT NULL DEFAULT '{}',
            confirmed_min_score REAL,
            provisional_score REAL,
            possible_max_score REAL,
            warnings TEXT NOT NULL DEFAULT '[]',
            assessment_mode TEXT NOT NULL DEFAULT 'legacy',
            expected_maximum_marks REAL,
            assessment_summary TEXT NOT NULL DEFAULT '{}',
            provider_metadata TEXT NOT NULL DEFAULT '{}',
            progress_percent REAL NOT NULL DEFAULT 0,
            progress_message TEXT NOT NULL DEFAULT '',
            progress_detail TEXT NOT NULL DEFAULT '',
            heartbeat_at TEXT,
            failure_details TEXT NOT NULL DEFAULT '{}',
            failure_message TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            updated_at TEXT NOT NULL,
            finished_at TEXT,
            UNIQUE(paper_id, version_number)
        );

        CREATE TABLE IF NOT EXISTS analysis_ocr_pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_version_id INTEGER NOT NULL REFERENCES paper_analysis_versions(id) ON DELETE CASCADE,
            document_type TEXT NOT NULL DEFAULT 'answer_script',
            page_number INTEGER NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            text TEXT NOT NULL DEFAULT '',
            normalized_text TEXT NOT NULL DEFAULT '',
            confidence REAL,
            warnings TEXT NOT NULL DEFAULT '[]',
            raw_response TEXT,
            timing_ms INTEGER,
            evaluation_label TEXT,
            corrected_text TEXT,
            corrected_by INTEGER REFERENCES users(id),
            corrected_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(analysis_version_id, document_type, page_number, model, prompt_version)
        );

        CREATE TABLE IF NOT EXISTS analysis_question_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_version_id INTEGER NOT NULL REFERENCES paper_analysis_versions(id) ON DELETE CASCADE,
            question_label TEXT NOT NULL,
            question_text TEXT NOT NULL DEFAULT '',
            mark_scheme_text TEXT NOT NULL DEFAULT '',
            structured_criteria TEXT NOT NULL DEFAULT '[]',
            maximum_marks REAL NOT NULL DEFAULT 0,
            topic TEXT NOT NULL DEFAULT 'Unclassified',
            subtopic TEXT NOT NULL DEFAULT '',
            skill TEXT NOT NULL DEFAULT '',
            answer_page INTEGER NOT NULL DEFAULT 1,
            response_text TEXT NOT NULL DEFAULT '',
            mapping_confidence REAL NOT NULL DEFAULT 0.5,
            ai_mark REAL NOT NULL DEFAULT 0,
            ai_confidence REAL NOT NULL DEFAULT 0,
            ai_rationale TEXT NOT NULL DEFAULT '',
            cited_evidence TEXT NOT NULL DEFAULT '',
            error_category TEXT,
            error_mechanism TEXT,
            deterministic_check TEXT NOT NULL DEFAULT '{}',
            risk_flags TEXT NOT NULL DEFAULT '[]',
            model TEXT NOT NULL DEFAULT '',
            prompt_version TEXT NOT NULL DEFAULT '',
            raw_provider_response TEXT,
            assessment_status TEXT NOT NULL DEFAULT 'graded',
            awarded_mark REAL,
            evidence_pages TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            UNIQUE(analysis_version_id, question_label)
        );

        CREATE TABLE IF NOT EXISTS analysis_human_corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_question_result_id INTEGER NOT NULL REFERENCES analysis_question_results(id) ON DELETE CASCADE,
            corrected_by INTEGER NOT NULL REFERENCES users(id),
            original_mark REAL NOT NULL,
            corrected_mark REAL NOT NULL,
            corrected_decision TEXT NOT NULL DEFAULT '',
            error_category TEXT,
            error_mechanism TEXT,
            failure_explanation TEXT NOT NULL DEFAULT '',
            alternative_method_should_pass INTEGER,
            ocr_caused_error INTEGER,
            parser_caused_error INTEGER,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS analysis_skill_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            paper_id INTEGER NOT NULL REFERENCES student_papers(id) ON DELETE CASCADE,
            analysis_version_id INTEGER NOT NULL REFERENCES paper_analysis_versions(id) ON DELETE CASCADE,
            question_result_id INTEGER NOT NULL REFERENCES analysis_question_results(id) ON DELETE CASCADE,
            observed_at TEXT NOT NULL,
            topic TEXT NOT NULL,
            subtopic TEXT NOT NULL DEFAULT '',
            skill TEXT NOT NULL,
            marks_earned REAL NOT NULL,
            marks_available REAL NOT NULL,
            success_fraction REAL NOT NULL,
            grading_confidence REAL NOT NULL DEFAULT 0.5,
            extraction_confidence REAL NOT NULL DEFAULT 0.5,
            evidence_weight REAL NOT NULL DEFAULT 1,
            error_category TEXT,
            error_mechanism TEXT,
            calculation_version TEXT NOT NULL DEFAULT 'beta-recency-v1',
            is_current INTEGER NOT NULL DEFAULT 1,
            UNIQUE(analysis_version_id, question_result_id, skill)
        );

        CREATE TABLE IF NOT EXISTS mistake_book_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            analysis_question_result_id INTEGER NOT NULL REFERENCES analysis_question_results(id) ON DELETE CASCADE,
            paper_question_id INTEGER REFERENCES paper_questions(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'not_retried'
                CHECK(status IN ('not_retried', 'improving', 'mastered')),
            first_added_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(student_id, analysis_question_result_id)
        );

        CREATE TABLE IF NOT EXISTS practice_sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            selection_mode TEXT NOT NULL DEFAULT 'weaknesses'
                CHECK(selection_mode IN ('weaknesses', 'topic', 'mixed', 'mistakes')),
            requested_count INTEGER NOT NULL,
            actual_count INTEGER NOT NULL DEFAULT 0,
            topic TEXT NOT NULL DEFAULT '',
            difficulty TEXT NOT NULL DEFAULT 'mixed',
            calculator_policy TEXT NOT NULL DEFAULT 'any',
            language TEXT NOT NULL DEFAULT 'en',
            status TEXT NOT NULL DEFAULT 'ready'
                CHECK(status IN ('draft', 'ready', 'completed', 'archived')),
            selection_explanation TEXT NOT NULL DEFAULT '',
            analysis_paper_id INTEGER REFERENCES student_papers(id) ON DELETE SET NULL,
            submitted_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS practice_set_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            practice_set_id INTEGER NOT NULL REFERENCES practice_sets(id) ON DELETE CASCADE,
            paper_question_id INTEGER NOT NULL REFERENCES paper_questions(id) ON DELETE RESTRICT,
            mistake_book_entry_id INTEGER REFERENCES mistake_book_entries(id) ON DELETE SET NULL,
            order_index INTEGER NOT NULL,
            selection_reason TEXT NOT NULL DEFAULT '',
            UNIQUE(practice_set_id, paper_question_id)
        );

        CREATE TABLE IF NOT EXISTS research_experiment_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL REFERENCES research_experiments(id) ON DELETE CASCADE,
            run_number INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            baseline INTEGER NOT NULL DEFAULT 0,
            configuration_snapshot TEXT NOT NULL DEFAULT '{}',
            sample_size INTEGER NOT NULL DEFAULT 0,
            metrics TEXT NOT NULL DEFAULT '{}',
            result_summary TEXT NOT NULL DEFAULT '',
            failure_message TEXT,
            started_at TEXT,
            finished_at TEXT,
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            UNIQUE(experiment_id, run_number)
        );

        CREATE TABLE IF NOT EXISTS research_dataset_selections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            filters TEXT NOT NULL DEFAULT '{}',
            sample_size INTEGER NOT NULL DEFAULT 0,
            created_by INTEGER NOT NULL REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_failure_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            analysis_version_id INTEGER REFERENCES paper_analysis_versions(id) ON DELETE CASCADE,
            ocr_page_id INTEGER REFERENCES analysis_ocr_pages(id) ON DELETE CASCADE,
            question_result_id INTEGER REFERENCES analysis_question_results(id) ON DELETE CASCADE,
            failure_type TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'open',
            tags TEXT NOT NULL DEFAULT '[]',
            notes TEXT NOT NULL DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS student_activity_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL,
            path TEXT NOT NULL DEFAULT '',
            entity_type TEXT NOT NULL DEFAULT '',
            entity_id TEXT NOT NULL DEFAULT '',
            active_seconds INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS taxonomy_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'draft',
            taxonomy TEXT NOT NULL DEFAULT '{}',
            notes TEXT NOT NULL DEFAULT '',
            created_by INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_submissions_student ON submissions(student_id, uploaded_at);
        CREATE INDEX IF NOT EXISTS idx_processing_submission ON processing_jobs(submission_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_observations_student_skill ON skill_observations(student_id, skill, observed_at);
        CREATE INDEX IF NOT EXISTS idx_decisions_submission ON criterion_decisions(submission_id, is_current);
        CREATE INDEX IF NOT EXISTS idx_student_papers_owner ON student_papers(student_id, updated_at);
        CREATE INDEX IF NOT EXISTS idx_analysis_versions_paper ON paper_analysis_versions(paper_id, version_number);
        CREATE INDEX IF NOT EXISTS idx_analysis_ocr_version ON analysis_ocr_pages(analysis_version_id, page_number);
        CREATE INDEX IF NOT EXISTS idx_analysis_results_version ON analysis_question_results(analysis_version_id, question_label);
        CREATE INDEX IF NOT EXISTS idx_experiment_runs ON research_experiment_runs(experiment_id, run_number);
        CREATE INDEX IF NOT EXISTS idx_student_activity_student_time
        ON student_activity_events(student_id, created_at);
        """
    )
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(questions)").fetchall()
    }
    user_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(users)").fetchall()
    }
    user_column_defs = {
        "username": "TEXT",
        "username_normalized": "TEXT",
        "recovery_code_hash": "TEXT",
    }
    for column, definition in user_column_defs.items():
        if column not in user_columns:
            conn.execute(f"ALTER TABLE users ADD COLUMN {column} {definition}")
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_normalized
        ON users(username_normalized)
        WHERE username_normalized IS NOT NULL
        """
    )
    for row in conn.execute(
        """
        SELECT id, email FROM users
        WHERE role = 'student' AND username_normalized IS NULL
        """
    ).fetchall():
        candidate = row["email"].split("@", 1)[0].strip().lower()
        if (
            3 <= len(candidate) <= 24
            and all(character.isalnum() or character in "_-" for character in candidate)
            and not conn.execute(
                "SELECT 1 FROM users WHERE username_normalized = ?",
                (candidate,),
            ).fetchone()
        ):
            conn.execute(
                """
                UPDATE users
                SET username = ?, username_normalized = ?
                WHERE id = ?
                """,
                (candidate, candidate, row["id"]),
            )
    if "question_text" not in columns:
        conn.execute(
            "ALTER TABLE questions ADD COLUMN question_text TEXT NOT NULL DEFAULT ''"
        )

    grade_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(grade_drafts)").fetchall()
    }
    grade_column_defs = {
        "risk_flags": "TEXT NOT NULL DEFAULT ''",
        "needs_exception_review": "INTEGER NOT NULL DEFAULT 0",
        "auto_finalized_at": "TEXT",
        "auto_finalize_reason": "TEXT",
        "teacher_override_mark": "REAL",
        "teacher_override_comment": "TEXT",
        "teacher_override_at": "TEXT",
        "teacher_override_by": "INTEGER REFERENCES users(id)",
    }
    for column, definition in grade_column_defs.items():
        if column not in grade_columns:
            conn.execute(
                f"ALTER TABLE grade_drafts ADD COLUMN {column} {definition}"
            )
    question_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(questions)").fetchall()
    }
    question_column_defs = {
        "syllabus_code": "TEXT",
        "subtopic": "TEXT",
        "paper_component": "TEXT",
        "calculator_allowed": "INTEGER",
        "source_paper": "TEXT",
        "source_year": "INTEGER",
        "question_number": "TEXT",
        "assessment_objective": "TEXT",
        "difficulty_teacher": "TEXT",
        "question_type_tag": "TEXT",
        "mark_structure": "TEXT",
        "requires_method_marks": "INTEGER",
        "answer_only_eligible": "INTEGER",
    }
    for column, definition in question_column_defs.items():
        if column not in question_columns:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {column} {definition}")

    assignment_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(assignments)").fetchall()
    }
    assignment_column_defs = {
        "paper_pack_id": "INTEGER REFERENCES paper_packs(id)",
        "syllabus_code": "TEXT NOT NULL DEFAULT '0606'",
        "syllabus_version": "TEXT",
        "examination_session": "TEXT",
        "paper_component": "TEXT",
        "calculator_policy": "TEXT NOT NULL DEFAULT 'unknown'",
    }
    for column, definition in assignment_column_defs.items():
        if column not in assignment_columns:
            conn.execute(f"ALTER TABLE assignments ADD COLUMN {column} {definition}")

    submission_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(submissions)").fetchall()
    }
    submission_column_defs = {
        "file_hash": "TEXT",
        "confirmed_min_score": "REAL",
        "provisional_score": "REAL",
        "possible_max_score": "REAL",
        "processing_started_at": "TEXT",
        "processing_finished_at": "TEXT",
    }
    for column, definition in submission_column_defs.items():
        if column not in submission_columns:
            conn.execute(f"ALTER TABLE submissions ADD COLUMN {column} {definition}")

    ocr_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(ocr_pages)").fetchall()
    }
    ocr_column_defs = {
        "model": "TEXT NOT NULL DEFAULT ''",
        "prompt_version": "TEXT NOT NULL DEFAULT 'ocr-math-v1'",
        "raw_response": "TEXT",
        "normalized_latex": "TEXT NOT NULL DEFAULT ''",
        "warnings": "TEXT NOT NULL DEFAULT '[]'",
        "timing_ms": "INTEGER",
        "model_run_id": "INTEGER REFERENCES model_runs(id)",
    }
    for column, definition in ocr_column_defs.items():
        if column not in ocr_columns:
            conn.execute(f"ALTER TABLE ocr_pages ADD COLUMN {column} {definition}")

    experiment_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(research_experiments)").fetchall()
    }
    experiment_column_defs = {
        "description": "TEXT NOT NULL DEFAULT ''",
        "grading_model": "TEXT NOT NULL DEFAULT ''",
        "diagnosis_model": "TEXT NOT NULL DEFAULT ''",
        "ocr_prompt_version": "TEXT NOT NULL DEFAULT ''",
        "grading_prompt_version": "TEXT NOT NULL DEFAULT ''",
        "deterministic_checks": "INTEGER NOT NULL DEFAULT 1",
        "image_resolution": "INTEGER NOT NULL DEFAULT 200",
        "preprocessing_config": "TEXT NOT NULL DEFAULT '{}'",
        "longitudinal_config": "TEXT NOT NULL DEFAULT '{}'",
        "evaluation_metrics": "TEXT NOT NULL DEFAULT '[]'",
        "configuration": "TEXT NOT NULL DEFAULT '{}'",
        "archived_at": "TEXT",
        "last_run_at": "TEXT",
    }
    for column, definition in experiment_column_defs.items():
        if column not in experiment_columns:
            conn.execute(
                f"ALTER TABLE research_experiments ADD COLUMN {column} {definition}"
            )

    analysis_version_columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(paper_analysis_versions)"
        ).fetchall()
    }
    analysis_version_column_defs = {
        "assessment_mode": "TEXT NOT NULL DEFAULT 'legacy'",
        "expected_maximum_marks": "REAL",
        "assessment_summary": "TEXT NOT NULL DEFAULT '{}'",
        "provider_metadata": "TEXT NOT NULL DEFAULT '{}'",
        "progress_percent": "REAL NOT NULL DEFAULT 0",
        "progress_message": "TEXT NOT NULL DEFAULT ''",
        "progress_detail": "TEXT NOT NULL DEFAULT ''",
        "heartbeat_at": "TEXT",
        "failure_details": "TEXT NOT NULL DEFAULT '{}'",
    }
    for column, definition in analysis_version_column_defs.items():
        if column not in analysis_version_columns:
            conn.execute(
                f"ALTER TABLE paper_analysis_versions ADD COLUMN {column} {definition}"
            )

    analysis_result_columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(analysis_question_results)"
        ).fetchall()
    }
    analysis_result_column_defs = {
        "assessment_status": "TEXT NOT NULL DEFAULT 'graded'",
        "awarded_mark": "REAL",
        "evidence_pages": "TEXT NOT NULL DEFAULT '[]'",
        "question_latex": "TEXT NOT NULL DEFAULT ''",
    }
    for column, definition in analysis_result_column_defs.items():
        if column not in analysis_result_columns:
            conn.execute(
                f"ALTER TABLE analysis_question_results ADD COLUMN {column} {definition}"
            )

    paper_question_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(paper_questions)").fetchall()
    }
    paper_question_column_defs = {
        "source_key": "TEXT",
        "question_asset_path": "TEXT",
        "answer_asset_path": "TEXT",
        "answer_text": "TEXT NOT NULL DEFAULT ''",
        "dependency_group": "TEXT NOT NULL DEFAULT ''",
        "review_status": "TEXT NOT NULL DEFAULT 'needs_review'",
        "classification_confidence": "REAL NOT NULL DEFAULT 0",
    }
    for column, definition in paper_question_column_defs.items():
        if column not in paper_question_columns:
            conn.execute(
                f"ALTER TABLE paper_questions ADD COLUMN {column} {definition}"
            )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_paper_questions_source_key
        ON paper_questions(source_key)
        WHERE source_key IS NOT NULL AND source_key != ''
        """
    )

    analysis_result_extended_defs = {
        "paper_question_id": "INTEGER REFERENCES paper_questions(id)",
        "ai_rationale_zh": "TEXT NOT NULL DEFAULT ''",
        "error_mechanism_zh": "TEXT NOT NULL DEFAULT ''",
    }
    analysis_result_columns = {
        row["name"]
        for row in conn.execute(
            "PRAGMA table_info(analysis_question_results)"
        ).fetchall()
    }
    for column, definition in analysis_result_extended_defs.items():
        if column not in analysis_result_columns:
            conn.execute(
                f"ALTER TABLE analysis_question_results ADD COLUMN {column} {definition}"
            )

    practice_set_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(practice_sets)").fetchall()
    }
    practice_set_column_defs = {
        "analysis_paper_id": "INTEGER REFERENCES student_papers(id)",
        "submitted_at": "TEXT",
    }
    for column, definition in practice_set_column_defs.items():
        if column not in practice_set_columns:
            conn.execute(
                f"ALTER TABLE practice_sets ADD COLUMN {column} {definition}"
            )
    conn.execute(
        """
        UPDATE analysis_question_results
        SET awarded_mark = ai_mark
        WHERE awarded_mark IS NULL
          AND analysis_version_id IN (
            SELECT id FROM paper_analysis_versions
            WHERE assessment_mode = 'legacy'
          )
        """
    )

    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT OR IGNORE INTO user_roles (user_id, role, created_at)
        SELECT id, role, ? FROM users
        """,
        (now,),
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO user_roles (user_id, role, created_at)
        SELECT id, 'researcher', ? FROM users WHERE role = 'teacher'
        """,
        (now,),
    )
    conn.execute(
        """
        UPDATE users SET name = 'Oscar'
        WHERE lower(email) = 'teacher@school.edu' AND name = 'Ms. Chen'
        """
    )
    conn.execute(
        """
        UPDATE assignments
        SET title = replace(replace(title, 'NUMERA', 'Sumkora'), 'Numera', 'Sumkora')
        WHERE title LIKE '%Numera%' OR title LIKE '%NUMERA%'
        """
    )
    conn.commit()
    conn.close()


def hash_password(password: str) -> str:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    encoded = bcrypt.hashpw(digest, bcrypt.gensalt()).decode()
    return f"bcrypt-sha256${encoded}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith("bcrypt-sha256$"):
            encoded = password_hash.removeprefix("bcrypt-sha256$")
            digest = hashlib.sha256(password.encode("utf-8")).digest()
            return bcrypt.checkpw(digest, encoded.encode())
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode())
    except (ValueError, TypeError):
        return False


def seed_if_empty():
    conn = connect()
    count = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if count > 0:
        conn.close()
        return

    teacher_hash = hash_password("teacher123")
    student_hash = hash_password("student123")

    conn.execute(
        "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
        ("teacher@school.edu", teacher_hash, "Oscar", "teacher"),
    )
    conn.execute(
        """
        INSERT INTO users
        (email, username, username_normalized, password_hash, name, role)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("student@school.edu", "student", "student", student_hash, "Alex Student", "student"),
    )
    conn.execute(
        """
        INSERT INTO users
        (email, username, username_normalized, password_hash, name, role)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        ("student2@school.edu", "student2", "student2", student_hash, "Jamie Lee", "student"),
    )

    teacher_id = conn.execute(
        "SELECT id FROM users WHERE email = 'teacher@school.edu'"
    ).fetchone()["id"]
    student_id = conn.execute(
        "SELECT id FROM users WHERE email = 'student@school.edu'"
    ).fetchone()["id"]
    student2_id = conn.execute(
        "SELECT id FROM users WHERE email = 'student2@school.edu'"
    ).fetchone()["id"]

    conn.execute(
        "INSERT INTO classes (name, teacher_id) VALUES (?, ?)",
        ("0606 Additional Mathematics - Set A", teacher_id),
    )
    class_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student_id),
    )
    conn.execute(
        "INSERT INTO class_enrollments (class_id, student_id) VALUES (?, ?)",
        (class_id, student2_id),
    )

    due = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    conn.execute(
        """
        INSERT INTO assignments
        (class_id, title, type, due_date, total_marks, status, created_at,
         syllabus_code, syllabus_version, paper_component, calculator_policy)
        VALUES (?, ?, ?, ?, ?, ?, ?, '0606', '2025-2027', 'demo',
                'non-calculator')
        """,
        (
            class_id,
            "0606 Diagnostic - Algebra & Calculus",
            "past_paper",
            due,
            20,
            "published",
            datetime.now().isoformat(),
        ),
    )
    assignment_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    sample_questions = [
        ("Q1a", "Algebra and graphs", 2, "Factorise x^2 - 5x + 6. M1 for factors with product 6 and sum -5; A1 fully correct."),
        ("Q1b", "Algebra and graphs", 2, "Solve x^2 - 5x + 6 = 0. A1 for each correct root."),
        ("Q2a", "Functions and graphs", 3, "Find the inverse of f(x)=3x-4. M1 interchange variables; A1 rearrangement; A1 correct domain-aware result."),
        ("Q2b", "Coordinate geometry", 3, "Find the equation of the normal. M1 gradient; M1 negative reciprocal; A1 equation."),
        ("Q3", "Calculus", 4, "Differentiate x^3-4x^2+2x. Award method and accuracy marks criterion by criterion."),
        ("Q4a", "Calculus", 2, "Integrate 6x-4. B1 each term, including the constant of integration where required."),
        ("Q4b", "Trigonometry", 4, "Use the required identity and solve in the stated interval. M marks for method; A marks for valid solutions."),
    ]
    for i, (label, topic, marks, scheme) in enumerate(sample_questions):
        conn.execute(
            """
            INSERT INTO questions
            (assignment_id, label, topic, max_marks, mark_scheme_text,
             page_number, order_index, syllabus_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, '0606')
            """,
            (assignment_id, label, topic, marks, scheme, 1, i),
        )

    practice = [
        ("Algebra and graphs", "0606-PRACTICE-A1", "Solve x^2 - 7x + 10 = 0 and verify both roots."),
        ("Functions and graphs", "0606-PRACTICE-F1", "Find the inverse of f(x)=2x+5 and state its domain."),
        ("Trigonometry", "0606-PRACTICE-T1", "Solve 2 sin x = 1 for 0 ≤ x ≤ 360°."),
        ("Series", "0606-PRACTICE-S1", "Find the first four terms of (1+2x)^6."),
        ("Calculus", "0606-PRACTICE-D1", "Differentiate y=x^3-5x and find its stationary points."),
        ("Calculus", "0606-PRACTICE-I1", "Evaluate the definite integral of 3x^2-4 from 0 to 2."),
        ("Coordinate geometry", "0606-PRACTICE-C1", "Find the perpendicular bisector of the segment joining (2,1) and (6,5)."),
        ("Vectors", "0606-PRACTICE-V1", "Express the point dividing AB in the ratio 2:3 as a position vector."),
    ]
    for topic, label, text in practice:
        conn.execute(
            "INSERT INTO practice_questions (topic, label, text, source) VALUES (?, ?, ?, ?)",
            (topic, label, text, "0606-seed"),
        )

    now = datetime.now().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO user_roles (user_id, role, created_at) VALUES (?, 'teacher', ?)",
        (teacher_id, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO user_roles (user_id, role, created_at) VALUES (?, 'researcher', ?)",
        (teacher_id, now),
    )
    for sid in (student_id, student2_id):
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (user_id, role, created_at) VALUES (?, 'student', ?)",
            (sid, now),
        )

    conn.commit()
    conn.close()


def get_user_by_email(email: str):
    conn = connect()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return row


def get_user_by_id(user_id: int):
    conn = connect()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def user_has_role(user_id: int, *roles: str) -> bool:
    if not roles:
        return False
    placeholders = ",".join("?" for _ in roles)
    row = query_one(
        f"""
        SELECT 1
        FROM user_roles
        WHERE user_id = ? AND role IN ({placeholders})
        LIMIT 1
        """,
        (user_id, *roles),
    )
    return bool(row)


def grant_role(user_id: int, role: str):
    if role not in {"student", "teacher", "researcher", "owner"}:
        raise ValueError("Unsupported role")
    execute(
        """
        INSERT OR IGNORE INTO user_roles (user_id, role, created_at)
        VALUES (?, ?, ?)
        """,
        (user_id, role, datetime.now().isoformat()),
    )


def query_all(sql: str, params=()):
    conn = connect()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def query_one(sql: str, params=()):
    conn = connect()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row


def execute(sql: str, params=()):
    conn = connect()
    cur = conn.execute(sql, params)
    conn.commit()
    last_id = cur.lastrowid
    conn.close()
    return last_id


def update_assignment_total_marks(assignment_id: int):
    conn = connect()
    total = conn.execute(
        "SELECT COALESCE(SUM(max_marks), 0) AS t FROM questions WHERE assignment_id = ?",
        (assignment_id,),
    ).fetchone()["t"]
    conn.execute(
        "UPDATE assignments SET total_marks = ? WHERE id = ?",
        (total, assignment_id),
    )
    conn.commit()
    conn.close()


def compute_topic_mastery(student_id: int):
    rows = query_all(
        """
        SELECT q.topic,
               SUM(COALESCE(gd.final_mark, 0)) AS earned,
               SUM(q.max_marks) AS possible,
               COUNT(*) AS question_count
        FROM grade_drafts gd
        JOIN questions q ON q.id = gd.question_id
        JOIN submissions s ON s.id = gd.submission_id
        JOIN assignments a ON a.id = s.assignment_id
        WHERE s.student_id = ? AND s.status = 'final'
          AND gd.final_mark IS NOT NULL
          AND a.syllabus_code = '0606'
        GROUP BY q.topic
        """,
        (student_id,),
    )
    result = []
    for row in rows:
        possible = row["possible"] or 0
        earned = row["earned"] or 0
        pct = round(100 * earned / possible, 1) if possible else 0
        result.append(
            {
                "topic": row["topic"],
                "earned": earned,
                "possible": possible,
                "accuracy": pct,
                "question_count": row["question_count"],
            }
        )
    result.sort(key=lambda x: x["accuracy"])
    return result


def weak_topics(student_id: int, threshold: float = 60.0):
    mastery = compute_topic_mastery(student_id)
    return [m for m in mastery if m["accuracy"] < threshold]


def recommend_practice(student_id: int, limit: int = 5):
    weak = weak_topics(student_id)
    if not weak:
        mastery = compute_topic_mastery(student_id)
        if mastery:
            topic = mastery[0]["topic"]
        else:
            return query_all(
                """
                SELECT * FROM practice_questions
                WHERE source LIKE '0606%' OR label LIKE '0606-%'
                ORDER BY id LIMIT ?
                """,
                (limit,),
            )
        return query_all(
            """
            SELECT * FROM practice_questions
            WHERE topic = ?
              AND (source LIKE '0606%' OR label LIKE '0606-%')
            ORDER BY id LIMIT ?
            """,
            (topic, limit),
        )

    topic = weak[0]["topic"]
    return query_all(
        """
        SELECT * FROM practice_questions
        WHERE topic = ?
          AND (source LIKE '0606%' OR label LIKE '0606-%')
        ORDER BY id LIMIT ?
        """,
        (topic, limit),
    )
