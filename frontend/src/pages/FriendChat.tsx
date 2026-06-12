import { useState, useRef, useEffect } from "react"
import { Send, ChevronDown, User, Bot, Plus } from "lucide-react"
import { API_BASE } from "@/lib/utils"

interface Persona { id: string; name: string; style: any; ocean: any; is_aggregated: boolean }
interface Message { id: number; role: "user" | "assistant"; content: string }

export default function FriendChat() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    fetch(`${API_BASE}/personas`).then(r => r.json()).then(data => {
      setPersonas(data.items || data || [])
    })
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const selectedPersona = personas.find(p => p.id === selectedId)
  const send = async () => {
    if (!input.trim() || !selectedId || loading) return
    const userMsg: Message = { id: Date.now(), role: "user", content: input }
    setMessages(prev => [...prev, userMsg])
    setInput("")
    setLoading(true)

    const assistantId = Date.now() + 1
    setMessages(prev => [...prev, { id: assistantId, role: "assistant", content: "" }])

    try {
      const res = await fetch(`${API_BASE}/chat/friend/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona_id: selectedId, message: userMsg.content, agent_type: "friend" }),
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
        setMessages(prev => prev.map(m => m.id === assistantId ? { ...m, content: full } : m))
      }
    } catch (e) {
      console.error("Stream error", e)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto h-screen flex flex-col">
      <div className="border-b border-slate-200 dark:border-slate-700 px-6 py-4 flex items-center gap-3 shrink-0">
        <div className="relative flex-1">
          <select
            value={selectedId || ""}
            onChange={e => { setSelectedId(e.target.value); setMessages([]) }}
            className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-sm appearance-none cursor-pointer focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="" disabled>选择一位好友</option>
            {personas.map(p => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <ChevronDown size={16} className="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none text-slate-400" />
        </div>
        {selectedPersona && (
          <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 shrink-0">
            {(selectedPersona.style?.personality || []).slice(0, 3).map((t: string) => (
              <span key={t} className="px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-slate-800">{t}</span>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center py-20 text-slate-400">
            <Bot size={48} className="mx-auto opacity-30 mb-3" />
            <p>选择好友，开始对话</p>
          </div>
        )}
        {messages.map(m => (
          <div key={m.id} className={`flex gap-3 ${m.role === "user" ? "justify-end" : ""}`}>
            {m.role === "assistant" && (
              <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center shrink-0">
                <Bot size={16} className="text-indigo-500" />
              </div>
            )}
            <div className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
              m.role === "user"
                ? "bg-indigo-500 dark:bg-indigo-400 text-white"
                : "bg-slate-100 dark:bg-slate-800"
            }`}>
              {m.content || (m.role === "assistant" && loading ? "..." : "")}
            </div>
            {m.role === "user" && (
              <div className="w-8 h-8 rounded-full bg-slate-200 dark:bg-slate-700 flex items-center justify-center shrink-0">
                <User size={16} />
              </div>
            )}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-slate-200 dark:border-slate-700 px-6 py-4 shrink-0">
        <div className="flex gap-2">
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send() } }}
            placeholder="输入消息..."
            disabled={!selectedId}
            className="flex-1 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:opacity-40"
          />
          <button
            onClick={send}
            disabled={!selectedId || loading || !input.trim()}
            className="px-4 py-2.5 rounded-xl bg-indigo-500 dark:bg-indigo-400 text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
          >
            <Send size={18} />
          </button>
        </div>
      </div>
    </div>
  )
}
