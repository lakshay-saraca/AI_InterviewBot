"""aiosqlite persistence for interview_configs. Direct SQL, no ORM.

Mirrors models/interview_report.py, but config CREATE fails loud (returns False
on DB failure) — a missing/half-saved config must never silently produce a broken
interview.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from src.types.config import InterviewConfig, InterviewPlan, JDSummary
from src.types.interview import ExperienceLevel

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "interviews.db")

_db: Optional[aiosqlite.Connection] = None


async def _get_db() -> Optional[aiosqlite.Connection]:
    global _db
    if _db is not None:
        try:
            await _db.execute("SELECT 1")
            return _db
        except Exception:
            _db = None
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _init_tables(_db)
        return _db
    except Exception as exc:
        logger.error("Failed to open SQLite DB at %s: %s", DB_PATH, exc)
        return None


async def _init_tables(db: aiosqlite.Connection) -> None:
    await db.execute("""
        CREATE TABLE IF NOT EXISTS interview_configs (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            role TEXT NOT NULL,
            experience_level TEXT NOT NULL,
            job_description TEXT NOT NULL,
            total_questions INTEGER NOT NULL,
            core_question_ratio REAL NOT NULL DEFAULT 0.8,
            jd_summary TEXT NOT NULL DEFAULT '{}',
            interview_plan TEXT NOT NULL DEFAULT '{}',
            created_at TEXT
        )
    """)
    await db.commit()


async def save_config(config: InterviewConfig) -> bool:
    db = await _get_db()
    if db is None:
        logger.error("No DB — config not saved id=%s", config.id)
        return False
    now = datetime.now(timezone.utc).isoformat()
    try:
        await db.execute(
            """
            INSERT INTO interview_configs
                (id, title, role, experience_level, job_description, total_questions,
                 core_question_ratio, jd_summary, interview_plan, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title = excluded.title,
                role = excluded.role,
                experience_level = excluded.experience_level,
                job_description = excluded.job_description,
                total_questions = excluded.total_questions,
                core_question_ratio = excluded.core_question_ratio,
                jd_summary = excluded.jd_summary,
                interview_plan = excluded.interview_plan
            """,
            (
                config.id, config.title, config.role, config.experience_level.value,
                config.job_description, config.total_questions, config.core_question_ratio,
                config.jd_summary.model_dump_json(), config.interview_plan.model_dump_json(),
                now,
            ),
        )
        await db.commit()
        logger.info("Config saved id=%s", config.id)
        return True
    except Exception as exc:
        logger.error("Failed to save config id=%s: %s", config.id, exc)
        return False


def _row_to_config(row) -> InterviewConfig:
    return InterviewConfig(
        id=row["id"],
        title=row["title"],
        role=row["role"],
        experience_level=ExperienceLevel(row["experience_level"]),
        job_description=row["job_description"],
        total_questions=row["total_questions"],
        core_question_ratio=row["core_question_ratio"],
        jd_summary=JDSummary.model_validate_json(row["jd_summary"]) if row["jd_summary"] else JDSummary(),
        interview_plan=InterviewPlan.model_validate_json(row["interview_plan"]) if row["interview_plan"] else InterviewPlan(),
        created_at=row["created_at"],
    )


async def get_config(config_id: str) -> Optional[InterviewConfig]:
    db = await _get_db()
    if db is None:
        return None
    try:
        cursor = await db.execute(
            "SELECT * FROM interview_configs WHERE id = ?", (config_id,)
        )
        row = await cursor.fetchone()
        return _row_to_config(row) if row is not None else None
    except Exception as exc:
        logger.error("Failed to read config id=%s: %s", config_id, exc)
        return None


async def list_configs(limit: int = 50, offset: int = 0) -> list[InterviewConfig]:
    db = await _get_db()
    if db is None:
        return []
    try:
        cursor = await db.execute(
            "SELECT * FROM interview_configs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        out: list[InterviewConfig] = []
        for row in rows:
            try:
                out.append(_row_to_config(row))
            except Exception as exc:
                logger.warning("Skipping malformed config row: %s", exc)
        return out
    except Exception as exc:
        logger.error("Failed to list configs: %s", exc)
        return []
