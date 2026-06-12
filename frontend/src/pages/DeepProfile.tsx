import { useState, useEffect } from "react"
import { Brain, Loader, AlertCircle, ChevronDown, ChevronRight, MessageSquare, Clock, Tag, User } from "lucide-react"
import { API_BASE } from "@/lib/utils"

interface Persona { id: string; name: string; message_count?: number }
interface Segment {
  segment_id: number
  timestamp_range: string
  topic_summary: string
  emotional_arc: string
  key_utterances: string[]
  pragmatic_markers: string[]
  context_notes: string
  participants: string[]
}
interface DeepProfile {
  persona_id: string
  name: string
  status: string
  segment_count?: number
  silence_count?: number
  segments?: Segment[]
  silences?: any[]
  report?: string
  error?: string
}

export default function DeepProfile() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [profile, setProfile] = useState<DeepProfile | null>(null)
  const [loading, setLoading] = useState(false)
  const [triggering, setTriggering] = useState(false)
  const [expandedSegments, setExpandedSegments] = useState<Set<number>>(new Set())

  useEffect(() => {
    fetch(API_BASE + "/personas?page_size=200")
      .then(r => r.json()).then(d => setPersonas(d.items || d || []))
  }, [])

  useEffect(() => {
    if (!selectedId) return
    setLoading(true)
    fetch(API_BASE + "/personas/" + selectedId + "/deep-profile")
      .then(r => r.json())
      .then(d => { setProfile(d); setLoading(false) })
      .catch(() => setLoading(false))
  }, [selectedId])

  const triggerAnalysis = async (id: string) => {
    setTriggering(true)
    await fetch(API_BASE + "/personas/" + id + "/deep-profile", { method: "POST" })
    setTriggering(false)
    setSelectedId(id)
  }

  const toggleSegment = (id: number) => {
    setExpandedSegments(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  return (
    <div className="flex h-full">
      {/* Persona list sidebar */}
      <aside className="w-56 shrink-0 border-r border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 overflow-y-auto">
        <div className="h-14 flex items-center px-4 border-b border-slate-200 dark:border-slate-700">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">画像列表</span>
        </div>
        <div className="py-1">
          {personas.map(p => (
            <button
              key={p.id}
              onClick={() => setSelectedId(p.id)}
              className={`w-full text-left px-4 py-3 text-sm transition-colors border-l-2 ${
                selectedId === p.id
                  ? "border-indigo-500 bg-indigo-500/5 text-indigo-600 dark:text-indigo-400"
                  : "border-transparent text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              <div className="truncate font-medium">{p.name}</div>
              {p.message_count ? (
                <div className="text-xs text-slate-400 mt-0.5">{p.message_count.toLocaleString()} 条消息</div>
              ) : null}
            </button>
          ))}
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        {!selectedId ? (
          <div className="flex items-center justify-center h-full text-slate-400">
            <div className="text-center">
              <Brain size={48} className="mx-auto opacity-30 mb-3" />
              <p>选择一位好友查看深度画像分析</p>
            </div>
          </div>
        ) : loading ? (
          <div className="flex items-center justify-center h-full">
            <Loader size={24} className="animate-spin text-indigo-500" />
          </div>
        ) : profile?.status === "not_started" ? (
          <div className="flex flex-col items-center justify-center h-full gap-4">
            <Brain size={48} className="opacity-30" />
            <p className="text-slate-500">尚未进行深度分析</p>
            <button
              onClick={() => triggerAnalysis(selectedId)}
              disabled={triggering}
              className="px-4 py-2 rounded-lg bg-indigo-500 text-white text-sm hover:opacity-90 disabled:opacity-50"
            >
              {triggering ? "启动中..." : "开始深度分析"}
            </button>
          </div>
        ) : profile?.status === "running" ? (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <Loader size={32} className="animate-spin text-indigo-500" />
            <p className="text-slate-500">分析中... 可能需要几分钟</p>
            <button
              onClick={() => setSelectedId(selectedId)}
              className="text-sm text-indigo-500 hover:underline"
            >
              刷新状态
            </button>
          </div>
        ) : profile?.status === "failed" ? (
          <div className="flex flex-col items-center justify-center h-full gap-3">
            <AlertCircle size={48} className="text-red-400" />
            <p className="text-slate-500">分析失败</p>
            <p className="text-xs text-red-400 max-w-md text-center">{profile.error}</p>
          </div>
        ) : profile?.report ? (
          <div className="max-w-3xl mx-auto p-8 space-y-8">
            {/* Header */}
            <div>
              <h1 className="text-2xl font-semibold">{profile.name} · 深度画像报告</h1>
              <div className="flex gap-4 mt-2 text-sm text-slate-500">
                <span>{profile.segment_count} 个对话段</span>
                <span>{profile.silence_count} 个静默期</span>
              </div>
            </div>

            {/* Markdown Report */}
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <MarkdownRenderer content={profile.report} segments={profile.segments || []} toggleSegment={toggleSegment} expandedSegments={expandedSegments} />
            </div>

            {/* Segments Detail */}
            <div>
              <h2 className="text-lg font-semibold mb-4">对话段详情</h2>
              <div className="space-y-2">
                {(profile.segments || []).map(seg => {
                  const isExpanded = expandedSegments.has(seg.segment_id)
                  return (
                    <div key={seg.segment_id} className="rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
                      <button
                        onClick={() => toggleSegment(seg.segment_id)}
                        className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors"
                      >
                        <span className="text-xs font-mono text-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 px-1.5 py-0.5 rounded">
                          #{seg.segment_id}
                        </span>
                        <span className="flex-1 text-sm font-medium truncate">{seg.topic_summary || "未命名段落"}</span>
                        {seg.emotional_arc && (
                          <span className="text-xs text-slate-400 hidden sm:inline">{seg.emotional_arc}</span>
                        )}
                        {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </button>
                      {isExpanded && (
                        <div className="px-4 pb-4 space-y-3 border-t border-slate-100 dark:border-slate-700 pt-3">
                          {seg.timestamp_range && (
                            <div className="flex items-center gap-1.5 text-xs text-slate-400">
                              <Clock size={12} /> {seg.timestamp_range}
                            </div>
                          )}
                          {seg.key_utterances?.length > 0 && (
                            <div>
                              <div className="flex items-center gap-1.5 text-xs font-medium text-slate-500 mb-1.5">
                                <MessageSquare size={12} /> 关键原话
                              </div>
                              <div className="space-y-1">
                                {seg.key_utterances.map((u, i) => (
                                  <p key={i} className="text-sm bg-slate-50 dark:bg-slate-800 rounded-lg px-3 py-1.5 text-slate-700 dark:text-slate-300">
                                    "{u}"
                                  </p>
                                ))}
                              </div>
                            </div>
                          )}
                          {seg.pragmatic_markers?.length > 0 && (
                            <div className="flex items-center gap-1.5 text-xs text-slate-400 flex-wrap">
                              <Tag size={12} />
                              {seg.pragmatic_markers.map((m, i) => (
                                <span key={i} className="px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-xs">{m}</span>
                              ))}
                            </div>
                          )}
                          {seg.context_notes && (
                            <p className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">{seg.context_notes}</p>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        ) : null}
      </main>
    </div>
  )
}

// Simple Markdown renderer
function MarkdownRenderer({ content, segments, toggleSegment, expandedSegments }: {
  content: string
  segments: Segment[]
  toggleSegment: (id: number) => void
  expandedSegments: Set<number>
}) {
  if (!content) return null

  const lines = content.split("\n")
  const elements: React.ReactNode[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]

    // Headers
    if (line.startsWith("#### ")) {
      elements.push(<h4 key={i} className="text-sm font-semibold mt-4 mb-1 text-slate-700 dark:text-slate-300">{line.slice(5)}</h4>)
      i++; continue
    }
    if (line.startsWith("### ")) {
      elements.push(<h3 key={i} className="text-base font-semibold mt-5 mb-2 text-slate-800 dark:text-slate-200">{line.slice(4)}</h3>)
      i++; continue
    }
    if (line.startsWith("## ")) {
      elements.push(<h2 key={i} className="text-lg font-bold mt-6 mb-3 text-slate-900 dark:text-slate-100 border-b border-slate-200 dark:border-slate-700 pb-1">{line.slice(3)}</h2>)
      i++; continue
    }

    // Bold markers
    let text = line
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code class='text-xs bg-slate-100 dark:bg-slate-800 px-1 py-0.5 rounded font-mono text-indigo-600 dark:text-indigo-400'>$1</code>")

    // Segment ID references: #1, segment_1, segment-1 etc.
    text = text.replace(/#(\d+)/g, (_, id) => {
      return `<button class="inline text-xs font-mono text-indigo-500 bg-indigo-50 dark:bg-indigo-900/30 px-1 rounded cursor-pointer hover:underline" data-seg="${id}">#${id}</button>`
    })

    if (line.trim() === "") {
      elements.push(<div key={i} className="h-2" />)
    } else {
      elements.push(<p key={i} className="text-sm leading-relaxed text-slate-700 dark:text-slate-300 mb-1" dangerouslySetInnerHTML={{ __html: text }} />)
    }
    i++
  }

  return <div onClick={(e) => {
    const target = e.target as HTMLElement
    const segId = target.getAttribute("data-seg")
    if (segId) {
      toggleSegment(parseInt(segId))
    }
  }}>{elements}</div>
}
