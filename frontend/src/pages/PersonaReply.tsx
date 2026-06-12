import { useState, useRef, useEffect } from "react"
import { Send, Copy, Check, ChevronDown, User, Bot } from "lucide-react"
import { API_BASE } from "@/lib/utils"

interface Persona { id: string; name: string; style: any; ocean: any; is_aggregated: boolean }
interface Message { id: number; role: "user" | "assistant"; content: string }

export default function PersonaReply() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [input, setInput] = useState("")
  const [reply, setReply] = useState("")
  const [loading, setLoading] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    fetch(`${API_BASE}/personas`).then(r => r.json()).then(data => {
      setPersonas(data.items || data || [])
    })
  }, [])

  const send = async () => {
    if (!input.trim() || !selectedId || loading) return
    setLoading(true)
    setReply("")

    try {
      const res = await fetch(`${API_BASE}/chat/persona/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona_id: selectedId, message: input, agent_type: "persona" }),
      })
      const reader = res.body?.getReader()
      const decoder = new TextDecoder()
      let full = ""
      while (reader) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        const lines = chunk.split("\n").filter(Boolean)
        for (const line of lines) {
          if (line.startsWith("data: ")) {
            const data = line.slice(6)
            try {
              const parsed = JSON.parse(data)
              if (parsed.type === "end") {
                if (parsed.data?.reply) full = parsed.data.reply
              }
            } catch {
              full += data
            }
          }
        }
        setReply(full)
      }
    } catch (e) {
      console.error("Stream error", e)
    } finally {
      setLoading(false)
    }
  }

  const handleCopy = () => {
    navigator.clipboard.writeText(reply)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const selectedPersona = personas.find(p => p.id === selectedId)

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      <div className="flex items-center gap-2">
        <User size={24} className="text-indigo-500 dark:text-indigo-400" />
        <h1 className="text-xl font-semibold">替身回复</h1>
        <span className="text-sm text-slate-400">以替身口吻自动回复好友</span>
      </div>

      {/* Select Persona */}
      <div className="relative">
        <select
          value={selectedId || ""}
          onChange={e => { setSelectedId(e.target.value); setReply("") }}
          className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-sm appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="" disabled>选择替身</option>
          {personas.map(p => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
        <ChevronDown size={16} className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400" />
      </div>

      {selectedPersona && (
        <div className="flex flex-wrap gap-1 text-xs text-slate-500 dark:text-slate-400">
          {(selectedPersona.style?.personality || []).map((t: string) => (
            <span key={t} className="px-2 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800">{t}</span>
          ))}
        </div>
      )}

      {/* Input: friend message */}
      <div>
        <label className="text-sm font-medium mb-1.5 block">好友发来的消息</label>
        <textarea
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="粘贴好友发来的消息..."
          rows={4}
          className="w-full resize-none rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>

      <button
        onClick={send}
        disabled={!selectedId || loading || !input.trim()}
        className="w-full py-3 rounded-xl bg-indigo-500 dark:bg-indigo-400 text-white font-medium text-sm disabled:opacity-40 hover:opacity-90 transition-opacity flex items-center justify-center gap-2"
      >
        <Send size={16} />
        {loading ? "生成中..." : "生成替身回复"}
      </button>

      {/* Reply */}
      {reply && (
        <div className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/50 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Bot size={16} className="text-indigo-500" />
              <span className="text-sm font-medium">替身回复</span>
            </div>
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 px-3 py-1 rounded-lg bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 text-xs hover:bg-slate-50 dark:hover:bg-slate-600 transition-colors"
            >
              {copied ? <Check size={14} className="text-green-500" /> : <Copy size={14} />}
              {copied ? "已复制" : "复制"}
            </button>
          </div>
          <p className="text-sm leading-relaxed whitespace-pre-wrap">{reply}</p>
        </div>
      )}
    </div>
  )
}
