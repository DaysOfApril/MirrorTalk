import { useState, useEffect } from "react"
import { Settings, Save, Wifi, Server, Globe, Eye, EyeOff, Check, X, Loader2 } from "lucide-react"
import { API_BASE } from "@/lib/utils"

// ---- Provider built-in defaults (mirrors backend BUILTIN_PROVIDERS) ----
const PROVIDERS = {
  ollama: {
    id: "ollama",
    name: "Ollama",
    desc: "本地免费，无需联网。需先运行 ollama serve 并拉取模型。",
    defaultBaseUrl: "http://localhost:11434/v1",
    defaultModel: "qwen2.5:7b",
    models: ["qwen2.5:7b", "qwen2.5:14b", "llama3.2", "deepseek-r1:8b", "mistral"],
    needsApiKey: false,
    icon: Server,
  },
  qwen: {
    id: "qwen",
    name: "通义千问 (Qwen)",
    desc: "阿里云免费额度，注册即送百万 Token。适合高频预处理与特征提取。",
    defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    defaultModel: "qwen-turbo",
    models: ["qwen-turbo", "qwen-plus", "qwen-max"],
    needsApiKey: true,
    icon: Globe,
  },
  deepseek: {
    id: "deepseek",
    name: "DeepSeek",
    desc: "强力推理模型，适合深度心理画像分析。按量付费，约 ¥0.01/次。",
    defaultBaseUrl: "https://api.deepseek.com/v1",
    defaultModel: "deepseek-chat",
    models: ["deepseek-chat", "deepseek-reasoner"],
    needsApiKey: true,
    icon: Wifi,
  },
} as const

type ProviderId = keyof typeof PROVIDERS
const TAB_ORDER: ProviderId[] = ["ollama", "qwen", "deepseek"]

interface ProviderForm {
  base_url: string
  model: string
  api_key: string
}

interface AppConfig {
  ollama_base_url: string; ollama_model: string
  ollama_api_key: string; ollama_api_key_set: boolean
  qwen_base_url: string; qwen_model: string
  qwen_api_key: string; qwen_api_key_set: boolean
  deepseek_base_url: string; deepseek_model: string
  deepseek_api_key: string; deepseek_api_key_set: boolean
}

export default function SettingsPage() {
  const [tab, setTab] = useState<ProviderId>("qwen")
  const [config, setConfig] = useState<AppConfig | null>(null)
  const [forms, setForms] = useState<Record<ProviderId, ProviderForm>>({
    ollama: { base_url: "", model: "", api_key: "" },
    qwen: { base_url: "", model: "", api_key: "" },
    deepseek: { base_url: "", model: "", api_key: "" },
  })
  const [showKeys, setShowKeys] = useState<Record<ProviderId, boolean>>({
    ollama: true, qwen: true, deepseek: true,
  })
  const [saving, setSaving] = useState<Record<ProviderId, boolean>>({
    ollama: false, qwen: false, deepseek: false,
  })
  const [testing, setTesting] = useState<Record<ProviderId, boolean>>({
    ollama: false, qwen: false, deepseek: false,
  })
  const [testResult, setTestResult] = useState<Record<ProviderId, { ok: boolean; msg: string; ms?: number } | null>>({
    ollama: null, qwen: null, deepseek: null,
  })
  const [saveMsg, setSaveMsg] = useState<Record<ProviderId, string>>({
    ollama: "", qwen: "", deepseek: "",
  })

  // ---- Load config ----
  useEffect(() => {
    fetch(`${API_BASE}/config`).then(r => r.json()).then((cfg: AppConfig) => {
      setConfig(cfg)
      setForms({
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
      })
    })
  }, [])

  // ---- Helpers ----
  const form = (pid: ProviderId) => forms[pid]
  const info = (pid: ProviderId) => PROVIDERS[pid]

  const updateForm = (pid: ProviderId, patch: Partial<ProviderForm>) => {
    setForms(prev => ({ ...prev, [pid]: { ...prev[pid], ...patch } }))
  }

  const effectiveBaseUrl = (pid: ProviderId) =>
    form(pid).base_url || info(pid).defaultBaseUrl

  const effectiveModel = (pid: ProviderId) =>
    form(pid).model || info(pid).defaultModel

  // ---- Save ----
  const handleSave = async (pid: ProviderId) => {
    setSaving(prev => ({ ...prev, [pid]: true }))
    setSaveMsg(prev => ({ ...prev, [pid]: "" }))

    const payload: Record<string, string> = {}
    const f = form(pid)
    const prefix = pid

    if (f.base_url.trim()) payload[`${prefix}_base_url`] = f.base_url.trim()
    if (f.model.trim()) payload[`${prefix}_model`] = f.model.trim()
    if (f.api_key.trim()) payload[`${prefix}_api_key`] = f.api_key.trim()

    try {
      const res = await fetch(`${API_BASE}/config`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })
      await res.json()
      // Keep api_key visible after save
      setSaveMsg(prev => ({ ...prev, [pid]: "保存成功" }))
      setTimeout(() => setSaveMsg(prev => ({ ...prev, [pid]: "" })), 2500)
    } catch {
      setSaveMsg(prev => ({ ...prev, [pid]: "保存失败" }))
    }
    setSaving(prev => ({ ...prev, [pid]: false }))
  }

  // ---- Test Connection ----
  const handleTest = async (pid: ProviderId) => {
    setTesting(prev => ({ ...prev, [pid]: true }))
    setTestResult(prev => ({ ...prev, [pid]: null }))

    try {
      const res = await fetch(`${API_BASE}/config/test-connection`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: pid,
          base_url: effectiveBaseUrl(pid),
          model: effectiveModel(pid),
          api_key: form(pid).api_key || "",
        }),
      })
      const data = await res.json()
      if (data.status === "ok") {
        setTestResult(prev => ({ ...prev, [pid]: { ok: true, msg: `连接成功`, ms: data.latency_ms } }))
      } else {
        setTestResult(prev => ({ ...prev, [pid]: { ok: false, msg: data.error || "连接失败" } }))
      }
    } catch {
      setTestResult(prev => ({ ...prev, [pid]: { ok: false, msg: "网络错误" } }))
    }
    setTesting(prev => ({ ...prev, [pid]: false }))
  }

  if (!config) return <div className="p-8 text-slate-500">加载中...</div>

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Settings size={24} className="text-indigo-500 dark:text-indigo-400" />
        <h1 className="text-xl font-semibold">大语言模型 (LLM) 设置</h1>
      </div>

      {/* Tabs */}
      <div className="flex rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-1 gap-1">
        {TAB_ORDER.map(pid => {
          const p = PROVIDERS[pid]
          const Icon = p.icon
          const active = tab === pid
          return (
            <button
              key={pid}
              onClick={() => setTab(pid)}
              className={`flex-1 flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg text-sm transition-all ${
                active
                  ? "bg-white dark:bg-slate-700 shadow-sm text-indigo-500 dark:text-indigo-400 font-medium"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
              }`}
            >
              <Icon size={14} />
              {p.name}
            </button>
          )
        })}
      </div>

      {/* Active Tab Content */}
      {TAB_ORDER.map(pid => {
        if (tab !== pid) return null
        const p = PROVIDERS[pid]
        const f = form(pid)
        const isSaving = saving[pid]
        const isTesting = testing[pid]
        const result = testResult[pid]
        const msg = saveMsg[pid]

        return (
          <div key={pid} className="space-y-5">
            {/* Provider Info Card */}
            <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5 space-y-4">
              <p className="text-sm text-slate-500 dark:text-slate-400">{p.desc}</p>

              {/* Status summary */}
              <div className="flex items-center gap-3 text-xs">
                <span className="text-slate-400">默认端点：</span>
                <code className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 font-mono text-[11px]">
                  {p.defaultBaseUrl}
                </code>
              </div>
              <div className="flex items-center gap-3 text-xs">
                <span className="text-slate-400">默认模型：</span>
                <code className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 font-mono text-[11px]">
                  {p.defaultModel}
                </code>
              </div>

              {/* Base URL */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  Base URL
                  {!f.base_url && <span className="ml-1 text-xs text-slate-400">(使用默认)</span>}
                </label>
                <input
                  type="text"
                  value={f.base_url}
                  onChange={e => updateForm(pid, { base_url: e.target.value })}
                  placeholder={p.defaultBaseUrl}
                  className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Model */}
              <div>
                <label className="text-sm font-medium mb-1.5 block">
                  Model
                  {!f.model && <span className="ml-1 text-xs text-slate-400">(使用默认: {p.defaultModel})</span>}
                </label>
                <div className="flex gap-2 flex-wrap mb-2">
                  {p.models.map(m => (
                    <button
                      key={m}
                      onClick={() => updateForm(pid, { model: m })}
                      className={`px-2.5 py-1 rounded-md text-xs transition-colors ${
                        effectiveModel(pid) === m
                          ? "bg-indigo-500/10 text-indigo-500 dark:text-indigo-400 border border-indigo-500/30"
                          : "bg-slate-50 dark:bg-slate-700 text-slate-500 dark:text-slate-400 border border-slate-200 dark:border-slate-600 hover:border-slate-300"
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
                <input
                  type="text"
                  value={f.model}
                  onChange={e => updateForm(pid, { model: e.target.value })}
                  placeholder={`自定义模型名 (默认: ${p.defaultModel})`}
                  className="w-full rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* API Key */}
              {p.needsApiKey ? (
                <div>
                  <label className="text-sm font-medium mb-1.5 block">
                    API Key
                    {config[(pid + '_api_key_set') as keyof AppConfig] && (
                      <span className="ml-2 inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-[11px] font-normal">
                        <Check size={10} /> 已配置
                      </span>
                    )}
                  </label>
                  {config[(pid + '_api_key_set') as keyof AppConfig] && !f.api_key && (
                    <p className="text-xs text-slate-400 mb-2">密钥已存储。输入新值可覆盖。</p>
                  )}
                  <div className="relative">
                    <input
                      type={showKeys[pid] ? "text" : "password"}
                      value={f.api_key}
                      onChange={e => updateForm(pid, { api_key: e.target.value })}
                      placeholder={config[(pid + '_api_key_set') as keyof AppConfig] ? "输入新密钥以覆盖..." : "输入 API Key..."}
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
              ) : (
                <div className="text-xs text-slate-400 flex items-center gap-1">
                  <Check size={12} className="text-green-500" />
                  本地模型无需 API Key
                </div>
              )}
            </div>

            {/* Action Buttons */}
            <div className="flex gap-3">
              {/* Test Connection */}
              <button
                onClick={() => handleTest(pid)}
                disabled={isTesting || (p.needsApiKey && !f.api_key.trim() && !config?.[(pid + "_api_key_set") as keyof AppConfig])}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 text-sm font-medium hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors disabled:opacity-40"
              >
                {isTesting ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <Wifi size={16} />
                )}
                测试连接
              </button>

              {/* Save */}
              <button
                onClick={() => handleSave(pid)}
                disabled={isSaving}
                className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-500 dark:bg-indigo-400 text-white text-sm font-medium hover:opacity-90 transition-opacity disabled:opacity-40"
              >
                {isSaving ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <Save size={16} />
                )}
                保存配置
              </button>
            </div>

            {/* Test Result */}
            {result && (
              <div className={`flex items-center gap-2 p-3 rounded-xl text-sm ${
                result.ok
                  ? "bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400"
                  : "bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400"
              }`}>
                {result.ok ? <Check size={16} /> : <X size={16} />}
                <span>{result.msg}{result.ms != null ? ` (${result.ms}ms)` : ""}</span>
              </div>
            )}

            {/* Save Message */}
            {msg && (
              <div className="flex items-center gap-2 p-3 rounded-xl bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 text-sm">
                <Check size={16} />
                <span>{msg}</span>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

