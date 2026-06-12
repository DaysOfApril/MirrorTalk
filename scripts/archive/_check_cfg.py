import sys, io, urllib.request, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    # First check what's currently saved
    resp = urllib.request.urlopen('http://127.0.0.1:8000/api/config', timeout=3)
    cfg = json.loads(resp.read())
    print('Current config keys saved:')
    for k in ['qwen_api_key_set','qwen_base_url','qwen_model','deepseek_api_key_set','deepseek_base_url','deepseek_model','ollama_base_url','ollama_model']:
        v = cfg.get(k, 'N/A')
        if 'api_key' in k and not k.endswith('_set'):
            v = '(masked)' if v else '(empty)'
        print(f'  {k}: {v}')
except Exception as e:
    print(f'Backend not reachable: {e}')
