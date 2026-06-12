# MirrorTalk - SQLite 数据库初始化与基础操作
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime
from typing import Optional

from app.config import settings


def _ensure_dir() -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    _ensure_dir()
    conn = sqlite3.connect(str(settings.sqlite_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    _ensure_dir()
    conn = get_db()
    conn.executescript("""
        -- 系统配置 (key-value)
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- 记忆/知识库条目
        CREATE TABLE IF NOT EXISTS memory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL DEFAULT 'fact',
            source TEXT NOT NULL DEFAULT 'shared',
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL,
            session_id TEXT,
            confidence REAL NOT NULL DEFAULT 0.5,
            importance REAL NOT NULL DEFAULT 0.5,
            tags TEXT NOT NULL DEFAULT '[]',
            parent_id INTEGER REFERENCES memory_items(id),
            chunk_index INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- FTS5 全文索引
        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            title, content, content=memory_items, content_rowid=id
        );

        -- FTS 同步触发器
        CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory_items BEGIN
            INSERT INTO memory_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory_items BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
        END;
        CREATE TRIGGER IF NOT EXISTS memory_au AFTER UPDATE ON memory_items BEGIN
            INSERT INTO memory_fts(memory_fts, rowid, title, content) VALUES('delete', old.id, old.title, old.content);
            INSERT INTO memory_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
        END;

        -- 人格画像 (JSON 存储)
        CREATE TABLE IF NOT EXISTS personas (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            style_json TEXT NOT NULL DEFAULT '{}',
            ocean_json TEXT NOT NULL DEFAULT '{}',
            source_count INTEGER NOT NULL DEFAULT 1,
            is_aggregated INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        -- Import tasks tracking
        CREATE TABLE IF NOT EXISTS import_tasks (
            id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'running',
            phase TEXT NOT NULL DEFAULT 'uploading',
            progress_current INTEGER NOT NULL DEFAULT 0,
            progress_total INTEGER NOT NULL DEFAULT 0,
            sender_count INTEGER NOT NULL DEFAULT 0,
            profiles_created INTEGER NOT NULL DEFAULT 0,
            skipped INTEGER NOT NULL DEFAULT 0,
            result_json TEXT NOT NULL DEFAULT '{}',
            error_message TEXT,
            file_name TEXT NOT NULL DEFAULT '',
            file_path TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- 对话会话
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            persona_id TEXT NOT NULL,
            agent_type TEXT NOT NULL DEFAULT 'friend',
            title TEXT NOT NULL DEFAULT '新对话',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- 对话消息
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- ??? ? ?? ?????
        CREATE TABLE IF NOT EXISTS knowledge_persona (
            knowledge_id INTEGER NOT NULL REFERENCES memory_items(id) ON DELETE CASCADE,
            persona_id TEXT NOT NULL REFERENCES personas(id) ON DELETE CASCADE,
            synced INTEGER NOT NULL DEFAULT 0,
            synced_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (knowledge_id, persona_id)
        );

        -- ????
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        -- ?????????/?????
        CREATE TABLE IF NOT EXISTS retrieval_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id TEXT NOT NULL,
            query_text TEXT NOT NULL DEFAULT '',
            thumbs INTEGER,  -- 1=?, 0=?, NULL=???
            rating INTEGER,  -- 1-5
            clicked_ids TEXT NOT NULL DEFAULT '[]',
            session_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        
        -- A/B 实验事件追踪
        CREATE TABLE IF NOT EXISTS experiment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id TEXT NOT NULL,
            variant_name TEXT NOT NULL,
            user_id TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'impression',
            value REAL NOT NULL DEFAULT 0.0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_exp_events ON experiment_events(experiment_id, variant_name);
        CREATE INDEX IF NOT EXISTS idx_feedback_trace ON retrieval_feedback(trace_id);
        CREATE INDEX IF NOT EXISTS idx_feedback_created ON retrieval_feedback(created_at);
        -- Stage1 ??????
        CREATE TABLE IF NOT EXISTS deep_profile_cache (
            persona_id TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            segments_json TEXT NOT NULL DEFAULT '"[]"',
            silences_json TEXT NOT NULL DEFAULT '"[]"',
            message_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()

def get_deep_profile_cache(persona_id: str) -> dict | None:
    """Get cached Stage1 results for a persona."""
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM deep_profile_cache WHERE persona_id = ?",
        (persona_id,),
    ).fetchone()
    conn.close()
    if row:
        return {
            "persona_id": row["persona_id"],
            "content_hash": row["content_hash"],
            "segments": json.loads(row["segments_json"]),
            "silences": json.loads(row["silences_json"]),
            "message_count": row["message_count"],
        }
    return None


def set_deep_profile_cache(
    persona_id: str,
    content_hash: str,
    segments: list[dict],
    silences: list[dict],
    message_count: int,
) -> None:
    """Cache Stage1 results for a persona."""
    conn = get_db()
    conn.execute(
        """INSERT INTO deep_profile_cache (persona_id, content_hash, segments_json, silences_json, message_count, updated_at)
           VALUES (?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(persona_id) DO UPDATE SET
               content_hash = excluded.content_hash,
               segments_json = excluded.segments_json,
               silences_json = excluded.silences_json,
               message_count = excluded.message_count,
               updated_at = datetime('now')""",
        (
            persona_id,
            content_hash,
            json.dumps(segments, ensure_ascii=False),
            json.dumps(silences, ensure_ascii=False),
            message_count,
        ),
    )
    conn.commit()
    conn.close()




def get_config(key: str) -> Optional[str]:
    conn = get_db()
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_config(key: str, value: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO config (key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_all_config() -> dict[str, str]:
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}


def create_conversation(persona_id: str, agent_type: str = "friend", title: str = "新对话") -> str:
    conv_id = str(uuid.uuid4())[:12]
    conn = get_db()
    conn.execute(
        "INSERT INTO conversations (id, persona_id, agent_type, title) VALUES (?, ?, ?, ?)",
        (conv_id, persona_id, agent_type, title),
    )
    conn.commit()
    conn.close()
    return conv_id


def save_message(conversation_id: str, role: str, content: str) -> int:
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO messages (conversation_id, role, content) VALUES (?, ?, ?)",
        (conversation_id, role, content),
    )
    conn.execute(
        "UPDATE conversations SET updated_at = datetime('now') WHERE id = ?",
        (conversation_id,),
    )
    conn.commit()
    msg_id = cur.lastrowid
    conn.close()
    return msg_id


def load_conversation(conversation_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id",
        (conversation_id,),
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def list_conversations(persona_id: Optional[str] = None) -> list[dict]:
    conn = get_db()
    if persona_id:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE persona_id = ? ORDER BY updated_at DESC",
            (persona_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ========== ??? ? ?? ?? ==========

def bind_knowledge_to_persona(knowledge_id: int, persona_id: str) -> None:
    conn = get_db()
    conn.execute(
        "INSERT OR IGNORE INTO knowledge_persona (knowledge_id, persona_id) VALUES (?, ?)",
        (knowledge_id, persona_id),
    )
    conn.commit()
    conn.close()


def unbind_knowledge_from_persona(knowledge_id: int, persona_id: str) -> None:
    conn = get_db()
    conn.execute(
        "DELETE FROM knowledge_persona WHERE knowledge_id = ? AND persona_id = ?",
        (knowledge_id, persona_id),
    )
    conn.commit()
    conn.close()


def set_knowledge_personas(knowledge_id: int, persona_ids: list[str]) -> None:
    conn = get_db()
    conn.execute("DELETE FROM knowledge_persona WHERE knowledge_id = ?", (knowledge_id,))
    for pid in persona_ids:
        conn.execute(
            "INSERT INTO knowledge_persona (knowledge_id, persona_id) VALUES (?, ?)",
            (knowledge_id, pid),
        )
    conn.commit()
    conn.close()


def get_knowledge_personas(knowledge_id: int) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT p.id, p.name FROM knowledge_persona kp
           JOIN personas p ON p.id = kp.persona_id
           WHERE kp.knowledge_id = ?
           ORDER BY p.name""",
        (knowledge_id,),
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def get_persona_knowledge(persona_id: str) -> list[dict]:
    conn = get_db()
    rows = conn.execute(
        """SELECT m.id, m.content, m.source_type, m.title, m.confidence, m.importance,
                  kp.synced, kp.synced_at
           FROM knowledge_persona kp
           JOIN memory_items m ON m.id = kp.knowledge_id
           WHERE kp.persona_id = ?
           ORDER BY kp.created_at DESC""",
        (persona_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ========== ???? ==========

def get_sync_version() -> str:
    conn = get_db()
    row = conn.execute("SELECT value FROM sync_state WHERE key = 'sync_version'").fetchone()
    conn.close()
    return row["value"] if row else "0"


def mark_pending_sync() -> str:
    import time
    version = str(int(time.time() * 1000))
    conn = get_db()
    conn.execute(
        "INSERT INTO sync_state (key, value) VALUES ('sync_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (version,),
    )
    conn.execute("UPDATE knowledge_persona SET synced = 0, synced_at = NULL")
    conn.commit()
    conn.close()
    return version


def mark_all_synced() -> None:
    conn = get_db()
    conn.execute(
        "UPDATE knowledge_persona SET synced = 1, synced_at = datetime('now') WHERE synced = 0"
    )
    conn.commit()
    conn.close()


def save_feedback(
    trace_id: str,
    query_text: str = "",
    thumbs: bool | None = None,
    rating: int | None = None,
    clicked_ids: list[int] | None = None,
    session_id: str | None = None,
) -> int:
    """????????"""
    conn = get_db()
    cur = conn.execute(
        """INSERT INTO retrieval_feedback (trace_id, query_text, thumbs, rating, clicked_ids, session_id)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            trace_id,
            query_text,
            1 if thumbs is True else (0 if thumbs is False else None),
            rating,
            json.dumps(clicked_ids or []),
            session_id,
        ),
    )
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    return fid


def get_feedback_stats() -> dict:
    """??????"""
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM retrieval_feedback").fetchone()["c"]
    thumbs_up = conn.execute("SELECT COUNT(*) as c FROM retrieval_feedback WHERE thumbs = 1").fetchone()["c"]
    thumbs_down = conn.execute("SELECT COUNT(*) as c FROM retrieval_feedback WHERE thumbs = 0").fetchone()["c"]
    avg_rating = conn.execute("SELECT AVG(rating) as a FROM retrieval_feedback WHERE rating IS NOT NULL").fetchone()["a"]
    conn.close()
    return {
        "total_feedback": total,
        "thumbs_up": thumbs_up,
        "thumbs_down": thumbs_down,
        "thumbs_up_rate": round(thumbs_up / (thumbs_up + thumbs_down), 3) if (thumbs_up + thumbs_down) > 0 else 0.0,
        "avg_rating": round(avg_rating, 2) if avg_rating else 0.0,
    }


def has_pending_sync() -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM knowledge_persona WHERE synced = 0"
    ).fetchone()
    conn.close()
    return row["cnt"] > 0





# ========== Import Tasks CRUD ==========

def create_import_task(task_id: str, file_name: str, file_path: str | None = None) -> None:
    conn = get_db()
    conn.execute(
        "INSERT INTO import_tasks (id, status, phase, file_name, file_path) VALUES (?, 'running', 'uploading', ?, ?)",
        (task_id, file_name, file_path),
    )
    conn.commit()
    conn.close()


def update_import_task(
    task_id: str,
    status: str | None = None,
    phase: str | None = None,
    progress_current: int | None = None,
    progress_total: int | None = None,
    sender_count: int | None = None,
    profiles_created: int | None = None,
    skipped: int | None = None,
    result_json: str | None = None,
    error_message: str | None = None,
) -> None:
    conn = get_db()
    sets = []
    params = []
    if status is not None:
        sets.append("status = ?")
        params.append(status)
    if phase is not None:
        sets.append("phase = ?")
        params.append(phase)
    if progress_current is not None:
        sets.append("progress_current = ?")
        params.append(progress_current)
    if progress_total is not None:
        sets.append("progress_total = ?")
        params.append(progress_total)
    if sender_count is not None:
        sets.append("sender_count = ?")
        params.append(sender_count)
    if profiles_created is not None:
        sets.append("profiles_created = ?")
        params.append(profiles_created)
    if skipped is not None:
        sets.append("skipped = ?")
        params.append(skipped)
    if result_json is not None:
        sets.append("result_json = ?")
        params.append(result_json)
    if error_message is not None:
        sets.append("error_message = ?")
        params.append(error_message)
    sets.append("updated_at = datetime('now')")
    params.append(task_id)
    conn.execute(f"UPDATE import_tasks SET {', '.join(sets)} WHERE id = ?", params)
    conn.commit()
    conn.close()


def get_import_task(task_id: str) -> dict | None:
    conn = get_db()
    row = conn.execute("SELECT * FROM import_tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_import_tasks(status: str | None = None) -> list[dict]:
    conn = get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM import_tasks WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM import_tasks ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def cancel_import_task(task_id: str) -> bool:
    """Mark a running import task as cancelled. Returns True if cancelled."""
    conn = get_db()
    row = conn.execute("SELECT status FROM import_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        return False
    if row["status"] != "running":
        conn.close()
        return False
    conn.execute(
        "UPDATE import_tasks SET status = 'cancelled', updated_at = datetime('now') WHERE id = ?",
        (task_id,),
    )
    conn.commit()
    conn.close()
    return True


def delete_persona(persona_id: str) -> bool:
    """Delete a persona by id. Returns True if deleted, False if not found."""
    conn = get_db()
    cur = conn.execute("DELETE FROM personas WHERE id = ?", (persona_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted
