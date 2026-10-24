import { useEffect, useState } from 'react'
import { api, type Claim, type Source } from '../api'
import ClaimList from './ClaimList'

type Msg = { role: 'user'; text: string } | { role: 'assistant'; claims: Claim[]; sources: Source[] }
const SUGGESTIONS = ['Как это повлияет на наш лизинг?', 'Покажи по контрагентам', 'Что делать казначейству?']

export default function ChatPanel({ insightId, sources }: { insightId: string; sources: Source[] }) {
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    api.chatHistory(insightId).then(h => setMsgs(h.map(m => m.role === 'user'
      ? { role: 'user', text: m.content.text ?? '' }
      : { role: 'assistant', claims: m.content.claims ?? [], sources: m.content.sources ?? sources }))).catch(() => {})
  }, [insightId, sources])

  const send = async (question: string) => {
    if (!question.trim()) return
    setBusy(true); setError(''); setQ('')
    setMsgs(m => [...m, { role: 'user', text: question }])
    try {
      const a = await api.chat(insightId, question)
      setMsgs(m => [...m, { role: 'assistant', claims: a.claims, sources: a.sources }])
    } catch (e) { setError((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <div className="card p-4 flex flex-col gap-3">
      <h3 className="font-semibold text-sm">Уточнить у аналитика AI</h3>
      <div className="space-y-3 max-h-[28rem] overflow-auto">
        {msgs.length === 0 && <p className="text-xs text-gray-500">Задайте вопрос по событию: другой разрез, влияние на продукт, что делать.</p>}
        {msgs.map((m, i) => m.role === 'user'
          ? <div key={i} className="ml-8 rounded-lg bg-gray-900 text-white text-sm px-3 py-2">{m.text}</div>
          : <div key={i}>{m.claims.length ? <ClaimList claims={m.claims} sources={m.sources} />
                                         : <p className="text-xs text-gray-500">Не удалось дать обоснованный ответ по имеющимся данным.</p>}</div>)}
        {busy && <p className="text-xs text-gray-400 animate-pulse">Агент собирает данные…</p>}
      </div>
      <div className="flex flex-wrap gap-1">
        {SUGGESTIONS.map(s => <button key={s} className="text-xs rounded-full border border-gray-300 px-2 py-1 hover:bg-gray-50"
                                       disabled={busy} onClick={() => send(s)}>{s}</button>)}
      </div>
      <form className="flex gap-2" onSubmit={e => { e.preventDefault(); send(q) }}>
        <input className="input flex-1" value={q} onChange={e => setQ(e.target.value)} placeholder="Ваш вопрос…" maxLength={1000} />
        <button className="btn-primary" disabled={busy || !q.trim()}>Спросить</button>
      </form>
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}
