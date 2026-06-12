# MirrorTalk - API 路由
from __future__ import annotations

import json
import logging
from typing import Optional
from pathlib import Path
import uuid
import asyncio
import os

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi import UploadFile, File, Form
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from app.agents.friend_graph import friend_graph
from app.agents.persona_graph import persona_graph
from app.agents.orchestrator import orchestrator_graph
from app.models import ChatRequest, ChatResponse, PersonaProfile, ProviderConfig, ProviderInfo, MemorySource, MemorySourceType
from app.services.database import (
    create_conversation,
    get_all_config,
    get_config,
    get_db,
    list_conversations,
    load_conversation,
    save_message,
    set_config,
    set_knowledge_personas,
    get_knowledge_personas,
    get_persona_knowledge,
    mark_pending_sync,
    mark_all_synced,
    has_pending_sync,
    get_sync_version,

    bind_knowledge_to_persona,
)
from app.services.memory import recall, insert_memory
from app.services.embedding import embed_texts_and_index
from collections import defaultdict
from app.services.provider import create_llm, list_providers
from app.pipelines.profile_builder import build_persona_pipeline
from app.pipelines.deep_profile import build_deep_profile
from app.services.stream_parser import count_and_parse_messages, normalize_message
from app.services.database import (
    create_import_task,
    update_import_task,
    get_import_task,
    list_import_tasks,
    cancel_import_task,
)
from app.services.cache import cache_lookup, cache_store
from app.services.chunking import default_chunker
from app.services.document_parser import ingest_document
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

# ========== 安全密钥 key 列表 ==========
SENSITIVE_KEYS = {"llm_api_key", "qwen_api_key", "deepseek_api_key", "openai_api_key", "ollama_api_key", "embed_remote_api_key", "rerank_remote_api_key"}


def _mask_key(value: str) -> str:
    if not value or len(value) <= 8:
        return "***"
    return value[:4] + "****" + value[-4:]


# ========== Provider ==========

@router.get("/providers", response_model=list[ProviderInfo])
async def get_providers():
    return list_providers()


@router.get("/providers/{provider_id}/models")
async def get_provider_models(provider_id: str):
    from app.services.provider import list_providers as _list_providers, get_provider_info

    prov = get_provider_info(provider_id)
    if not prov:
        return {"models": []}

    db_cfg = get_all_config()
    api_key = db_cfg.get("llm_api_key") or settings.llm_api_key
    base_url = db_cfg.get("llm_base_url") or settings.llm_base_url or prov.base_url

    if not base_url or not api_key:
        return {"models": prov.models, "fallback": True, "reason": "missing_credentials"}

    import httpx
    try:
        url = base_url.rstrip("/") + "/models"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            data = resp.json()
        models = [m["id"] for m in data.get("data", []) if "id" in m]
        return {"models": models, "fallback": False}
    except Exception:
        return {"models": prov.models, "fallback": True, "reason": "fetch_failed"}


# ========== Persona 管理 ==========

@router.get("/personas")
async def get_personas(page: int = 1, page_size: int = 20):
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as cnt FROM personas").fetchone()["cnt"]
    offset = (page - 1) * page_size
    rows = conn.execute(
        "SELECT * FROM personas ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (page_size, offset),
    ).fetchall()
    conn.close()
    return {
        "items": [{
            "id": r["id"], "name": r["name"],
            "style": json.loads(r["style_json"]),
            "ocean": json.loads(r["ocean_json"]),
            "is_aggregated": bool(r["is_aggregated"]),
            "message_count": r["source_count"],
        } for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": max(1, (total + page_size - 1) // page_size),
    }





# ========== Conversation endpoints ==========

@router.get("/conversations")
async def get_conversations(persona_id: str = "", limit: int = 10):
    """List conversations, optionally filtered by persona."""
    conn = get_db()
    if persona_id:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE persona_id = ? ORDER BY updated_at DESC LIMIT ?",
            (persona_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()

    # Enrich with last message preview
    result = []
    for r in rows:
        last_msg = conn.execute(
            "SELECT content, role FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
            (r["id"],),
        ).fetchone()
        item = dict(r)
        item["last_message"] = dict(last_msg) if last_msg else None
        result.append(item)
    conn.close()
    return {"conversations": result}


@router.get("/conversations/{conv_id}/messages")
async def get_messages(conv_id: str):
    """Get message history for a conversation."""
    conn = get_db()
    conv = conn.execute("SELECT * FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    if not conv:
        conn.close()
        raise HTTPException(404, "Conversation not found")
    rows = conn.execute(
        "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id ASC",
        (conv_id,),
    ).fetchall()
    conn.close()
    return {
        "conversation": dict(conv),
        "messages": [dict(r) for r in rows],
    }
@router.post("/personas/import")
async def import_persona(data: dict = Body(...)):
    """Upload chat JSON file, start async persona building. Returns task_id."""
    persona_id = data.get("persona_id", data.get("name", ""))
    name = data.get("name", persona_id)
    min_messages = data.get("min_messages", 5)

    # Accept either inline messages or file-based upload
    messages = data.get("messages", [])
    if messages:
        # Inline mode (small files): write to temp, process same as file upload
        import tempfile
        file_path = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ).name
        import json
        with open(file_path, "w", encoding="utf-8") as tmp:
            json.dump(messages if isinstance(messages, list) else data, tmp, ensure_ascii=False)
        file_name = f"{name}.json"
    else:
        raise HTTPException(400, "No messages provided")

    import uuid, asyncio
    task_id = uuid.uuid4().hex[:16]
    create_import_task(task_id, file_name, file_path)

    # Launch async background build
    asyncio.create_task(_run_import_task(task_id, persona_id, name, file_path, min_messages))

    return {"task_id": task_id}


@router.post("/personas/import/file")
async def import_persona_file(
    file: UploadFile = File(...),
    persona_id: str = Form(""),
    name: str = Form(""),
    min_messages: int = Form(5),
):
    """Upload a chat JSON file and start async persona building."""
    if not name:
        name = persona_id or file.filename.rsplit(".", 1)[0]
    if not persona_id:
        persona_id = name

    import tempfile, shutil, uuid, asyncio

    # Save file to data dir
    upload_dir = Path("data/uploads")
    upload_dir.mkdir(parents=True, exist_ok=True)
    task_id = uuid.uuid4().hex[:16]
    file_path = upload_dir / f"{task_id}_{file.filename}"
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    create_import_task(task_id, file.filename, str(file_path))

    asyncio.create_task(_run_import_task(task_id, persona_id, name, str(file_path), min_messages))

    return {"task_id": task_id}


# ========== Task progress endpoints ==========


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str):
    """Get import task status."""
    task = get_import_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


@router.get("/tasks/{task_id}/stream")
async def stream_task_progress(task_id: str, request: Request):
    """SSE endpoint: stream import progress events."""
    import json as _json

    task = get_import_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    async def event_stream():
        # Send current status immediately
        yield f"data: {_json.dumps({'type': 'status', 'task': task})}\n\n"

        if task["status"] != "running":
            yield f"data: {_json.dumps({'type': 'done', 'task': task})}\n\n"
            return

        # Poll for updates (every 1s)
        last_phase = task["phase"]
        last_current = task["progress_current"]
        while True:
            if await request.is_disconnected():
                break
            await asyncio.sleep(1)
            updated = get_import_task(task_id)
            if not updated:
                break
            if updated["phase"] != last_phase or updated["progress_current"] != last_current:
                yield f"data: {_json.dumps({'type': 'progress', 'task': updated})}\n\n"
                last_phase = updated["phase"]
                last_current = updated["progress_current"]
            if updated["status"] != "running":
                yield f"data: {_json.dumps({'type': 'done', 'task': updated})}\n\n"
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/tasks")
async def list_tasks(status: Optional[str] = None):
    """List import tasks."""
    tasks = list_import_tasks(status)
    return {"tasks": tasks}




# ========== 聊天记录管理 ==========

@router.get("/chat-records")
async def list_chat_records():
    """列出所有聊天记录文件（按导入任务分组）"""
    from pathlib import Path as _Path
    import json as _json

    chat_dir = _Path("data/chat_records")
    chat_dir.mkdir(parents=True, exist_ok=True)

    # 扫所有 {platformId}.jsonl 文件
    records = []
    for fpath in sorted(chat_dir.iterdir()):
        if not fpath.name.endswith(".jsonl") or fpath.name == "_timeline.jsonl" or fpath.name.startswith("_"):
            continue
        platform_id = fpath.stem
        # 读第一行取 accountName
        name = platform_id
        count = 0
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        count += 1
                        if name == platform_id:
                            try:
                                obj = _json.loads(line)
                                name = obj.get("sender", "") or obj.get("name", platform_id)
                            except _json.JSONDecodeError:
                                pass
        except Exception:
            pass
        records.append({
            "platform_id": platform_id,
            "name": name,
            "message_count": count,
            "file_size": fpath.stat().st_size,
            "has_persona": False,  # 由前端查
        })

    return {"records": sorted(records, key=lambda r: r["message_count"], reverse=True)}


@router.get("/chat-records/{platform_id}/messages")
async def stream_chat_messages(platform_id: str, request: Request):
    """SSE endpoint: 流式返回某人的聊天记录"""
    import json as _json
    from pathlib import Path as _Path

    fpath = _Path("data/chat_records") / f"{platform_id}.jsonl"
    if not fpath.exists():
        raise HTTPException(404, f"Chat record not found: {platform_id}")

    async def event_stream():
        NL = "\n"
        yield f"data: {_json.dumps({'type': 'meta', 'platform_id': platform_id, 'file': fpath.name})}{NL}{NL}"
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        obj = _json.loads(stripped)
                        yield f"data: {_json.dumps({'type': 'msg', 'data': obj})}{NL}{NL}"
                    except _json.JSONDecodeError:
                        pass
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'error': str(e)})}{NL}{NL}"
        yield f"data: {_json.dumps({'type': 'end'})}{NL}{NL}"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/chat-records/{platform_id}")
async def delete_chat_record(platform_id: str):
    """删除某个用户的聊天记录文件"""
    from pathlib import Path as _Path
    _os = __import__("os")

    fpath = _Path("data/chat_records") / f"{platform_id}.jsonl"
    if not fpath.exists():
        raise HTTPException(404, f"Chat record not found: {platform_id}")
    _os.unlink(str(fpath))
    return {"success": True, "platform_id": platform_id}


@router.get("/chat-records/timeline")
async def stream_timeline(request: Request):
    """SSE endpoint: 流式返回全量时间线"""
    import json as _json
    from pathlib import Path as _Path

    fpath = _Path("data/chat_records") / "_timeline.jsonl"
    if not fpath.exists():
        raise HTTPException(404, "Timeline not found. Import chat records first.")

    async def event_stream():
        NL = "\n"
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    try:
                        obj = _json.loads(stripped)
                        yield f"data: {_json.dumps({'type': 'msg', 'data': obj})}{NL}{NL}"
                    except _json.JSONDecodeError:
                        pass
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'error': str(e)})}{NL}{NL}"
        yield f"data: {_json.dumps({'type': 'end'})}{NL}{NL}"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ========== 按需构建画像 ==========

@router.get("/personas/by-platform/{platform_id}")
async def get_persona_by_platform(platform_id: str):
    """根据 platformId 查询是否已有画像"""
    conn = get_db()
    row = conn.execute(
        "SELECT id, name, style_json, ocean_json, message_count FROM personas WHERE id = ?",
        (platform_id,),
    ).fetchone()
    conn.close()
    if not row:
        return {"exists": False, "platform_id": platform_id}
    return {
        "exists": True,
        "platform_id": platform_id,
        "persona": {
            "id": row["id"],
            "name": row["name"],
            "style": _json.loads(row["style_json"]) if row["style_json"] else {},
            "ocean": _json.loads(row["ocean_json"]) if row["ocean_json"] else {},
            "message_count": row["message_count"] or 0,
        }
    }


@router.post("/personas/by-platform/{platform_id}/build")
async def build_persona_for_platform(platform_id: str, data: dict = Body(...)):
    """按需构建某人的画像。参数：
    {
        "name": "安卓人",          // 显示名
        "stage1_provider": "qwen", // 事实提取+风格提取的 provider
        "stage1_model": "qwen-turbo",
        "stage2_provider": "deepseek",  // 深度分析的 provider
        "stage2_model": "deepseek-chat"
    }
    """
    import json as _json, asyncio
    from pathlib import Path as _Path
    from app.pipelines.profile_builder import build_persona_pipeline
    from app.pipelines.deep_profile import build_deep_profile

    fpath = _Path("data/chat_records") / f"{platform_id}.jsonl"
    if not fpath.exists():
        raise HTTPException(404, f"Chat record not found: {platform_id}")

    name = data.get("name", platform_id)
    stage1_provider = data.get("stage1_provider", "qwen")
    stage1_model = data.get("stage1_model", "qwen-turbo")
    stage2_provider = data.get("stage2_provider", "deepseek")
    stage2_model = data.get("stage2_model", "deepseek-chat")

    # 读消息
    messages = []
    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = _json.loads(stripped)
                messages.append(obj)
            except _json.JSONDecodeError:
                pass

    if not messages:
        raise HTTPException(400, "No messages found in chat record")

    task_id = str(uuid.uuid4())[:16]

    async def _run():
        try:
            set_config(f"build_status_{platform_id}", "stage1_running")
            # Stage 1: 基础画像
            profile = await build_persona_pipeline(
                persona_id=platform_id,
                name=name,
                messages=messages,
                speaker=name,
                message_count=len(messages),
                extraction_provider=stage1_provider,
                extraction_model=stage1_model,
                style_provider=stage1_provider,
                style_model=stage1_model,
            )
            logger.info("Stage 1 complete for %s", platform_id)
            set_config(f"build_status_{platform_id}", "stage2_running")

            # Stage 2: 深度分析
            timeline_path = _Path("data/chat_records") / "_timeline.jsonl"
            deep_result = await build_deep_profile(
                persona_id=platform_id,
                name=name,
                messages=None if timeline_path.exists() else messages,
                timeline_path=str(timeline_path) if timeline_path.exists() else None,
                target_speaker=name,
                stage1_provider=stage1_provider,
                stage1_model=stage1_model,
                stage2_provider=stage2_provider,
                stage2_model=stage2_model,
            )
            set_config(f"deep_profile_{platform_id}", _json.dumps(deep_result, ensure_ascii=False))
            set_config(f"deep_profile_{platform_id}_status", "completed")
            set_config(f"build_status_{platform_id}", "completed")
            logger.info("Build complete for %s", platform_id)

        except Exception as e:
            logger.exception("Build failed for %s", platform_id)
            set_config(f"build_status_{platform_id}", f"failed: {str(e)[:200]}")
            set_config(f"deep_profile_{platform_id}_status", f"failed: {str(e)[:200]}")

    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "running"}


@router.post("/personas/by-platform/{platform_id}/build-style")
async def build_style_for_platform(platform_id: str, data: dict = Body(...)):
    """只做风格分析"""
    import json as _json, asyncio
    from pathlib import Path as _Path
    from app.pipelines.profile_builder import extract_style as _extract_style

    fpath = _Path("data/chat_records") / f"{platform_id}.jsonl"
    if not fpath.exists():
        raise HTTPException(404, f"Chat record not found: {platform_id}")

    provider = data.get("provider", "qwen")
    model = data.get("model", "qwen-turbo")
    name = data.get("name", platform_id)

    messages = []
    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = _json.loads(stripped)
                messages.append(obj)
            except _json.JSONDecodeError:
                pass

    set_config(f"style_status_{platform_id}", "running")

    async def _run():
        try:
            style = await _extract_style(messages, name, provider=provider, model=model)
            conn = get_db()
            existing = conn.execute("SELECT style_json FROM personas WHERE id = ?", (platform_id,)).fetchone()
            if existing:
                conn.execute("""UPDATE personas SET style_json = ? WHERE id = ?""",
                    (_json.dumps(style.model_dump(), ensure_ascii=False), platform_id))
            else:
                conn.execute("""INSERT INTO personas (id, name, style_json, ocean_json, is_aggregated, source_count, created_at)
                    VALUES (?, ?, ?, '{}', 0, 1, datetime('now'))""",
                    (platform_id, name, _json.dumps(style.model_dump(), ensure_ascii=False)))
            conn.commit()
            conn.close()
            set_config(f"style_status_{platform_id}", "completed")
            logger.info("Style analysis complete for %s", platform_id)
        except Exception as e:
            logger.exception("Style analysis failed for %s", platform_id)
            set_config(f"style_status_{platform_id}", f"failed: {str(e)[:200]}")

    task_id = str(uuid.uuid4())[:16]
    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "running"}


@router.post("/personas/by-platform/{platform_id}/build-facts")
async def build_facts_for_platform(platform_id: str, data: dict = Body(...)):
    """只做原子事实提取"""
    import json as _json, asyncio
    from pathlib import Path as _Path
    from app.pipelines.profile_builder import extract_atomic_facts as _extract_facts
    from app.services.memory import insert_memory
    from app.models import MemorySource, MemorySourceType

    fpath = _Path("data/chat_records") / f"{platform_id}.jsonl"
    if not fpath.exists():
        raise HTTPException(404, f"Chat record not found: {platform_id}")

    provider = data.get("provider", "qwen")
    model = data.get("model", "qwen-turbo")

    messages = []
    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = _json.loads(stripped)
                messages.append(obj)
            except _json.JSONDecodeError:
                pass

    set_config(f"facts_status_{platform_id}", "running")

    async def _run():
        try:
            facts = await _extract_facts(messages, provider=provider, model=model)
            for f in facts:
                insert_memory(
                    source_type=MemorySourceType(f.get("type", "fact")),
                    source=MemorySource.FRIEND_SPEECH,
                    content=f["content"],
                    confidence=0.7,
                    importance=0.5,
                )
            set_config(f"facts_status_{platform_id}", "completed")
            logger.info("Fact extraction complete for %s: %d facts", platform_id, len(facts))
        except Exception as e:
            logger.exception("Fact extraction failed for %s", platform_id)
            set_config(f"facts_status_{platform_id}", f"failed: {str(e)[:200]}")

    task_id = str(uuid.uuid4())[:16]
    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "running"}


@router.post("/personas/by-platform/{platform_id}/build-deep")
async def build_deep_for_platform(platform_id: str, data: dict = Body(...)):
    """只做深度画像分析（只用该用户本人消息，不用时间线）"""
    import json as _json, asyncio
    from pathlib import Path as _Path
    from app.pipelines.deep_profile import build_deep_profile as _build_deep

    fpath = _Path("data/chat_records") / f"{platform_id}.jsonl"
    if not fpath.exists():
        raise HTTPException(404, f"Chat record not found: {platform_id}")

    stage1_provider = data.get("stage1_provider", "qwen")
    stage1_model = data.get("stage1_model", "qwen-turbo")
    stage2_provider = data.get("stage2_provider", "deepseek")
    stage2_model = data.get("stage2_model", "deepseek-chat")
    name = data.get("name", platform_id)

    messages = []
    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = _json.loads(stripped)
                messages.append(obj)
            except _json.JSONDecodeError:
                pass

    # 先同步设置状态，确保前端轮询能立即看到
    set_config(f"deep_profile_{platform_id}_status", "running")

    async def _run():
        try:
            result = await _build_deep(
                persona_id=platform_id,
                name=name,
                messages=messages,
                timeline_path=None,
                target_speaker=name,
                stage1_provider=stage1_provider,
                stage1_model=stage1_model,
                stage2_provider=stage2_provider,
                stage2_model=stage2_model,
            )
            set_config(f"deep_profile_{platform_id}", _json.dumps(result, ensure_ascii=False))
            set_config(f"deep_profile_{platform_id}_status", "completed")
            logger.info("Deep profile complete for %s", platform_id)
        except Exception as e:
            logger.exception("Deep profile failed for %s", platform_id)
            set_config(f"deep_profile_{platform_id}_status", f"failed: {str(e)[:200]}")

    task_id = str(uuid.uuid4())[:16]
    asyncio.create_task(_run())
    return {"task_id": task_id, "status": "running"}


@router.get("/personas/by-platform/{platform_id}/build-status")

async def get_persona_build_status(platform_id: str):
    """查询某人的画像构建状态（style / facts / deep 三种独立状态）"""
    import json as _json

    style_status = get_config(f"style_status_{platform_id}") or "not_started"
    facts_status = get_config(f"facts_status_{platform_id}") or "not_started"
    deep_status = get_config(f"deep_profile_{platform_id}_status") or "not_started"
    deep_raw = get_config(f"deep_profile_{platform_id}")

    # 检查 personas 表是否有基础画像
    conn = get_db()
    row = conn.execute("SELECT id, style_json, ocean_json FROM personas WHERE id = ?", (platform_id,)).fetchone()
    conn.close()

    stage1_done = row is not None
    stage2_done = deep_status == "completed"

    return {
        "platform_id": platform_id,
        "style_status": style_status,
        "facts_status": facts_status,
        "deep_status": deep_status,
        "stage1_complete": stage1_done,
        "stage2_complete": stage2_done,
        "persona": {
            "style": _json.loads(row["style_json"]) if row and row["style_json"] else {},
            "ocean": _json.loads(row["ocean_json"]) if row and row["ocean_json"] else {},
        } if row else None,
    }

@router.get("/providers/available")
async def get_available_providers():
    """返回可用的 provider 列表（用于前端构建画像时的模型选择）"""
    from app.config import settings as _settings
    db_cfg = get_all_config()
    providers_list = []

    for pid in ["ollama", "qwen", "deepseek"]:
        api_key = db_cfg.get(f"{pid}_api_key") or getattr(_settings, f"{pid}_api_key", "") or ""
        base_url = db_cfg.get(f"{pid}_base_url") or getattr(_settings, f"{pid}_base_url", "") or ""
        model = db_cfg.get(f"{pid}_model") or getattr(_settings, f"{pid}_model", "") or ""
        providers_list.append({
            "id": pid,
            "name": {"ollama": "Ollama", "qwen": "通义千问", "deepseek": "DeepSeek"}.get(pid, pid),
            "has_api_key": bool(api_key) or pid == "ollama",
            "default_base_url": base_url,
            "default_model": model,
        })

    return {"providers": providers_list}

@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    persona_id: str = Form(...),
    source_label: str = Form(""),
):
    """"上传文档并摄入知识库。支持 TXT/MD/PDF/DOCX/PNG/JPG。"""
    if not file.filename:
        raise HTTPException(400, "文件名不能为空")

    ext = Path(file.filename).suffix.lower()
    from app.services.document_parser import SUPPORTED_EXTENSIONS
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"不支持的文件类型: {ext}；支持: {SUPPORTED_EXTENSIONS}")

    # 保存到临时目录
    tmp_dir = settings.data_dir / "uploads"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{uuid.uuid4().hex}_{file.filename}"
    content = await file.read()
    tmp_path.write_bytes(content)

    label = source_label or file.filename
    try:
        result = await ingest_document(str(tmp_path), persona_id, label)
        return result
    except Exception as e:
        logger.error("文档摄入失败: %s", e)
        raise HTTPException(500, f"文档处理失败: {str(e)}")
    finally:
        # 清理临时文件
        try:
            tmp_path.unlink()
        except Exception:
            pass


# ========== A/B 实验 ==========

@router.get("/experiments")
async def list_experiments():
    """"列出所有注册的实验"""
    from app.services.experiment import list_experiments as _list_exps
    exps = _list_exps()
    return [{
        "id": e.id, "name": e.name, "enabled": e.enabled,
        "traffic_pct": e.traffic_pct,
        "variants": [{"name": v.name, "weight": v.weight, "description": v.description} for v in e.variants],
    } for e in exps]


@router.get("/experiments/{exp_id}/stats")
async def get_experiment_stats(exp_id: str):
    """"查询实验统计数据（转化率、延迟等）"""
    from app.services.experiment import get_experiment_stats
    return get_experiment_stats(exp_id)


# ========== 健康检查 ==========

@router.get("/health")
async def health_check():
    """"三依赖健康检测：SQLite + ChromaDB + LLM"""
    from fastapi.responses import JSONResponse

    checks = {}

    # 1. SQLite
    try:
        conn = get_db()
        conn.execute("SELECT 1")
        conn.close()
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {str(e)[:100]}"

    # 2. ChromaDB
    try:
        from app.services.memory import _get_collection
        col = _get_collection()
        col.count()
        checks["chromadb"] = "ok"
    except Exception as e:
        checks["chromadb"] = f"error: {str(e)[:100]}"

    # 3. LLM Provider
    try:
        llm = create_llm(ProviderConfig())
        await llm.ainvoke([HumanMessage(content="ping")])
        checks["llm"] = "ok"
    except Exception as e:
        checks["llm"] = "unavailable"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=200 if all_ok else 503,
    )


# ========== GraphRAG 知识图谱 ==========

@router.post("/graph/build")
async def build_knowledge_graph(data: dict):
    """"从知识库批量构建知识图谱"""
    persona_id = data.get("persona_id", "")
    conn = get_db()
    if persona_id:
        rows = conn.execute(
            "SELECT * FROM memory_items WHERE id IN (SELECT knowledge_id FROM knowledge_persona WHERE persona_id = ?) ORDER BY id DESC LIMIT 200",
            (persona_id,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM memory_items ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()

    from app.services.graph_rag import build_graph_from_memories
    from app.services.memory import _row_to_item

    items = [_row_to_item(r) for r in rows]
    added = await build_graph_from_memories(items)
    stats = graph_stats()
    return {"success": True, "added_edges": added, "graph_stats": stats}


@router.get("/graph/stats")
async def get_graph_stats():
    """"获取知识图谱统计信息"""
    from app.services.graph_rag import graph_stats
    return graph_stats()


@router.post("/graph/search")
async def search_knowledge_graph(data: dict):
    """"图遍历检索"""
    entities = data.get("entities", [])
    max_hops = data.get("max_hops", 2)
    results = graph_search(entities, max_hops=max_hops)
    return {"results": results, "formatted": format_graph_results(results)}


# ========== 多智能体协作 ==========

@router.post("/chat/collaborative/stream")
async def chat_collaborative_stream(req: ChatRequest):
    """"多智能体协作：friend agent + persona agent 联合分析"""
    conn = get_db()
    row = conn.execute("SELECT * FROM personas WHERE id = ?", (req.persona_id,)).fetchone()
    agg_row = conn.execute("SELECT * FROM personas WHERE is_aggregated = 1 LIMIT 1").fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"Persona not found: {req.persona_id}")

    persona = {"name": row["name"], "style_json": row["style_json"], "ocean_json": row["ocean_json"]}
    aggregated = {}
    if agg_row:
        aggregated = {"name": agg_row["name"], "style_json": agg_row["style_json"], "ocean_json": agg_row["ocean_json"]}

    conv_id = req.conversation_id or create_conversation(req.persona_id, "collaborative")
    save_message(conv_id, "user", req.message)

    state = {
        "messages": [HumanMessage(content=req.message)],
        "persona": persona,
        "friend_persona": persona,
        "aggregated": aggregated,
        "provider_config": {"provider": _resolve_provider()},
        "final_reply": None,
    }

    async def event_stream():
        cached = await cache_lookup(req.message, req.persona_id)
        if cached:
            save_message(conv_id, "assistant", cached["reply"])
            import json as _json
            end_data = _json.dumps({"type": "end", "data": {"conversation_id": conv_id, "reply": cached["reply"], "cached": True}})
            yield f"data: {end_data}" + NL + NL
            return

        full_reply = ""
        try:
            async for event in orchestrator_graph.astream_events(state, version="v1"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", None)
                    if chunk and hasattr(chunk, "content"):
                        token = chunk.content or ""
                        if token:
                            full_reply += token
                            yield f"data: {token}" + NL + NL
        except Exception as e:
            logger.error("Collab streaming error: %s", e)
        finally:
            save_message(conv_id, "assistant", full_reply)
            end_data = json.dumps({"type": "end", "data": {"conversation_id": conv_id, "reply": full_reply}}, ensure_ascii=False)
            yield f"data: {end_data}" + NL + NL

    return StreamingResponse(event_stream(), media_type="text/event-stream")

# ========== 对话 ==========

@router.get("/conversations")
async def get_conversations(persona_id: Optional[str] = None):
    return list_conversations(persona_id)


@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    msgs = load_conversation(conversation_id)
    if not msgs:
        raise HTTPException(404, "对话不存在")
    return {"id": conversation_id, "messages": msgs}


# ========== 聊天 ==========

@router.post("/chat/friend")
async def chat_friend(req: ChatRequest):
    """与虚拟好友对话"""
    conn = get_db()
    row = conn.execute("SELECT * FROM personas WHERE id = ?", (req.persona_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"未找到好友画像: {req.persona_id}")

    persona = {"name": row["name"], "style_json": row["style_json"], "ocean_json": row["ocean_json"]}

    conv_id = req.conversation_id or create_conversation(req.persona_id, "friend")
    save_message(conv_id, "user", req.message)

    state = {
        "messages": [HumanMessage(content=req.message)],
        "persona": persona,
        "provider_config": {"provider": _resolve_provider()},
        "persona_check": None,
        "final_reply": None,
        "tool_call_history": [],
        "structured_tools_used": False,
        "review_result": None,
    }

    result = await friend_graph.ainvoke(state)
    reply = result.get("final_reply", "") or result["messages"][-1].content
    save_message(conv_id, "assistant", reply)

    return ChatResponse(
        conversation_id=conv_id,
        reply=reply,
        persona_check=result.get("persona_check"),
    )


@router.post("/chat/persona")
async def chat_persona(req: ChatRequest):
    """用户替身生成回复"""
    conn = get_db()
    row = conn.execute("SELECT * FROM personas WHERE id = ?", (req.persona_id,)).fetchone()
    agg_row = conn.execute("SELECT * FROM personas WHERE is_aggregated = 1 LIMIT 1").fetchone()
    conn.close()

    if not row:
        raise HTTPException(404, f"未找到替身画像: {req.persona_id}")

    persona = {"name": row["name"], "style_json": row["style_json"], "ocean_json": row["ocean_json"]}
    aggregated = {}
    if agg_row:
        aggregated = {"name": agg_row["name"], "style_json": agg_row["style_json"], "ocean_json": agg_row["ocean_json"]}

    conv_id = req.conversation_id or create_conversation(req.persona_id, "persona")
    save_message(conv_id, "user", req.message)

    state = {
        "messages": [HumanMessage(content=req.message)],
        "persona": persona,
        "aggregated": aggregated,
        "provider_config": {"provider": _resolve_provider()},
        "persona_check": None,
        "final_reply": None,
        "tool_call_history": [],
        "structured_tools_used": False,
        "review_result": None,
    }

    result = await persona_graph.ainvoke(state)
    reply = result.get("final_reply", "") or result["messages"][-1].content
    save_message(conv_id, "assistant", reply)

    return ChatResponse(
        conversation_id=conv_id,
        reply=reply,
        persona_check=result.get("persona_check"),
    )


# ========== 知识库 ==========

@router.get("/memories")
async def get_memories(
    persona_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    conn = get_db()
    if persona_id:
        rows = conn.execute(
            "SELECT * FROM memory_items WHERE session_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
            (persona_id, limit, offset),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM memory_items ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    conn.close()
    return [{
        "id": r["id"], "source_type": r["source_type"], "source": r["source"],
        "content": r["content"], "confidence": r["confidence"],
        "importance": r["importance"], "tags": json.loads(r["tags"]),
    } for r in rows]


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int):
    conn = get_db()
    conn.execute("DELETE FROM memory_items WHERE id = ?", (memory_id,))
    conn.commit()
    conn.close()
    return {"success": True}


# ========== 配置 ==========

def _build_config_response() -> dict:
    """构建完整配置响应，密钥脱敏。优先 DB，其次 .env 按 provider 分类的字段，最后通用 fallback。"""
    db_cfg = get_all_config()

    def _val(key: str, *fallbacks: str) -> str:
        """链式取值: DB -> 各 fallback settings -> 空字符串"""
        v = db_cfg.get(key)
        if v:
            return v
        for fb in fallbacks:
            if fb:
                return fb
        return ""

    def _set_flag(key: str, *fallbacks: str) -> bool:
        return bool(db_cfg.get(key) or any(fb for fb in fallbacks))

    response = {
        "llm_provider": db_cfg.get("llm_provider") or settings.llm_provider,
        # Qwen
        "qwen_api_key": _val("qwen_api_key", settings.qwen_api_key, settings.llm_api_key),
        "qwen_api_key_set": _set_flag("qwen_api_key", settings.qwen_api_key, settings.llm_api_key),
        "qwen_base_url": _val("qwen_base_url", settings.qwen_base_url, settings.llm_base_url),
        "qwen_model": _val("qwen_model", settings.qwen_model, settings.llm_model),
        # DeepSeek
        "deepseek_api_key": _val("deepseek_api_key", settings.deepseek_api_key, settings.llm_api_key),
        "deepseek_api_key_set": _set_flag("deepseek_api_key", settings.deepseek_api_key, settings.llm_api_key),
        "deepseek_base_url": _val("deepseek_base_url", settings.deepseek_base_url, settings.llm_base_url),
        "deepseek_model": _val("deepseek_model", settings.deepseek_model, settings.llm_model),
        # Ollama
        "ollama_api_key": _val("ollama_api_key", settings.ollama_api_key),
        "ollama_api_key_set": _set_flag("ollama_api_key", settings.ollama_api_key),
        "ollama_base_url": _val("ollama_base_url", settings.ollama_base_url),
        "ollama_model": _val("ollama_model", settings.ollama_model),
        # Legacy 通用字段（兼容旧前端 / 内部使用）
        "llm_api_key": _val("llm_api_key", settings.llm_api_key),
        "llm_api_key_set": _set_flag("llm_api_key", settings.llm_api_key),
        "llm_base_url": _val("llm_base_url", settings.llm_base_url),
        "llm_model": _val("llm_model", settings.llm_model),
        # Embedding
        "embed_mode": _val("embed_mode", settings.embed_mode),
        "embed_remote_provider": _val("embed_remote_provider", settings.embed_remote_provider),
        "embed_remote_model": _val("embed_remote_model", settings.embed_remote_model),
        "embed_remote_base_url": _val("embed_remote_base_url", settings.embed_remote_base_url),
        "embed_remote_api_key": _val("embed_remote_api_key", settings.embed_remote_api_key),
        "embed_remote_api_key_set": _set_flag("embed_remote_api_key", settings.embed_remote_api_key),
        # Rerank
        "rerank_mode": _val("rerank_mode", settings.rerank_mode),
        "rerank_remote_provider": _val("rerank_remote_provider", settings.rerank_remote_provider),
        "rerank_remote_model": _val("rerank_remote_model", settings.rerank_remote_model),
        "rerank_remote_base_url": _val("rerank_remote_base_url", settings.rerank_remote_base_url),
        "rerank_remote_api_key": _val("rerank_remote_api_key", settings.rerank_remote_api_key),
        "rerank_remote_api_key_set": _set_flag("rerank_remote_api_key", settings.rerank_remote_api_key),
    }
    return response


@router.get("/config")
async def get_config_endpoint():
    return _build_config_response()


@router.put("/config")
async def update_config(data: dict):
    """更新配置。密钥字段传真实值时更新，传空字符串或脱敏值时不更新。"""
    allowed_keys = {
        "llm_provider", "llm_model", "llm_base_url",
        "llm_api_key", "qwen_api_key", "deepseek_api_key", "openai_api_key", "ollama_api_key",
        "qwen_base_url", "qwen_model",
        "deepseek_base_url", "deepseek_model",
        "ollama_base_url", "ollama_model",
        "embed_mode", "embed_remote_provider", "embed_remote_model", "embed_remote_base_url",
        "embed_remote_api_key",
        "rerank_mode", "rerank_remote_provider", "rerank_remote_model", "rerank_remote_base_url",
        "rerank_remote_api_key",
    }

    for key, value in data.items():
        if key not in allowed_keys:
            continue
        if key in SENSITIVE_KEYS:
            # 密钥: 只保存非空且非脱敏值(不含****)
            if value and isinstance(value, str) and "****" not in value and value.strip():
                set_config(key, value.strip())
        else:
            if value and isinstance(value, str) and value.strip():
                set_config(key, value.strip())

    return _build_config_response()


@router.post("/config/test-connection")
async def test_llm_connection(data: dict):
    """Test LLM connection with given provider config. Returns latency & status."""
    import time, logging
    logger = logging.getLogger(__name__)

    provider = (data.get("provider") or "").strip()
    base_url = (data.get("base_url") or "").strip()
    model = (data.get("model") or "").strip()
    api_key = (data.get("api_key") or "").strip()

    if not provider or not model:
        return {"status": "error", "error": "provider and model are required", "latency_ms": 0}

    config = ProviderConfig(provider=provider, model=model, base_url=base_url, api_key=api_key)
    try:
        llm = create_llm(config)
        start = time.time()
        resp = await llm.ainvoke([HumanMessage(content="ping")])
        latency = round((time.time() - start) * 1000)
        return {"status": "ok", "latency_ms": latency, "response": str(resp.content)[:50]}
    except Exception as e:
        err_msg = str(e)[:200]
        logger.warning("Test connection %s/%s failed: %s", provider, model, err_msg)
        return {"status": "error", "error": err_msg, "latency_ms": 0}



@router.post("/check-providers")
async def check_all_providers():
    """Check connectivity for all configured providers (ollama, deepseek, qwen).
    Returns latency/status for each, without blocking import."""
    import time, logging, asyncio
    logger = logging.getLogger(__name__)

    providers_to_check = [
        ("qwen", "qwen-turbo"),
        ("deepseek", "deepseek-chat"),
        ("ollama", "qwen2.5:7b"),
    ]

    results = {}
    for provider_id, model in providers_to_check:
        try:
            cfg = ProviderConfig(provider=provider_id, model=model)
            llm = create_llm(cfg)
            start = time.time()
            await llm.ainvoke([HumanMessage(content="ping")])
            latency = round((time.time() - start) * 1000)
            results[provider_id] = {"status": "ok", "latency_ms": latency}
        except Exception as e:
            err = str(e)[:150]
            results[provider_id] = {"status": "error", "error": err}

    return {"providers": results}

@router.get("/config/export")
async def export_config():
    """Export all config as JSON for backup/migration."""
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM config").fetchall()
    conn.close()
    data = {}
    for r in rows:
        data[r["key"]] = r["value"]
    return data


@router.post("/config/import")
async def import_config(data: dict):
    """Import config from JSON backup. Returns count of restored keys."""
    allowed_keys = {
        "llm_provider", "llm_model", "llm_base_url",
        "llm_api_key", "qwen_api_key", "deepseek_api_key", "openai_api_key", "ollama_api_key",
        "qwen_base_url", "qwen_model",
        "deepseek_base_url", "deepseek_model",
        "ollama_base_url", "ollama_model",
        "embed_mode", "embed_remote_provider", "embed_remote_model", "embed_remote_base_url",
        "embed_remote_api_key",
        "rerank_mode", "rerank_remote_provider", "rerank_remote_model", "rerank_remote_base_url",
        "rerank_remote_api_key",
    }
    imported = 0
    for key, value in data.items():
        if key in allowed_keys and value and isinstance(value, str):
            set_config(key, value.strip())
            imported += 1
    return {"imported": imported}


# ========== 知识库导入 ==========

@router.post("/knowledge/import")
async def import_knowledge(data: dict):
    """导入外部文件为知识库条目"""
    try:
        content_text = data.get("content", "")
        title = data.get("title", "导入知识")
        source = data.get("source", "external_file")
        persona_ids = data.get("persona_ids", [])

        if not content_text.strip():
            raise HTTPException(400, "内容不能为空")

        result = default_chunker.chunk_text(content_text)

        inserted_ids = []
        for i, chunk in enumerate(result.chunks):
            parent_id = result.chunk_to_parent[i]
            mem_id = insert_memory(
                source_type=MemorySourceType("external"),
                source=MemorySource(source),
                content=chunk,
                title=title if len(result.chunks) == 1 else title + " - 片段" + str(i + 1),
                confidence=0.8,
                importance=0.7,
                parent_id=parent_id,
                chunk_index=i,
                chunk_count=len(result.chunks),
            )
            inserted_ids.append(mem_id)
            for pid in persona_ids:
                bind_knowledge_to_persona(mem_id, pid)

        import asyncio
        asyncio.create_task(_index_knowledge_to_vector(inserted_ids))

        return {"success": True, "count": len(inserted_ids), "ids": inserted_ids}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("知识导入失败: %s", e, exc_info=True)
        raise HTTPException(500, f"导入失败: {str(e)}")
async def _index_knowledge_to_vector(memory_ids: list[int]):
    try:
        texts = []
        conn = get_db()
        placeholders = ",".join("?" for _ in memory_ids)
        rows = conn.execute(
            "SELECT id, content FROM memory_items WHERE id IN (" + placeholders + ")",
            memory_ids,
        ).fetchall()
        conn.close()
        for r in rows:
            texts.append(r["content"])
        if texts:
            await embed_texts_and_index(texts, [str(i) for i in memory_ids])
    except Exception as e:
        logger.warning("向量索引失败: %s", e)


# ========== 知识库 ↔ 画像 绑定 ==========

@router.get("/knowledge/{knowledge_id}/personas")
async def get_personas_for_knowledge(knowledge_id: int):
    return get_knowledge_personas(knowledge_id)


@router.put("/knowledge/{knowledge_id}/personas")
async def update_knowledge_personas(knowledge_id: int, data: dict):
    persona_ids = data.get("persona_ids", [])
    set_knowledge_personas(knowledge_id, persona_ids)
    return {"success": True}


@router.get("/personas/{persona_id}/knowledge")
async def get_knowledge_for_persona(persona_id: str):
    return get_persona_knowledge(persona_id)



# ========== ?????? ==========

@router.post("/personas/{persona_id}/deep-profile")
async def trigger_deep_profile(persona_id: str):
    """Trigger deep psychological profile analysis. Runs async, returns status."""
    import asyncio, uuid, glob as _glob, os as _os

    conn = get_db()
    row = conn.execute("SELECT id, name FROM personas WHERE id = ?", (persona_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Persona not found")

    # Find most recent timeline file
    timeline_files = sorted(
        _glob.glob("data/tmp/*_timeline.jsonl"),
        key=lambda p: _os.path.getmtime(p),
        reverse=True,
    )
    timeline_path = timeline_files[0] if timeline_files else None

    # Fallback: get messages from memory_items
    conn = get_db()
    msg_rows = conn.execute(
        "SELECT content FROM memory_items LIMIT 5000"
    ).fetchall()
    conn.close()
    messages = [{"sender": "unknown", "content": r["content"]} for r in msg_rows]

    if not messages and not timeline_path:
        raise HTTPException(400, "No messages or timeline found. Import data first.")

    task_id = uuid.uuid4().hex[:16]
    set_config(f"deep_profile_{persona_id}_status", "running")

    async def _run():
        try:
            result = await build_deep_profile(
                persona_id=persona_id,
                name=row["name"],
                messages=messages if not timeline_path else None,
                timeline_path=timeline_path,
                target_speaker=row["name"],
            )
            import json as _json
            set_config(
                f"deep_profile_{persona_id}",
                _json.dumps(result, ensure_ascii=False),
            )
            set_config(f"deep_profile_{persona_id}_status", "completed")
        except Exception as e:
            logger.error("Deep profile failed for %s: %s", persona_id, e)
            set_config(f"deep_profile_{persona_id}_status", f"failed: {str(e)[:200]}")

    asyncio.create_task(_run())
    return {"persona_id": persona_id, "task_id": task_id, "status": "running"}


@router.get("/personas/{persona_id}/deep-profile")
async def get_deep_profile(persona_id: str):
    """Get deep profile analysis result."""
    import json as _json

    status = get_config(f"deep_profile_{persona_id}_status") or "not_started"
    raw = get_config(f"deep_profile_{persona_id}")

    if status == "not_started":
        return {"persona_id": persona_id, "status": "not_started"}
    if status == "running":
        return {"persona_id": persona_id, "status": "running"}
    if status.startswith("failed"):
        return {"persona_id": persona_id, "status": "failed", "error": status}
    if raw:
        try:
            data = _json.loads(raw)
            return {"persona_id": persona_id, "status": "completed", **data}
        except _json.JSONDecodeError:
            return {"persona_id": persona_id, "status": "failed", "error": "JSON decode error"}
    return {"persona_id": persona_id, "status": "not_found"}


# ========== 同步至 Agent ==========

@router.delete("/personas/{persona_id}")
async def delete_persona_endpoint(persona_id: str):
    """Delete a persona profile."""
    # Also delete related knowledge bindings
    from app.services.database import get_db as _get_db
    conn = _get_db()
    conn.execute("DELETE FROM knowledge_persona WHERE persona_id = ?", (persona_id,))
    conn.commit()
    conn.close()
    ok = delete_persona(persona_id)
    if not ok:
        raise HTTPException(404, "Persona not found")
    return {"success": True, "persona_id": persona_id}


@router.post("/knowledge/sync-to-agent")
async def sync_knowledge_to_agent():
    version = mark_pending_sync()
    import asyncio
    asyncio.create_task(_do_sync())
    return {"success": True, "version": version}


async def _do_sync():
    try:
        conn = get_db()
        rows = conn.execute(
            """SELECT kp.knowledge_id, kp.persona_id, m.content
               FROM knowledge_persona kp
               JOIN memory_items m ON m.id = kp.knowledge_id
               WHERE kp.synced = 0"""
        ).fetchall()
        conn.close()

        if not rows:
            mark_all_synced()
            return

        groups = defaultdict(list)
        for r in rows:
            groups[r["knowledge_id"]].append({
                "persona_id": r["persona_id"],
                "content": r["content"],
            })

        import chromadb
        from app.config import settings as app_settings
        client = chromadb.PersistentClient(
            path=str(app_settings.chroma_dir),
            settings=chromadb.config.Settings(anonymized_telemetry=False),
        )
        collection = client.get_or_create_collection(
            name="memory_items",
            metadata={"hnsw:space": "cosine"},
        )

        for kid, bindings in groups.items():
            pids = ",".join(b["persona_id"] for b in bindings)
            collection.update(
                ids=[str(kid)],
                metadatas=[{"persona_ids": pids}],
            )

        mark_all_synced()
        logger.info("同步完成: %d 条绑定", len(rows))
    except Exception as e:
        logger.error("同步失败: %s", e)


@router.get("/knowledge/sync-status")
async def get_sync_status():
    return {
        "pending": has_pending_sync(),
        "version": get_sync_version(),
    }




# ========== ??????? ==========

@router.post("/feedback")
async def submit_feedback(data: dict):
    """????????????????"""
    from app.services.database import save_feedback as _save_feedback

    trace_id = data.get("trace_id", "")
    if not trace_id:
        raise HTTPException(400, "trace_id ????")

    fid = _save_feedback(
        trace_id=trace_id,
        query_text=data.get("query_text", ""),
        thumbs=data.get("thumbs"),
        rating=data.get("rating"),
        clicked_ids=data.get("clicked_ids"),
        session_id=data.get("session_id"),
    )
    return {"success": True, "feedback_id": fid}


@router.get("/metrics/retrieval")
async def get_retrieval_metrics():
    """????????"""
    from app.services.memory import get_retrieval_stats
    from app.services.database import get_feedback_stats

    return {
        "retrieval": get_retrieval_stats(),
        "feedback": get_feedback_stats(),
    }

def _resolve_provider() -> str:
    """解析当前有效的 provider"""
    db_cfg = get_all_config()
    return db_cfg.get("llm_provider") or settings.llm_provider

# ========== Stream Chat ==========

@router.post("/chat/friend/stream")
async def chat_friend_stream(req: ChatRequest):
    conn = get_db()
    row = conn.execute("SELECT * FROM personas WHERE id = ?", (req.persona_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"Friend persona not found: {req.persona_id}")

    persona = {"name": row["name"], "style_json": row["style_json"], "ocean_json": row["ocean_json"]}
    conv_id = req.conversation_id or create_conversation(req.persona_id, "friend")
    save_message(conv_id, "user", req.message)

    state = {
        "messages": [HumanMessage(content=req.message)],
        "persona": persona,
        "provider_config": {"provider": _resolve_provider()},
        "persona_check": None,
        "final_reply": None,
        "tool_call_history": [],
        "structured_tools_used": False,
        "review_result": None,
    }

    async def event_stream():
        """SSE event generator using LangGraph astream_events"""
        # ---- Semantic Cache Lookup ----
        cached = await cache_lookup(req.message, req.persona_id)
        if cached:
            save_message(conv_id, "assistant", cached["reply"])
            import json as _json
            end_data = _json.dumps({"type": "end", "data": {"conversation_id": conv_id, "reply": cached["reply"], "cached": True}})
            yield f"data: {end_data}" + NL + NL
            return
        full_reply = ""
        try:
            async for event in friend_graph.astream_events(state, version="v1"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", None)
                    if chunk and hasattr(chunk, "content"):
                        token = chunk.content or ""
                        if token:
                            full_reply += token
                            yield f"data: {token}" + NL + NL
                            # -- 流式增量安全检测 (每 25 token) --
                            if len(full_reply) % 25 == 0 and len(full_reply) >= 25:
                                from app.services.safety import check_output_safety
                                inc_check = check_output_safety(full_reply)
                                if not inc_check.passed:
                                    logger.warning("流式 Guard 拦截: 输出异常中断")
                                    yield f"data: [回复已中断 - 安全检测]" + NL + NL
                                    break  # 终止流
            logger.error("Streaming error: %s", e)
        finally:
            save_message(conv_id, "assistant", full_reply)
            end_data = json.dumps({"type": "end", "data": {"conversation_id": conv_id, "reply": full_reply}}, ensure_ascii=False)
            yield f"data: {end_data}" + NL + NL

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@router.post("/chat/persona/stream")
async def chat_persona_stream(req: ChatRequest):
    conn = get_db()
    row = conn.execute("SELECT * FROM personas WHERE id = ?", (req.persona_id,)).fetchone()
    agg_row = conn.execute("SELECT * FROM personas WHERE is_aggregated = 1 LIMIT 1").fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, f"Persona not found: {req.persona_id}")

    persona = {"name": row["name"], "style_json": row["style_json"], "ocean_json": row["ocean_json"]}
    aggregated = {}
    if agg_row:
        aggregated = {"name": agg_row["name"], "style_json": agg_row["style_json"], "ocean_json": agg_row["ocean_json"]}
    conv_id = req.conversation_id or create_conversation(req.persona_id, "persona")
    save_message(conv_id, "user", req.message)

    state = {
        "messages": [HumanMessage(content=req.message)],
        "persona": persona,
        "aggregated": aggregated,
        "provider_config": {"provider": _resolve_provider()},
        "persona_check": None,
        "final_reply": None,
        "tool_call_history": [],
        "structured_tools_used": False,
        "review_result": None,
    }

    async def event_stream():
        """SSE event generator using LangGraph astream_events"""
        cached = await cache_lookup(req.message, req.persona_id)
        if cached:
            save_message(conv_id, "assistant", cached["reply"])
            import json as _json
            end_data = _json.dumps({"type": "end", "data": {"conversation_id": conv_id, "reply": cached["reply"], "cached": True}})
            yield f"data: {end_data}" + NL + NL
            return
        full_reply = ""
        try:
            async for event in persona_graph.astream_events(state, version="v1"):
                kind = event.get("event")
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", None)
                    if chunk and hasattr(chunk, "content"):
                        token = chunk.content or ""

            logger.error("Streaming error: %s", e)
        finally:
            save_message(conv_id, "assistant", full_reply)
            end_data = json.dumps({"type": "end", "data": {"conversation_id": conv_id, "reply": full_reply}}, ensure_ascii=False)
            yield f"data: {end_data}" + NL + NL

    return StreamingResponse(event_stream(), media_type="text/event-stream")











# ========== Background import task runner ==========

async def _run_import_task(
    task_id: str,
    persona_id: str,
    name: str,
    file_path: str,
    min_messages: int = 5,
):
    """Background task: parse JSONL, split by sender, write to chat_records/.
    No auto-build. Files are persistent until user deletes them.
    """
    import json as _json
    import os as _os
    from pathlib import Path as _Path

    chat_dir = _Path("data/chat_records")
    chat_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Phase 1: Stream parse + split by sender
        update_import_task(task_id, phase="parsing", progress_current=0)
        total, gen, member_map = await count_and_parse_messages(file_path)
        update_import_task(task_id, phase="parsing", progress_total=total)

        timeline_path = chat_dir / "_timeline.jsonl"
        sender_messages: dict[str, int] = {}  # platformId -> count
        sender_names: dict[str, str] = {}     # platformId -> accountName
        discovered_senders: list[str] = []    # 按发现顺序记录，用于前端实时展示
        parsed = 0

        # 预加载已存在文件的 platformMessageId 集合（用于去重）
        existing_ids: dict[str, set[str]] = {}
        for fpath in chat_dir.iterdir():
            if fpath.name.endswith(".jsonl") and fpath.name != "_timeline.jsonl" and not fpath.name.startswith("_"):
                pid = fpath.stem
                existing_ids[pid] = set()
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = _json.loads(line)
                                mid = obj.get("platform_message_id", "")
                                if mid:
                                    existing_ids[pid].add(mid)
                            except _json.JSONDecodeError:
                                pass
                except Exception:
                    pass

        # 打开所有文件句柄（追加模式）
        file_handles: dict[str, object] = {}
        timeline_fh = open(timeline_path, "a", encoding="utf-8")

        def _ensure_fh(platform_id: str):
            if platform_id not in file_handles:
                fpath = chat_dir / f"{platform_id}.jsonl"
                fh = open(fpath, "a", encoding="utf-8")
                file_handles[platform_id] = fh
            return file_handles[platform_id]

        async for msg in gen:
            # 取消检查
            task_check = get_import_task(task_id)
            if task_check and task_check["status"] == "cancelled":
                logger.info("Import %s cancelled", task_id)
                break

            norm = normalize_message(msg, member_map)
            if not norm:
                parsed += 1
                continue

            platform_id = norm.get("platform_id", "") or norm.get("sender", "")
            if not platform_id:
                parsed += 1
                continue

            # 去重检查
            msg_id = norm.get("platform_message_id", "")
            if msg_id and platform_id in existing_ids:
                if msg_id in existing_ids[platform_id]:
                    parsed += 1
                    continue
                existing_ids[platform_id].add(msg_id)

            # 写入对应文件
            line_json = _json.dumps(norm, ensure_ascii=False)
            fh = _ensure_fh(platform_id)
            fh.write(line_json + "\n")

            # 写入时间线（复用句柄，避免每条消息 open/close）
            timeline_fh.write(line_json + "\n")

            # 统计
            sender_messages[platform_id] = sender_messages.get(platform_id, 0) + 1
            sender_names[platform_id] = norm["sender"]
            if sender_messages[platform_id] == 1:
                discovered_senders.append(norm["sender"])
            parsed += 1
            if parsed % 500 == 0:
                update_import_task(task_id, progress_current=parsed)

        # 关闭所有文件句柄
        timeline_fh.close()
        for fh in file_handles.values():
            fh.close()

        logger.info("Import %s: %d messages, %d senders", task_id, parsed, len(sender_messages))

        if not sender_messages:
            update_import_task(task_id, status="failed", error_message="No valid messages found")
            return

        # 保存导入结果：发送者列表 + 原始文件名
        sender_list = sorted([
            {"platform_id": pid, "name": sender_names.get(pid, pid), "count": cnt}
            for pid, cnt in sender_messages.items()
        ], key=lambda x: x["count"], reverse=True)

        result = {
            "success": True,
            "source_file": _os.path.basename(file_path),
            "group_name": name,
            "total_messages": parsed,
            "total_senders": len(sender_list),
            "senders": sender_list,
        }
        update_import_task(
            task_id, status="done", phase="done",
            result_json=_json.dumps(result, ensure_ascii=False),
        )
        logger.info("Import %s complete: %d senders", task_id, len(sender_list))

    except Exception as e:
        logger.exception("Import task %s failed", task_id)
        update_import_task(task_id, status="failed", error_message=str(e))
@router.post("/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    """Cancel a running import task."""
    ok = cancel_import_task(task_id)
    if not ok:
        raise HTTPException(400, "Task not found or already completed/failed")
    return {"success": True, "task_id": task_id, "status": "cancelled"}



