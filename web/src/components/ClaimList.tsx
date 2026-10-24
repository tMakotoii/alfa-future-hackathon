import type { Claim, Source } from '../api'
import SourceChip from './SourceChip'

export const ORIGIN: Record<Claim['origin'], { label: string; cls: string; dot: string }> = {
  fact: { label: 'Факт', cls: 'border-fact/30 bg-fact-soft', dot: 'bg-fact' },
  bank: { label: 'Мнение Альфа-Банка', cls: 'border-bank/30 bg-bank-soft', dot: 'bg-bank' },
  ai: { label: 'Вывод AI', cls: 'border-ai/30 bg-ai-soft', dot: 'bg-ai' },
}

type ClaimLike = Claim & { doc_date?: string | null; stale?: boolean; type?: string; horizon?: string; confidence?: string }

export default function ClaimList({ claims, sources }: { claims: ClaimLike[]; sources: Source[] }) {
  const byId = Object.fromEntries(sources.map(s => [s.id, s]))
  return (
    <ul className="space-y-2">
      {claims.map((c, i) => {
        const o = ORIGIN[c.origin]
        return (
          <li key={i} className={`rounded-lg border-l-4 border px-3 py-2 text-sm ${o.cls}`}>
            <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-gray-500 mb-0.5">
              <span className={`w-1.5 h-1.5 rounded-full ${o.dot}`} />{o.label}
              {c.type && <span className={c.type === 'risk' ? 'text-red-600' : 'text-emerald-600'}>· {c.type === 'risk' ? 'риск' : 'возможность'}</span>}
              {c.horizon && <span>· {c.horizon}</span>}
              {c.confidence && <span>· уверенность: {{ low: 'низкая', med: 'средняя', high: 'высокая' }[c.confidence]}</span>}
              {c.doc_date && <span>· документ от {c.doc_date}</span>}
              {c.stale && <span className="text-amber-600 normal-case">· может быть неактуален</span>}
            </div>
            <div>{c.text}</div>
            {c.source_ids.length > 0 && <div className="mt-1">{c.source_ids.map(id => <SourceChip key={id} id={id} source={byId[id]} />)}</div>}
          </li>
        )
      })}
    </ul>
  )
}
