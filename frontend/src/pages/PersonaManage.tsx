import { useState, useEffect } from "react"
import { Users, ChevronDown, ChevronRight, Database, ChevronLeft, ChevronsLeft, ChevronRightIcon, X, MessageSquare, UserCircle, Brain, Trash2 } from "lucide-react"
import { API_BASE } from "@/lib/utils"

interface Persona { id: string; name: string; style: any; ocean: any; is_aggregated: boolean; message_count?: number }

export default function PersonaManage() {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selected, setSelected] = useState<Persona | null>(null)
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [total, setTotal] = useState(0)
  const [deleting, setDeleting] = useState<string | null>(null)
  const pageSize = 20

  const handleDelete = async (id: string, name: string) => {
    if (deleting) return
    if (!window.confirm(`确定要删除「${name}」的画像吗？此操作不可撤销。`)) return
    setDeleting(id)
    try {
      await fetch(`${API_BASE}/personas/${id}`, { method: "DELETE" })
      setPersonas(prev => prev.filter(p => p.id !== id))
      setSelected(prev => prev?.id === id ? null : prev)
    } catch {
      alert("删除失败，请重试")
    } finally {
      setDeleting(null)
    }
  }

  useEffect(() => {
    fetch(`${API_BASE}/personas?page=${page}&page_size=${pageSize}`)
      .then(r => r.json())
      .then(data => {
        setPersonas(data.items || data)
        setTotalPages(data.total_pages || 1)
        setTotal(data.total || 0)
      })
  }, [page])

  return (
    <div className="max-w-4xl mx-auto p-8 space-y-6 relative">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Users size={24} className="text-indigo-500 dark:text-indigo-400" />
          <h1 className="text-xl font-semibold">画像管理</h1>
          <span className="text-sm text-slate-400">({total})</span>
        </div>
      </div>

      {personas.length === 0 ? (
        <div className="text-center py-20 text-slate-500 dark:text-slate-400">
          <Users size={48} className="mx-auto opacity-30 mb-3" />
          <p>暂无画像，请先导入聊天记录</p>
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {personas.map(p => (
              <div
                key={p.id}
                onClick={() => setSelected(p)}
                className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 overflow-hidden cursor-pointer transition-all hover:border-indigo-300 dark:hover:border-indigo-600 hover:shadow-sm"
              >
                <div className="flex items-center justify-between px-4 py-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-sm truncate">{p.name}</span>
                      {p.is_aggregated && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-indigo-500/10 dark:bg-indigo-400/10 text-indigo-500 dark:text-indigo-400 font-medium shrink-0">综合</span>
                      )}
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 flex flex-wrap gap-1">
                      {(p.style?.personality || []).slice(0, 4).map((tag: string) => (
                        <span key={tag} className="px-1.5 py-0.5 rounded-md bg-slate-100 dark:bg-slate-700 text-xs">{tag}</span>
                      ))}
                      {(p.style?.personality || []).length > 4 && (
                        <span className="text-slate-400">+{p.style.personality.length - 4}</span>
                      )}
                    </div>
                  </div>
                  <ChevronRight size={16} className="text-slate-400 shrink-0 ml-2" />
                </div>
              </div>
            ))}
          </div>

          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-4">
              <button onClick={() => setPage(1)} disabled={page <= 1}
                className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30">
                <ChevronsLeft size={16} />
              </button>
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page <= 1}
                className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30">
                <ChevronLeft size={16} />
              </button>
              {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                let pageNum: number
                if (totalPages <= 5) pageNum = i + 1
                else if (page <= 3) pageNum = i + 1
                else if (page >= totalPages - 2) pageNum = totalPages - 4 + i
                else pageNum = page - 2 + i
                return (
                  <button key={pageNum} onClick={() => setPage(pageNum)}
                    className={`w-8 h-8 rounded-lg text-sm ${pageNum === page ? "bg-indigo-500 dark:bg-indigo-400 text-white" : "hover:bg-slate-100 dark:hover:bg-slate-800"}`}>
                    {pageNum}
                  </button>
                )
              })}
              <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page >= totalPages}
                className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30">
                <ChevronRightIcon size={16} />
              </button>
              <span className="text-xs text-slate-400 ml-2">第 {page}/{totalPages} 页，共 {total} 人</span>
            </div>
          )}
        </>
      )}

      {/* Side Drawer */}
      {selected && (
        <>
          <div className="fixed inset-0 bg-black/20 z-40" onClick={() => setSelected(null)} />
          <div className="fixed right-0 top-0 h-full w-[420px] max-w-[90vw] bg-white dark:bg-slate-900 border-l border-slate-200 dark:border-slate-700 z-50 overflow-y-auto shadow-2xl">
            <div className="sticky top-0 bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 px-6 py-4 flex items-center justify-between z-10">
              <div>
                <h2 className="text-lg font-semibold">{selected.name}</h2>
                {selected.is_aggregated && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-indigo-500/10 dark:bg-indigo-400/10 text-indigo-500 dark:text-indigo-400 font-medium">综合画像</span>
                )}
              </div>
              <button onClick={() => setSelected(null)}
                className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800">
                <X size={18} />
              </button>
            </div>
            <div className="p-6 space-y-6">
              <PersonaDetail persona={selected} />
            </div>
          </div>
        </>
      )}
    </div>
  )
}

function PersonaDetail({ persona }: { persona: Persona }) {
  return (
    <>
      {/* Personality Tags */}
      <Section icon={<UserCircle size={16} />} title="性格特征">
        <div className="flex flex-wrap gap-1.5">
          {(persona.style?.personality || []).map((t: string) => (
            <span key={t} className="px-2 py-1 rounded-lg bg-indigo-50 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-400 text-sm font-medium">{t}</span>
          ))}
        </div>
      </Section>

      {/* Style Details */}
      <Section icon={<MessageSquare size={16} />} title="说话风格">
        <div className="space-y-3 text-sm">
          <DetailRow label="口头禅" value={(persona.style?.catchphrases || []).join("、") || "-"} />
          <DetailRow label="句式习惯" value={persona.style?.sentence_style || "-"} />
          <DetailRow label="语气" value={persona.style?.tone || "-"} />
          <DetailRow label="表情包" value={persona.style?.emoji_style || "-"} />
        </div>
      </Section>

      {/* OCEAN */}
      <Section icon={<Brain size={16} />} title="OCEAN 大五人格">
        <div className="space-y-3">
          {[
            { key: "openness", label: "开放性", desc: "好奇、创造性、对新事物的接受度" },
            { key: "conscientiousness", label: "尽责性", desc: "自律、条理性、目标导向" },
            { key: "extraversion", label: "外向性", desc: "社交活跃度、热情、积极情绪" },
            { key: "agreeableness", label: "宜人性", desc: "合作、信任、利他倾向" },
            { key: "neuroticism", label: "情绪稳定性", desc: "焦虑、情绪波动程度（越低越稳定）" },
          ].map(d => {
            const val = (persona.ocean?.[d.key] || 0.5) * 100
            const color = val > 70 ? "bg-green-500" : val > 40 ? "bg-yellow-500" : "bg-red-400"
            return (
              <div key={d.key}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="font-medium">{d.label}</span>
                  <span className="text-slate-400">{val.toFixed(0)}%</span>
                </div>
                <div className="h-2 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                  <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${val}%` }} />
                </div>
                <p className="text-[11px] text-slate-400 mt-0.5">{d.desc}</p>
              </div>
            )
          })}
        </div>
      </Section>

      {/* Knowledge */}
      <Section icon={<Database size={16} />} title="知识库条目">
        <PersonaKnowledge personaId={persona.id} />
      </Section>
    </>
  )
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="flex items-center gap-1.5 mb-3 text-slate-500 dark:text-slate-400">
        {icon}
        <h3 className="text-xs font-medium uppercase tracking-wide">{title}</h3>
      </div>
      {children}
    </div>
  )
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className="text-slate-900 dark:text-slate-200 max-w-[60%] text-right">{value}</span>
    </div>
  )
}

function PersonaKnowledge({ personaId }: { personaId: string }) {
  const [items, setItems] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetch(API_BASE + "/personas/" + personaId + "/knowledge")
      .then(r => r.json())
      .then(data => { setItems(data); setLoading(false) })
  }, [personaId])

  if (loading) return <p className="text-xs text-slate-400">加载中...</p>
  if (items.length === 0) return <p className="text-xs text-slate-400">暂无知识库条目</p>

  return (
    <div className="space-y-1.5 max-h-64 overflow-y-auto">
      {items.map((item: any) => (
        <div key={item.id} className="flex items-start gap-2 p-2.5 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-100 dark:border-slate-800">
          <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 shrink-0" />
          <div className="flex-1 min-w-0">
            <p className="text-xs leading-relaxed">{item.content}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-[10px] text-slate-400">{item.source_type}</span>
              {!item.synced && <span className="text-[9px] px-1 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">未同步</span>}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
