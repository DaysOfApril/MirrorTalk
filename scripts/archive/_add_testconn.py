import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend\app\api\routes.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the config section and add test-connection endpoint after update_config
marker = '''    return _build_config_response()


# ========== 知识库导入 =========='''

new_endpoint = '''    return _build_config_response()


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


# ========== 知识库导入 =========='''

content = content.replace(marker, new_endpoint)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Test-connection endpoint added")
