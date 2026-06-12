import pathlib

p = pathlib.Path("D:/02_Personal_Projects/Tmp/MirrorTalk/backend/app/api/routes.py")
t = p.read_text("utf-8")

# 1. Add cache import
t = t.replace(
    "from app.pipelines.profile_builder import build_persona_pipeline",
    "from app.pipelines.profile_builder import build_persona_pipeline\nfrom app.services.cache import cache_lookup, cache_store"
)

# 2. Add cache lookup in chat_friend_stream
old_cf = '    async def event_stream():\n        """SSE event generator using LangGraph astream_events"""\n        full_reply = ""\n        try:'
new_cf = '    async def event_stream():\n        """SSE event generator using LangGraph astream_events"""\n        # ---- Semantic Cache Lookup ----\n        cached = await cache_lookup(req.message, req.persona_id)\n        if cached:\n            save_message(conv_id, "assistant", cached["reply"])\n            import json as _json\n            end_data = _json.dumps({"type": "end", "data": {"conversation_id": conv_id, "reply": cached["reply"], "cached": True}})\n            yield f"data: {end_data}\n\n"\n            return\n        full_reply = ""\n        try:'
t = t.replace(old_cf, new_cf, 1)

# 3. Add cache lookup in chat_persona_stream
old_cp = '    async def event_stream():\n        """SSE event generator using LangGraph astream_events"""\n        full_reply = ""\n        try:'
# only replace the 2nd occurrence (persona)
idx = t.find(old_cp, t.find("chat_persona_stream"))
if idx > 0:
    new_cp = old_cp.replace('        """SSE event generator using LangGraph astream_events"""', '        """SSE event generator using LangGraph astream_events"""\n        cached = await cache_lookup(req.message, req.persona_id)\n        if cached:\n            save_message(conv_id, "assistant", cached["reply"])\n            import json as _json\n            end_data = _json.dumps({"type": "end", "data": {"conversation_id": conv_id, "reply": cached["reply"], "cached": True}})\n            yield f"data: {end_data}\n\n"\n            return')
    t = t[:idx] + new_cp + t[idx + len(old_cp):]

# 4. Add cache_store after save_message in finally blocks (both friend and persona)
old_save = 'save_message(conv_id, "assistant", full_reply)\n            import json'
new_save = 'save_message(conv_id, "assistant", full_reply)\n            cache_store(req.message, full_reply, req.persona_id)\n            import json'
t = t.replace(old_save, new_save)

p.write_text(t, "utf-8")

import py_compile
py_compile.compile(str(p), doraise=True)
print("Cache integrated + COMPILE OK")