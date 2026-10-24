import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ROLE_LABEL, type FeedItem } from '../api'
import FeedCard from '../components/FeedCard'
import { useSession } from '../session'

export default function Home() {
  const { me, version } = useSession()
  const [top, setTop] = useState<FeedItem[] | null>(null)
  useEffect(() => { setTop(null); api.feed().then(f => setTop(f.slice(0, 3))).catch(() => setTop([])) }, [version])
  if (!me) return null
  return (
    <div className="max-w-5xl space-y-6">
      <h1 className="text-xl font-semibold">Добрый день! <span className="text-gray-400 font-normal">{ROLE_LABEL[me.role]}, {me.display_name}</span></h1>
      <div className="grid sm:grid-cols-2 gap-4">
        {[['Расчётный счёт', '•• 4021'], ['Валютный счёт CNY', '•• 7710']].map(([n, num]) => (
          <div key={num} className="card p-4 opacity-70" title="Заглушка прототипа">
            <div className="text-sm text-gray-500">{n} {num}</div>
            <div className="text-lg font-semibold mt-1 text-gray-400">— демо —</div>
          </div>
        ))}
      </div>
      <section className="card p-5 border-brand/30 ring-1 ring-brand/10">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold">Что важно для вашего бизнеса сегодня</h2>
            <p className="text-xs text-gray-500">События отобраны и объяснены с учётом профиля группы и вашей роли · AI</p>
          </div>
          <Link to="/feed" className="btn-primary">Все инсайты</Link>
        </div>
        {top === null && <div className="text-sm text-gray-400">Загрузка…</div>}
        {top?.length === 0 && <div className="text-sm text-gray-500">Пока нет значимых событий. Новости обновляются каждые 30 минут.</div>}
        <div className="grid gap-3">{top?.map(i => <FeedCard key={i.news_id} item={i} compact />)}</div>
      </section>
    </div>
  )
}
