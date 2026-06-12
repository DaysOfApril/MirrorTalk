import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Need to add backend to path
sys.path.insert(0, r'D:\AI\My-projects\0610\Tmp\MirrorTalk\backend')

from app.services.provider import create_llm
from app.models import ProviderConfig
from langchain_core.messages import SystemMessage
import traceback

config = ProviderConfig(
    provider='qwen',
    model='qwen-turbo',
    base_url='https://dashscope.aliyuncs.com/compatible-mode/v1',
    api_key='',
)

try:
    llm = create_llm(config)
    print(f'LLM created: {type(llm).__name__}')
    print(f'  model={llm.model_name}')
    print(f'  base_url={llm.openai_api_base}')
    print(f'  api_key={"set" if llm.openai_api_key else "NOT SET"}')
    print(f'  streaming={llm.streaming}')
    
    import asyncio
    async def test():
        resp = await llm.ainvoke([SystemMessage(content='Say "hello" in Chinese')])
        print(f'Response: {resp.content[:100]}')
    
    asyncio.run(test())
except Exception as e:
    print(f'ERROR: {e}')
    traceback.print_exc()
