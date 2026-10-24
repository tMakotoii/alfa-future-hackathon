import { Link } from 'react-router-dom'
import type { FeedItem } from '../api'
import ImpactBadge from './ImpactBadge'
import ScoreBadge from './ScoreBadge'

const STATUS: Record<string, string> = { ready: '', degraded: 'проверено частично', rule_only: 'без AI', none: 'анализ по запросу' }

export function whyLine(item: FeedItem): string {
  const top = [...item.components].filter(c => !['freshness', 'region', 'bank_view'].includes(c.name))
    .sort((a, b) => b.value - a.value)[0]
  return top && top.value > 0 ? top.evidence : 'Общее событие для бизнеса'
}

export default function FeedCard({ item, compact = false }: { item: FeedItem; compact?: boolean }) {
  return (
    <Link to={`/insight/${item.news_id}`} className="card p-4 block hover:border-gray-300 hover:shadow transition">
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <ImpactBadge impact={item.impact_hint} />
            {STATUS[item.insight_status] && <span className="text-xs text-gray-400">{STATUS[item.insight_status]}</span>}
          </div>
          <div className="font-medium leading-snug">{item.headline}</div>
          {item.headline !== item.title && !compact && <div className="text-sm text-gray-500 mt-1">{item.title}</div>}
          <div className="text-sm text-gray-700 mt-2"><span className="text-gray-400">Почему важно вам: </span>{whyLine(item)}</div>
          <div className="text-xs text-gray-400 mt-2">
            {item.source} · {new Date(item.published_at).toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}
          </div>
        </div>
        <ScoreBadge score={item.score} components={item.components} />
      </div>
    </Link>
  )
}
