import { useState } from 'react'
import { api } from '../api'

export default function FeedbackBar({ insightId }: { insightId: string }) {
  const [sent, setSent] = useState<string | null>(null)
  const [down, setDown] = useState(false)
  const send = async (verdict: 'up' | 'down', reason?: string) => {
    await api.feedback(insightId, verdict, reason)
    setSent(verdict === 'up' ? 'Спасибо! Учтём в ранжировании.' : 'Спасибо, отметили. Аналитики проверят.')
  }
  if (sent) return <p className="text-xs text-gray-500">{sent}</p>
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-gray-500">Полезно?</span>
      <button className="btn-ghost py-1" onClick={() => send('up')} aria-label="Полезно">👍</button>
      <button className="btn-ghost py-1" onClick={() => setDown(true)} aria-label="Не полезно">👎</button>
      {down && (['irrelevant', 'wrong', 'other'] as const).map(r => (
        <button key={r} className="text-xs rounded-full border border-gray-300 px-2 py-1 hover:bg-gray-50" onClick={() => send('down', r)}>
          {{ irrelevant: 'Не релевантно', wrong: 'Неверно', other: 'Другое' }[r]}
        </button>
      ))}
    </div>
  )
}
