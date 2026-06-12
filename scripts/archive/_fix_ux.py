import sys

path = r'D:\AI\My-projects\0610\Tmp\MirrorTalk\frontend\src\pages\SettingsPage.tsx'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix 1: load saved API key masked value from config
old_load = """      setForms({
        ollama: {
          base_url: cfg.ollama_base_url || "",
          model: cfg.ollama_model || "",
          api_key: cfg.ollama_api_key_set ? "" : "",
        },
        qwen: {
          base_url: cfg.qwen_base_url || "",
          model: cfg.qwen_model || "",
          api_key: cfg.qwen_api_key_set ? "" : "",
        },
        deepseek: {
          base_url: cfg.deepseek_base_url || "",
          model: cfg.deepseek_model || "",
          api_key: cfg.deepseek_api_key_set ? "" : "",
        },
      })"""

new_load = """      setForms({
        ollama: {
          base_url: cfg.ollama_base_url || "",
          model: cfg.ollama_model || "",
          api_key: cfg.ollama_api_key || "",
        },
        qwen: {
          base_url: cfg.qwen_base_url || "",
          model: cfg.qwen_model || "",
          api_key: cfg.qwen_api_key || "",
        },
        deepseek: {
          base_url: cfg.deepseek_base_url || "",
          model: cfg.deepseek_model || "",
          api_key: cfg.deepseek_api_key || "",
        },
      })"""

content = content.replace(old_load, new_load)

# Fix 2: Show "已配置" badge + masked key when key is set
old_key_section = """              {p.needsApiKey ? (
                <div>
                  <label className="text-sm font-medium mb-1.5 block">
                    API Key
                  </label>
                  <div className="relative">
                    <input
                      type={showKeys[pid] ? "text" : "password"}
                      value={f.api_key}
                      onChange={e => updateForm(pid, { api_key: e.target.value })}
                      placeholder="输入 API Key..."
                      className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowKeys(prev => ({ ...prev, [pid]: !prev[pid] }))}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                    >
                      {showKeys[pid] ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
              ) : ("""

new_key_section = """              {p.needsApiKey ? (
                <div>
                  <label className="text-sm font-medium mb-1.5 block">
                    API Key
                    {config[${pid}_api_key_set as keyof AppConfig] && (
                      <span className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-[11px] font-normal">
                        <Check size={10} /> 已配置
                      </span>
                    )}
                  </label>
                  {config[${pid}_api_key_set as keyof AppConfig] && !f.api_key && (
                    <p className="text-xs text-slate-400 mb-2">密钥已存储。输入新值可覆盖。</p>
                  )}
                  <div className="relative">
                    <input
                      type={showKeys[pid] ? "text" : "password"}
                      value={f.api_key}
                      onChange={e => updateForm(pid, { api_key: e.target.value })}
                      placeholder={config[${pid}_api_key_set as keyof AppConfig] ? "输入新密钥以覆盖..." : "输入 API Key..."}
                      className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowKeys(prev => ({ ...prev, [pid]: !prev[pid] }))}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                    >
                      {showKeys[pid] ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
              ) : ("""

content = content.replace(old_key_section, new_key_section)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("SettingsPage UX improved")
