import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, TOPIC_LABEL, type FeedItem } from '../api'
import FeedCard from '../components/FeedCard'
import { useSession } from '../session'

export default function Feed() {
  const { version } = useSession()
  const nav = useNavigate()
  const [items, setItems] = useState<FeedItem[] | null>(null)
  const [impact, setImpact] = useState('')
  const [topic, setTopic] = useState('')
  const [days, setDays] = useState(7)
  const [manual, setManual] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    setItems(null)
    api.feed({ impact, topic, days }).then(setItems).catch(e => { setError(e.message); setItems([]) })
  }, [impact, topic, days, version])

  const submit = async () => {
    setSending(true); setError('')
    const v = manual.trim()
    try {
      const r = await api.manualNews(/^https?:\/\//.test(v) ? { url: v } : { text: v })
      nav(`/insight/${r.news_id}`)
    } catch (e) { setError((e as Error).message) } finally { setSending(false) }
  }

  return (
    <div className="max-w-5xl space-y-4">
      <h1 className="text-xl font-semibold">Инсайты для вашего бизнеса</h1>
      <div className="card p-4 flex flex-wrap gap-3 items-center text-sm">
        <select className="input" value={impact} onChange={e => setImpact(e.target.value)} aria-label="Влияние">
          <option value="">Все влияния</option><option value="risk">Риски</option>
          <option value="opportunity">Возможности</option><option value="neutral">Нейтральные</option>
        </select>
        <select className="input" value={topic} onChange={e => setTopic(e.target.value)} aria-label="Тема">
          <option value="">Все темы</option>
          {Object.entries(TOPIC_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className="input" value={days} onChange={e => setDays(Number(e.target.value))} aria-label="Период">
          <option value={1}>За сутки</option><option value={7}>За неделю</option><option value={30}>За месяц</option>
        </select>
      </div>
      <div className="card p-4 space-y-2">
        <label className="text-sm font-medium" htmlFor="manual">Проанализировать новость: вставьте текст или ссылку</label>
        <textarea id="manual" className="input w-full h-20" value={manual} onChange={e => setManual(e.target.value)}
                  placeholder="Например: «Правительство повысило утилизационный сбор на грузовики с 1 января…» или https://…" />
        <div className="flex items-center gap-3">
          <button className="btn-primary" disabled={!manual.trim() || sending} onClick={submit}>
            {sending ? 'Отправляем…' : 'Проанализировать для моей компании'}
          </button>
          {error && <span className="text-sm text-red-600">{error}</span>}
        </div>
      </div>
      {items === null && <div className="text-sm text-gray-400">Загрузка…</div>}
      {items?.length === 0 && <div className="text-sm text-gray-500">Нет событий по выбранным фильтрам.</div>}
      <div className="grid gap-3">{items?.map(i => <FeedCard key={i.news_id} item={i} />)}</div>
    </div>
  )
}
