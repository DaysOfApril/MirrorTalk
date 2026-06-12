import { useState, useEffect } from "react"
import { Database, Trash2, Search, RefreshCw, Upload, FileText, Link2, Check, Loader2, CloudUpload } from "lucide-react"
import { cn, API_BASE } from "@/lib/utils"

interface Memory { id: number; source_type: string; source: string; content: string; confidence: number; importance: number }
interface Persona { id: string; name: string; is_aggregated?: boolean }

const TYPE_LABELS: Record<string, string> = {
  profile: "??", fact: "??", relationship: "??", external: "????",
}
const TYPE_COLORS: Record<string, string> = {
  profile: "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300",
  fact: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300",
  relationship: "bg-pink-100 dark:bg-pink-900/40 text-pink-700 dark:text-pink-300",
  external: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300",
}

export default function KnowledgeBase() {
  const [items, setItems] = useState<Memory[]>([])
  const [personas, setPersonas] = useState<Persona[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState("")

  // ????
  const [showImport, setShowImport] = useState(false)
  const [importTitle, setImportTitle] = useState("")
  const [importContent, setImportContent] = useState("")
  const [importPersonaIds, setImportPersonaIds] = useState<string[]>([])
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState("")

  // ????
  const [bindItem, setBindItem] = useState<number | null>(null)
  const [bindPersonas, setBindPersonas] = useState<string[]>([])
  const [itemPersonas, setItemPersonas] = useState<Record<number, Persona[]>>({})
  const [savingBind, setSavingBind] = useState(false)

  // ????
  const [syncing, setSyncing] = useState(false)
  const [hasPendingSync, setHasPendingSync] = useState(false)

  const load = () => {
    setLoading(true)
    Promise.all([
      fetch(`${API_BASE}/memories?limit=200`).then(r => r.json()),
      fetch(`${API_BASE}/personas`).then(r => r.json()),
    ]).then(([itemsData, personasData]) => {
      setItems(itemsData)
      setPersonas(personasData.filter((p: Persona) => !p.is_aggregated))
      setLoading(false)
    })
  }

  useEffect(() => { load() }, [])

  // ??????
  useEffect(() => {
    fetch(`${API_BASE}/knowledge/sync-status`).then(r => r.json()).then(data => {
      setHasPendingSync(data.pending)
    })
  }, [])

  const deleteItem = async (id: number) => {
    await fetch(`${API_BASE}/memories/${id}`, { method: "DELETE" })
    setItems(prev => prev.filter(i => i.id !== id))
  }

  // ????
  const handleImport = async () => {
    if (!importContent.trim()) return
    setImporting(true)
    setImportResult("")
    try {
      const res = await fetch(`${API_BASE}/knowledge/import`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          content: importContent,
          title: importTitle || "????",
          persona_ids: importPersonaIds,
        }),
      })
      const data = await res.json()
      if (data.success) {
        setImportResult(`???? ${data.count} ???`)
        setImportContent("")
        setImportTitle("")
        setImportPersonaIds([])
        setShowImport(false)
        load()
      } else {
        setImportResult("????")
      }
    } catch {
      setImportResult("????")
    }
    setImporting(false)
  }

  // ????????????
  const loadBindings = async (itemId: number) => {
    const res = await fetch(`${API_BASE}/knowledge/${itemId}/personas`)
    const data = await res.json()
    setItemPersonas(prev => ({ ...prev, [itemId]: data }))
  }

  // ???????
  const openBindEditor = async (itemId: number) => {
    setBindItem(itemId)
    if (!itemPersonas[itemId]) {
      await loadBindings(itemId)
    }
    setBindPersonas(itemPersonas[itemId]?.map(p => p.id) || [])
  }

  // ????
  const saveBindings = async () => {
    if (bindItem === null) return
    setSavingBind(true)
    await fetch(`${API_BASE}/knowledge/${bindItem}/personas`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ persona_ids: bindPersonas }),
    })
    await loadBindings(bindItem)
    setSavingBind(false)
    setBindItem(null)
  }

  // ??????
  const syncToAgent = async () => {
    setSyncing(true)
    await fetch(`${API_BASE}/knowledge/sync-to-agent`, { method: "POST" })
    // ????????
    const poll = setInterval(async () => {
      const res = await fetch(`${API_BASE}/knowledge/sync-status`)
      const data = await res.json()
      if (!data.pending) {
        clearInterval(poll)
        setHasPendingSync(false)
        setSyncing(false)
      }
    }, 1000)
    // ??? 30 ?
    setTimeout(() => { clearInterval(poll); setSyncing(false) }, 30000)
  }

  const filtered = filter
    ? items.filter(i => i.content.includes(filter) || i.source_type.includes(filter))
    : items

  return (
    <div className="max-w-4xl mx-auto p-8 space-y-6">
      {/* ??? */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Database size={24} className="text-indigo-500 dark:text-indigo-400" />
          <h1 className="text-xl font-semibold">???</h1>
          <span className="text-sm text-slate-500 dark:text-slate-400">({items.length} ?)</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowImport(true)}
            className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-indigo-500 dark:bg-indigo-400 text-white text-sm font-medium hover:opacity-90 transition-opacity"
          >
            <Upload size={15} />
            ????
          </button>
          <button
            onClick={syncToAgent}
            disabled={syncing}
            className="relative flex items-center gap-1.5 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
          >
            <CloudUpload size={15} />
            {syncing ? "???..." : "??????"}
            {hasPendingSync && !syncing && (
              <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-red-500" />
            )}
          </button>
          <button onClick={load} className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 transition-colors" title="??">
            <RefreshCw size={16} className={loading ? "animate-spin" : ""} />
          </button>
        </div>
      </div>

      {/* ???? */}
      {showImport && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setShowImport(false)}>
          <div className="bg-white dark:bg-[#2d2d2d] rounded-2xl shadow-xl w-full max-w-lg mx-4 p-6 space-y-4" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-semibold">??????</h2>
            <div>
              <label className="text-xs text-slate-500 dark:text-slate-400 mb-1 block">??????</label>
              <input
                value={importTitle}
                onChange={e => setImportTitle(e.target.value)}
                placeholder="????"
                className="w-full rounded-xl border border-slate-200 dark:border-[#3d3d3d] bg-white dark:bg-[#333] px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500 dark:text-slate-400 mb-1 block">????? txt/md ???</label>
              <textarea
                value={importContent}
                onChange={e => setImportContent(e.target.value)}
                placeholder={"?????????...\\n\\n?????????????????????"}
                rows={8}
                className="w-full resize-none rounded-xl border border-slate-200 dark:border-[#3d3d3d] bg-white dark:bg-[#333] px-4 py-3 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="text-xs text-slate-500 dark:text-slate-400 mb-1.5 block">????????????</label>
              <div className="flex flex-wrap gap-1.5 max-h-32 overflow-auto">
                {personas.map(p => (
                  <button
                    key={p.id}
                    onClick={() => setImportPersonaIds(prev =>
                      prev.includes(p.id) ? prev.filter(id => id !== p.id) : [...prev, p.id]
                    )}
                    className={cn(
                      "px-2.5 py-1 rounded-full text-xs border transition-colors",
                      importPersonaIds.includes(p.id)
                        ? "border-indigo-500 bg-indigo-500/10 text-indigo-500 dark:text-indigo-400"
                        : "border-slate-200 dark:border-[#3d3d3d] hover:bg-slate-100 dark:hover:bg-[#383838]"
                    )}
                  >
                    {p.name}
                  </button>
                ))}
              </div>
            </div>
            {importResult && (
              <p className={cn("text-sm", importResult.includes("??") ? "text-green-600" : "text-red-500")}>{importResult}</p>
            )}
            <div className="flex gap-3 justify-end">
              <button onClick={() => setShowImport(false)} className="px-4 py-2 rounded-lg border border-slate-200 dark:border-[#3d3d3d] text-sm">??</button>
              <button
                onClick={handleImport}
                disabled={importing || !importContent.trim()}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-500 dark:bg-indigo-400 text-white text-sm disabled:opacity-40"
              >
                {importing ? <Loader2 size={15} className="animate-spin" /> : <FileText size={15} />}
                {importing ? "???..." : "??"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ???? */}
      {bindItem !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={() => setBindItem(null)}>
          <div className="bg-white dark:bg-[#2d2d2d] rounded-2xl shadow-xl w-full max-w-md mx-4 p-6 space-y-4" onClick={e => e.stopPropagation()}>
            <h2 className="text-lg font-semibold">????</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400">
              ????????????
            </p>
            <div className="flex flex-wrap gap-2 max-h-48 overflow-auto">
              {personas.map(p => (
                <button
                  key={p.id}
                  onClick={() => setBindPersonas(prev =>
                    prev.includes(p.id) ? prev.filter(id => id !== p.id) : [...prev, p.id]
                  )}
                  className={cn(
                    "px-3 py-1.5 rounded-lg text-sm border transition-colors",
                    bindPersonas.includes(p.id)
                      ? "border-indigo-500 bg-indigo-500/10 text-indigo-500 dark:text-indigo-400"
                      : "border-slate-200 dark:border-[#3d3d3d] hover:bg-slate-100 dark:hover:bg-[#383838]"
                  )}
                >
                  {p.name}
                </button>
              ))}
              {personas.length === 0 && <p className="text-sm text-slate-400">???????????</p>}
            </div>
            <div className="flex gap-3 justify-end">
              <button onClick={() => setBindItem(null)} className="px-4 py-2 rounded-lg border border-slate-200 dark:border-[#3d3d3d] text-sm">??</button>
              <button
                onClick={saveBindings}
                disabled={savingBind}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-indigo-500 dark:bg-indigo-400 text-white text-sm disabled:opacity-40"
              >
                {savingBind ? <Loader2 size={15} className="animate-spin" /> : <Check size={15} />}
                ??
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ?? */}
      <div className="relative">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 dark:text-slate-400" />
        <input
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="???????..."
          className="w-full rounded-xl border border-slate-200 dark:border-[#3d3d3d] bg-white dark:bg-[#333] pl-9 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:focus:ring-[#4cc2ff]"
        />
      </div>

      {/* ?? */}
      {loading ? (
        <div className="text-center py-20 text-slate-500 dark:text-slate-400">???...</div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-20 text-slate-500 dark:text-slate-400">
          <Database size={48} className="mx-auto opacity-30 mb-3" />
          <p>{filter ? "?????" : "???????"}</p>
          {!filter && (
            <button onClick={() => setShowImport(true)} className="mt-3 text-indigo-500 dark:text-indigo-400 text-sm hover:underline">
              ???????
            </button>
          )}
        </div>
      ) : (
        <div className="space-y-2">
          {filtered.map(item => (
            <div key={item.id} className="flex items-start gap-3 p-4 rounded-xl border border-slate-200 dark:border-[#3d3d3d] bg-white dark:bg-[#2d2d2d] hover:shadow-sm transition-shadow group">
              <span className={cn("shrink-0 text-[10px] px-2 py-0.5 rounded-full font-medium mt-0.5", TYPE_COLORS[item.source_type] || "bg-slate-100 dark:bg-slate-700")}>
                {TYPE_LABELS[item.source_type] || item.source_type}
              </span>
              <div className="flex-1 min-w-0">
                <p className="text-sm leading-relaxed break-words">{item.content}</p>
                {/* ?????? */}
                <BindTags itemId={item.id} itemPersonas={itemPersonas} onLoad={loadBindings} />
              </div>
              <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 shrink-0">
                <span title="???">{(item.confidence * 100).toFixed(0)}%</span>
                <span title="???">{(item.importance * 100).toFixed(0)}%</span>
                <button
                  onClick={() => openBindEditor(item.id)}
                  className="p-1.5 rounded-md hover:bg-indigo-50 dark:hover:bg-[#383838] hover:text-indigo-500 dark:hover:text-indigo-400 opacity-0 group-hover:opacity-100 transition-all"
                  title="??????"
                >
                  <Link2 size={14} />
                </button>
                <button
                  onClick={() => deleteItem(item.id)}
                  className="p-1.5 rounded-md hover:bg-red-50 dark:hover:bg-red-900/30 hover:text-red-500 dark:hover:text-red-400 opacity-0 group-hover:opacity-100 transition-all"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** ????????????? */
function BindTags({ itemId, itemPersonas, onLoad }: {
  itemId: number
  itemPersonas: Record<number, Persona[]>
  onLoad: (id: number) => void
}) {
  const personas = itemPersonas[itemId]

  useEffect(() => {
    if (personas === undefined) {
      onLoad(itemId)
    }
  }, [itemId])

  if (!personas || personas.length === 0) return null

  return (
    <div className="flex flex-wrap gap-1 mt-1.5">
      {personas.map(p => (
        <span key={p.id} className="text-[10px] px-1.5 py-0.5 rounded-md bg-indigo-100 dark:bg-indigo-900/30 text-indigo-600 dark:text-indigo-300">
          {p.name}
        </span>
      ))}
    </div>
  )
}
