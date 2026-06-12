import { useState, useEffect, useCallback } from "react"
import { Routes, Route, NavLink, useLocation, useNavigate } from "react-router-dom"
import {
  MessageCircle, UserRoundPen, Upload, Users, Database, Settings, Brain,
  Moon, Sun, Pin, MessageSquare, Bot, User as UserIcon
} from "lucide-react"
import ChatPanel from "./pages/ChatPanel"
import PersonaReply from "./pages/PersonaReply"
import DataImport from "./pages/DataImport"
import PersonaManage from "./pages/PersonaManage"
import KnowledgeBase from "./pages/KnowledgeBase"
import SettingsPage from "./pages/SettingsPage"
import DeepProfile from "./pages/DeepProfile"
import { API_BASE } from "@/lib/utils"

interface Persona { id: string; name: string; style: any; ocean: any; is_aggregated: boolean; message_count?: number }
interface ConvPreview { id: string; title: string; last_message: { content: string; role: string } | null }

const NAV_ITEMS = [
  { to: "/friend-chat", icon: MessageCircle, label: "好友聊天" },
  { to: "/persona-reply", icon: UserRoundPen, label: "替身回复" },
  { to: "/data-import", icon: Upload, label: "数据导入" },
  { to: "/personas", icon: Users, label: "画像管理" },
  { to: "/knowledge", icon: Database, label: "知识库" },
  { to: "/settings", icon: Settings, label: "设置" },
]

export default function App() {
  const location = useLocation()
  const navigate = useNavigate()
  const [theme, setTheme] = useState<"light" | "dark">("light")
  const [personas, setPersonas] = useState<Persona[]>([])
  const [selectedFriendId, setSelectedFriendId] = useState<string | null>(null)
  const [chatMode, setChatMode] = useState(false)
  const [pinnedIds, setPinnedIds] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem("mirrortalk_pinned") || "[]") }
    catch { return [] }
  })
  const [convPreviews, setConvPreviews] = useState<Record<string, ConvPreview[]>>({})

  useEffect(() => { document.documentElement.setAttribute("data-theme", theme) }, [theme])

  useEffect(() => {
    fetch(`${API_BASE}/personas?page_size=200`)
      .then(r => r.json()).then(data => setPersonas(data.items || data || []))
  }, [])

  useEffect(() => {
    personas.forEach(p => {
      if (!convPreviews[p.id]) {
        fetch(`${API_BASE}/conversations?persona_id=${p.id}&limit=2`)
          .then(r => r.json()).then(data => setConvPreviews(prev => ({ ...prev, [p.id]: data.conversations || [] })))
          .catch(() => {})
      }
    })
  }, [personas])

  const togglePin = useCallback((id: string) => {
    setPinnedIds(prev => {
      const next = prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
      localStorage.setItem("mirrortalk_pinned", JSON.stringify(next))
      return next
    })
  }, [])

  // 点击好友名 → 看画像
  const viewProfile = useCallback((id: string) => {
    setSelectedFriendId(id)
    setChatMode(false)
    navigate("/friend-chat")
  }, [navigate])

  // 点击对话按钮 → 聊天模式
  const startChat = useCallback((id: string) => {
    setSelectedFriendId(id)
    setChatMode(true)
    navigate("/friend-chat")
  }, [navigate])

  // 从聊天返回画像
  const backToProfile = useCallback(() => {
    setChatMode(false)
  }, [])

  const selectedPersona = personas.find(p => p.id === selectedFriendId)

  const sortedPersonas = [...personas].sort((a, b) => {
    const aP = pinnedIds.includes(a.id) ? 0 : 1
    const bP = pinnedIds.includes(b.id) ? 0 : 1
    if (aP !== bP) return aP - bP
    return a.name.localeCompare(b.name, "zh")
  })

  return (
    <div className="flex h-screen bg-white dark:bg-slate-900">
      {/* ====== 侧边栏 1: 导航 ====== */}
      <aside className="w-52 shrink-0 border-r border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 flex flex-col">
        <div className="h-14 flex items-center px-4 border-b border-slate-200 dark:border-slate-700">
          <span className="text-lg font-semibold text-indigo-500 dark:text-indigo-400">MirrorTalk</span>
        </div>
        <nav className="flex-1 py-2 space-y-0.5 px-2">
          {NAV_ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to}
              className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                location.pathname === item.to
                  ? "bg-indigo-500/10 dark:bg-indigo-400/10 text-indigo-500 dark:text-indigo-400 font-medium"
                  : "text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800"
              }`}
            >
              <item.icon size={16} />{item.label}
            </NavLink>
          ))}
        </nav>
        <div className="p-2 border-t border-slate-200 dark:border-slate-700">
          <button onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
            {theme === "light" ? "深色模式" : "浅色模式"}
          </button>
        </div>
      </aside>

{location.pathname === "/friend-chat" && (
      <>
      {/* ====== 侧边栏 2: 好友列表 ====== */}
      <aside className="w-60 shrink-0 border-r border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 flex flex-col">
        <div className="h-14 flex items-center px-4 border-b border-slate-200 dark:border-slate-700">
          <span className="text-sm font-medium text-slate-700 dark:text-slate-300">好友 ({personas.length})</span>
        </div>
        <div className="flex-1 overflow-y-auto py-1">
          {sortedPersonas.map(p => {
            const isSelected = selectedFriendId === p.id && !chatMode
            const isChatting = selectedFriendId === p.id && chatMode
            const pre = convPreviews[p.id] || []
            return (
              <div key={p.id} className="group">
                {/* 好友行 */}
                <button onClick={() => viewProfile(p.id)}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-sm transition-colors text-left ${
                    isSelected || isChatting
                      ? "bg-indigo-500/10 dark:bg-indigo-400/10 text-indigo-500 dark:text-indigo-400 border-r-2 border-indigo-500"
                      : "text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-800"
                  }`}
                >
                  <div className="w-7 h-7 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center shrink-0">
                    <UserIcon size={13} className="text-indigo-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="truncate block">{p.name}</span>
                    {p.message_count ? (
                      <span className="text-[10px] text-slate-400">{p.message_count.toLocaleString()} 条</span>
                    ) : null}
                  </div>
                  {/* Hover 按钮 */}
                  <span className="hidden group-hover:flex items-center gap-0.5">
                    <button onClick={(e) => { e.stopPropagation(); togglePin(p.id) }}
                      className={`p-1 rounded-md ${pinnedIds.includes(p.id) ? "text-amber-500 bg-amber-500/10" : "text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-700"}`}
                      title={pinnedIds.includes(p.id) ? "取消置顶" : "置顶"}
                    ><Pin size={13} /></button>
                    <button onClick={(e) => { e.stopPropagation(); startChat(p.id) }}
                      className="p-1 rounded-md text-slate-400 hover:text-indigo-500 hover:bg-indigo-500/10"
                      title="开始对话"
                    ><MessageSquare size={13} /></button>
                  </span>
                </button>

                {/* 最近对话预览 —— 缩进 + 小字 */}
                {pre.length > 0 && (
                  <div className="ml-9 mb-1 mr-2">
                    {pre.map(c => (
                      <div key={c.id}
                        onClick={(e) => { e.stopPropagation(); startChat(p.id) }}
                        className="text-[10px] text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300 cursor-pointer px-1 py-0.5 truncate rounded hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                      >
                        {c.last_message ? c.last_message.content.slice(0, 35) : c.title}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
          {personas.length === 0 && (
            <p className="px-4 py-8 text-xs text-slate-400 text-center">暂无好友，请先导入聊天记录</p>
          )}
        </div>
      </aside>
      </>
)}


      {/* ====== 主内容区 ====== */}
      <main className="flex-1 overflow-auto">
        <Routes>
          <Route path="/friend-chat" element={
            chatMode && selectedFriendId && selectedPersona ? (
              <ChatPanel personaId={selectedFriendId} personaName={selectedPersona.name} onBack={backToProfile} />
            ) : (
              <MainContent selectedFriend={selectedPersona || null} />
            )
          } />
          <Route path="/persona-reply" element={<PersonaReply />} />
          <Route path="/data-import" element={<DataImport />} />
          <Route path="/personas" element={<PersonaManage />} />
          <Route path="/knowledge" element={<KnowledgeBase />} />
          <Route path="/deep-profile" element={<DeepProfile />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<MainContent selectedFriend={null} />} />
        </Routes>
      </main>
    </div>
  )
}

function MainContent({ selectedFriend }: { selectedFriend: Persona | null }) {
  if (!selectedFriend) {
    return (
      <div className="flex items-center justify-center h-full text-slate-400">
        <div className="text-center">
          <Bot size={48} className="mx-auto opacity-30 mb-3" />
          <p>在左侧好友列表中选择一位好友</p>
        </div>
      </div>
    )
  }

  const s = selectedFriend.style || {}
  const o = selectedFriend.ocean || {}

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-6">
      <div className="flex items-center gap-4">
        <div className="w-16 h-16 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center">
          <UserIcon size={32} className="text-indigo-500" />
        </div>
        <div>
          <h1 className="text-xl font-semibold">{selectedFriend.name}</h1>
          <div className="flex items-center gap-2 mt-0.5">
            {selectedFriend.is_aggregated && (
              <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-500">综合画像</span>
            )}
            {selectedFriend.message_count ? (
              <span className="text-xs text-slate-400">分析了 {selectedFriend.message_count.toLocaleString()} 条聊天记录</span>
            ) : null}
          </div>
        </div>
      </div>

      {s.personality?.length > 0 && (
        <div>
          <h2 className="text-sm font-medium mb-2 text-slate-700 dark:text-slate-300">性格特征</h2>
          <div className="flex flex-wrap gap-2">
            {s.personality.map((t: string) => (
              <span key={t} className="px-3 py-1 rounded-lg bg-slate-100 dark:bg-slate-800 text-sm">{t}</span>
            ))}
          </div>
        </div>
      )}

      {s.catchphrases?.length > 0 && (
        <div>
          <h2 className="text-sm font-medium mb-2 text-slate-700 dark:text-slate-300">口头禅</h2>
          <div className="flex flex-wrap gap-2">
            {s.catchphrases.map((t: string) => (
              <span key={t} className="px-3 py-1 rounded-lg bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-400 text-sm">{t}</span>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-2 gap-4">
        {s.sentence_style && (
          <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800">
            <p className="text-xs text-slate-400 mb-1">句式习惯</p><p className="text-sm">{s.sentence_style}</p>
          </div>
        )}
        {s.emoji_style && (
          <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800">
            <p className="text-xs text-slate-400 mb-1">表情包使用</p><p className="text-sm">{s.emoji_style}</p>
          </div>
        )}
        {s.tone && (
          <div className="p-4 rounded-xl bg-slate-50 dark:bg-slate-800">
            <p className="text-xs text-slate-400 mb-1">语气</p><p className="text-sm">{s.tone}</p>
          </div>
        )}
      </div>

      <div>
        <h2 className="text-sm font-medium mb-3 text-slate-700 dark:text-slate-300">大五人格 (OCEAN)</h2>
        <div className="space-y-2">
          {[
            { label: "开放性", key: "openness", value: o.openness },
            { label: "尽责性", key: "conscientiousness", value: o.conscientiousness },
            { label: "外向性", key: "extraversion", value: o.extraversion },
            { label: "宜人性", key: "agreeableness", value: o.agreeableness },
            { label: "神经质", key: "neuroticism", value: o.neuroticism },
          ].map(item => (
            <div key={item.key} className="flex items-center gap-3">
              <span className="w-16 text-xs text-slate-500">{item.label}</span>
              <div className="flex-1 h-2 rounded-full bg-slate-200 dark:bg-slate-700 overflow-hidden">
                <div className="h-full rounded-full bg-indigo-500" style={{ width: `${(item.value || 0) * 100}%` }} />
              </div>
              <span className="text-xs text-slate-400 w-8 text-right">{((item.value || 0) * 100).toFixed(0)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}