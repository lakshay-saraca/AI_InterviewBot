"""
Voice session state management in Redis.

Namespace: voice_session:{session_id} — Hash, TTL 4hr
Lock:       voice_session:{session_id}:lock — String, TTL 30s
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

VOICE_SESSION_TTL = 14400  # 4 hours
LOCK_TTL = 30

_redis_client = None
_use_memory_fallback = False


def _client():
    """Return synchronous Redis client (or None for in-memory fallback)."""
    global _redis_client, _use_memory_fallback
    if _use_memory_fallback:
        return None
    if _redis_client is not None:
        return _redis_client
    import redis as _redis  # type: ignore[import-untyped]
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        c = _redis.from_url(url, decode_responses=True, socket_connect_timeout=2)
        c.ping()
        _redis_client = c
        logger.info("Voice sessions connected to Redis at %s", url)
        return _redis_client
    except Exception as exc:
        logger.warning("Redis unavailable for voice sessions (%s), using in-memory store", exc)
        _use_memory_fallback = True
        return None


_MEMORY: dict[str, dict[str, Any]] = {}


VOICE_RUNTIME_STATES = {
    "idle",
    "bot_asking_question",
    "waiting_for_candidate_answer",
    "candidate_speaking",
    "transcribing_answer",
    "processing_answer",
    "bot_generating_response",
    "bot_speaking",
    "recovering",
    "error",
    "evaluating",
    "complete",
}

_VOICE_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"bot_asking_question", "waiting_for_candidate_answer", "error"},
    "bot_asking_question": {"bot_speaking", "waiting_for_candidate_answer", "error"},
    "waiting_for_candidate_answer": {
        "candidate_speaking",
        "transcribing_answer",
        "bot_speaking",
        "recovering",
        "evaluating",
        "error",
    },
    "candidate_speaking": {
        "candidate_speaking",
        "transcribing_answer",
        "processing_answer",
        "bot_speaking",
        "recovering",
        "error",
    },
    "transcribing_answer": {
        "candidate_speaking",
        "transcribing_answer",
        "processing_answer",
        "recovering",
        "error",
    },
    "processing_answer": {
        "candidate_speaking",
        "bot_generating_response",
        "bot_speaking",
        "recovering",
        "waiting_for_candidate_answer",
        "error",
    },
    "bot_generating_response": {
        "candidate_speaking",
        "bot_speaking",
        "recovering",
        "waiting_for_candidate_answer",
        "error",
    },
    "bot_speaking": {
        "candidate_speaking",
        "waiting_for_candidate_answer",
        "recovering",
        "evaluating",
        "complete",
        "error",
    },
    "recovering": {
        "bot_speaking",
        "waiting_for_candidate_answer",
        "processing_answer",
        "candidate_speaking",
        "error",
    },
    "error": {"recovering", "waiting_for_candidate_answer", "complete"},
    "evaluating": {"complete", "error"},
    "complete": set(),
}

_LEGACY_STATE_BY_RUNTIME = {
    "idle": "INITIALIZING",
    "bot_asking_question": "BOT_SPEAKING",
    "waiting_for_candidate_answer": "WAITING_FOR_CANDIDATE",
    "candidate_speaking": "CANDIDATE_SPEAKING",
    "transcribing_answer": "TRANSCRIBING",
    "processing_answer": "PROCESSING",
    "bot_generating_response": "PROCESSING",
    "bot_speaking": "BOT_SPEAKING",
    "recovering": "RECOVERING",
    "error": "ERROR",
    "evaluating": "EVALUATING",
    "complete": "COMPLETE",
}

_RUNTIME_BY_LEGACY_STATE = {
    "INITIALIZING": "idle",
    "WAITING_FOR_CANDIDATE": "waiting_for_candidate_answer",
    "CANDIDATE_SPEAKING": "candidate_speaking",
    "TRANSCRIBING": "transcribing_answer",
    "PROCESSING": "processing_answer",
    "BOT_SPEAKING": "bot_speaking",
    "RECOVERING": "recovering",
    "ERROR": "error",
    "EVALUATING": "evaluating",
    "COMPLETE": "complete",
}


def _key(session_id: str) -> str:
    return f"voice_session:{session_id}"


def _lock_key(session_id: str) -> str:
    return f"voice_session:{session_id}:lock"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    try:
        parsed = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _current_question_id(data: dict[str, Any]) -> str:
    questions = _safe_json_list(data.get("questions", "[]"))
    try:
        idx = int(data.get("current_question_idx", 0))
    except (TypeError, ValueError):
        return ""
    if 0 <= idx < len(questions):
        q = questions[idx]
        if isinstance(q, dict):
            return str(q.get("id", ""))
    return ""


def _runtime_from_session(data: dict[str, Any]) -> str:
    runtime = str(data.get("runtime_state", "") or "")
    if runtime in VOICE_RUNTIME_STATES:
        return runtime
    return _RUNTIME_BY_LEGACY_STATE.get(str(data.get("state", "")), "idle")


def _redact_text(text: Any, limit: int = 80) -> str:
    if text is None:
        return ""
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit]}..."


def log_voice_event(session_id: str, event: str, **fields: Any) -> None:
    """Emit a structured voice log without dumping full candidate answers."""
    data = get_voice_session(session_id) or {}
    payload: dict[str, Any] = {
        "event": event,
        "session_id": session_id,
        "current_question_id": fields.pop("question_id", None) or _current_question_id(data),
        "state": data.get("runtime_state") or _runtime_from_session(data),
        "legacy_state": data.get("state", ""),
    }
    for key, value in fields.items():
        if key in {"transcript", "text", "answer"}:
            payload[f"{key}_preview"] = _redact_text(value)
            payload[f"{key}_chars"] = len(str(value or ""))
        else:
            payload[key] = value
    logger.info("voice_event %s", json.dumps(payload, sort_keys=True))


def transition_voice_state(
    session_id: str,
    target: str,
    reason: str,
    *,
    question_id: Optional[str] = None,
    **fields: Any,
) -> str:
    """Move the voice runtime state and log the transition.

    The legacy ``state`` field is preserved for existing API/UI callers while
    ``runtime_state`` carries the explicit state-machine value.
    """
    if target not in VOICE_RUNTIME_STATES:
        raise ValueError(f"Unknown voice runtime state: {target}")

    data = get_voice_session(session_id) or {}
    previous = _runtime_from_session(data)
    allowed = target == previous or target in _VOICE_TRANSITIONS.get(previous, set())
    if not allowed:
        logger.warning(
            "voice_event %s",
            json.dumps(
                {
                    "event": "invalid_state_transition",
                    "session_id": session_id,
                    "previous_state": previous,
                    "target_state": target,
                    "reason": reason,
                    "current_question_id": question_id or _current_question_id(data),
                },
                sort_keys=True,
            ),
        )

    legacy = _LEGACY_STATE_BY_RUNTIME[target]
    set_voice_field(session_id, "runtime_state", target)
    set_voice_field(session_id, "state", legacy)
    set_voice_field(session_id, "state_updated_at", _now_iso())
    log_voice_event(
        session_id,
        "state_transition",
        previous_state=previous,
        target_state=target,
        state_transition_reason=reason,
        question_id=question_id,
        invalid_transition=not allowed,
        **fields,
    )
    return target


def reset_voice_timing(session_id: str) -> None:
    set_voice_field(session_id, "latency_marks", json.dumps({}))


def record_voice_timing(
    session_id: str,
    mark: str,
    *,
    overwrite: bool = True,
    **fields: Any,
) -> str:
    """Store and log a timestamp for the current voice pipeline turn."""
    data = get_voice_session(session_id) or {}
    marks = _safe_json_dict(data.get("latency_marks", "{}"))
    if not overwrite and mark in marks:
        return str(marks[mark])
    now = _now_iso()
    marks[mark] = now
    marks[f"{mark}_epoch_ms"] = int(time.time() * 1000)
    set_voice_field(session_id, "latency_marks", json.dumps(marks))
    log_voice_event(session_id, "timing_mark", timing_mark=mark, **fields)
    return now


def create_voice_session(
    session_id: str,
    candidate_name: str,
    job_role: str,
    experience_level: str,
    required_skills: list[str],
    questions_json: str = "[]",
    intro_text: str = "",
    ease_in_text: str = "",
    jd_summary_json: str = "{}",
) -> dict[str, Any]:
    """Create initial voice session hash in Redis."""
    now = _now_iso()

    questions = json.loads(questions_json)
    transcript: list[dict[str, str]] = []
    initial_state = "INITIALIZING"

    if questions:
        first_q_text = questions[0].get("question_text", "")
        if first_q_text:
            # Intro is its OWN questionless turn; the question turn carries the
            # ease-in lead-in then the first question. Splitting them fixes the
            # "bot asks a question in the introduction" bug.
            if intro_text:
                transcript.append({
                    "speaker": "bot",
                    "text": intro_text,
                    "timestamp": now,
                    "type": "intro",
                })
            question_text = (
                f"{ease_in_text} {first_q_text}".strip() if ease_in_text else first_q_text
            )
            transcript.append({
                "speaker": "bot",
                "text": question_text,
                "timestamp": now,
                "type": "question",
            })
            initial_state = "WAITING_FOR_CANDIDATE"

    first_question_id = questions[0].get("id", "") if questions else ""

    data: dict[str, Any] = {
        "state": initial_state,
        "runtime_state": (
            "waiting_for_candidate_answer" if questions else "idle"
        ),
        "state_updated_at": now,
        "candidate_name": candidate_name,
        "job_role": job_role,
        "experience_level": experience_level,
        "required_skills": json.dumps(required_skills),
        "questions": questions_json,
        "jd_summary": jd_summary_json,
        "current_question_idx": 0,
        "current_question_id": first_question_id,
        "current_question_status": (
            "waiting_for_answer" if questions else "not_started"
        ),
        "pending_answer_text": "",
        "pending_answer_question_id": "",
        "pending_answer_status": "",
        "latency_marks": json.dumps({}),
        "follow_up_count": 0,
        "running_scores": json.dumps({}),
        "transcript": json.dumps(transcript),
        "started_at": now,
        "turn_count": 0,
        "barge_in_count": 0,
        "silence_strikes": 0,
        "connection_state": "connected",
    }
    client = _client()
    if client:
        client.hset(_key(session_id), mapping=data)
        client.expire(_key(session_id), VOICE_SESSION_TTL)
    else:
        _MEMORY[session_id] = dict(data)
    logger.info(
        "Voice session created session=%s state=%s questions=%d",
        session_id,
        initial_state,
        len(questions),
    )
    return data


def get_voice_session(session_id: str) -> Optional[dict[str, Any]]:
    """Rehydrate full session state from Redis."""
    client = _client()
    if client:
        raw = client.hgetall(_key(session_id))
        if not raw:
            logger.warning("Voice session lookup missed session=%s", session_id)
            return None
        return raw
    session = _MEMORY.get(session_id)
    if session is None:
        logger.warning("Voice session lookup missed session=%s", session_id)
    return session


def set_voice_field(session_id: str, field: str, value: Any) -> None:
    client = _client()
    if client:
        client.hset(_key(session_id), field, value)
        client.expire(_key(session_id), VOICE_SESSION_TTL)
    elif session_id in _MEMORY:
        _MEMORY[session_id][field] = value


def increment_voice_field(session_id: str, field: str, amount: int = 1) -> int:
    client = _client()
    if client:
        result = int(client.hincrby(_key(session_id), field, amount))
        client.expire(_key(session_id), VOICE_SESSION_TTL)
        return result
    if session_id in _MEMORY:
        current = int(_MEMORY[session_id].get(field, 0))
        _MEMORY[session_id][field] = current + amount
        return current + amount
    return amount


def append_transcript_turn(
    session_id: str,
    speaker: str,
    text: str,
    entry_type: str = "candidate",
    question_id: Optional[str] = None,
) -> None:
    client = _client()
    if client:
        raw = client.hget(_key(session_id), "transcript") or "[]"
    elif session_id in _MEMORY:
        raw = _MEMORY[session_id].get("transcript", "[]")
    else:
        raw = "[]"

    turns: list = json.loads(raw)
    turn: dict = {
        "speaker": speaker,
        "text": text,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": entry_type,
    }
    if question_id is not None:
        turn["question_id"] = question_id
    turns.append(turn)
    serialized = json.dumps(turns)

    if client:
        client.hset(_key(session_id), "transcript", serialized)
    elif session_id in _MEMORY:
        _MEMORY[session_id]["transcript"] = serialized


def pause_voice_session(session_id: str) -> None:
    """On client disconnect — pause but preserve state."""
    set_voice_field(session_id, "connection_state", "paused")
    logger.info("Voice connection paused session=%s", session_id)


def resume_voice_session(session_id: str) -> None:
    set_voice_field(session_id, "connection_state", "connected")
    logger.info("Voice connection resumed session=%s", session_id)


def acquire_lock(session_id: str) -> bool:
    client = _client()
    if client:
        result = client.set(_lock_key(session_id), "1", nx=True, ex=LOCK_TTL)
        return result is not None
    return True


def release_lock(session_id: str) -> None:
    client = _client()
    if client:
        client.delete(_lock_key(session_id))
