import { useEffect, useState } from 'react'
import { api } from '../api'

interface M {
  insights: Record<string, number>; groundedness: number | null; bank_view_share: number | null; avg_revisions: number | null
  cost_today_rub: number; budget_rub: number; budget_level: string; cache_hit_rate: number | null
  avg_cost_per_insight_rub: number | null; feedback: Record<string, number>
  last_eval: { summary: Record<string, number> } | null
}

const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)
const LEVEL: Record<string, string> = { normal: 'норма', fallback: 'экономия (fallback-модели)', cache_only: 'только кэш' }

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs text-gray-500">{label}</div>
      <div className="text-2xl font-semibold tabular-nums mt-1">{value}</div>
      {hint && <div className="text-xs text-gray-400 mt-1">{hint}</div>}
    </div>
  )
}

export default function Metrics() {
  const [m, setM] = useState<M | null>(null)
  useEffect(() => { api.metrics().then(x => setM(x as unknown as M)) }, [])
  if (!m) return <div className="text-sm text-gray-400">Загрузка…</div>
  const ev = m.last_eval?.summary
  return (
    <div className="max-w-5xl space-y-6">
      <h1 className="text-xl font-semibold">Качество и стоимость AI</h1>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Tile label="Утверждений с источником" value={pct(m.groundedness)} hint="groundedness" />
        <Tile label="Инсайтов с позицией банка" value={pct(m.bank_view_share)} />
        <Tile label="Доработок на инсайт" value={m.avg_revisions?.toFixed(2) ?? '—'} hint="итерации самопроверки" />
        <Tile label="Инсайтов" value={String(m.insights.total)}
              hint={`готово ${m.insights.ready} · частично ${m.insights.degraded} · без AI ${m.insights.rule_only}`} />
        <Tile label="Расход сегодня" value={`${m.cost_today_rub.toFixed(2)} ₽`} hint={`из ${m.budget_rub} ₽ · режим: ${LEVEL[m.budget_level] ?? m.budget_level}`} />
        <Tile label="Стоимость инсайта" value={m.avg_cost_per_insight_rub === null ? '—' : `${m.avg_cost_per_insight_rub.toFixed(2)} ₽`} />
        <Tile label="Попаданий в кэш LLM" value={pct(m.cache_hit_rate)} />
        <Tile label="Отзывы" value={`👍 ${m.feedback.up} · 👎 ${m.feedback.down}`}
              hint={`не релевантно ${m.feedback.irrelevant} · неверно ${m.feedback.wrong}`} />
      </div>
      <section className="card p-5">
        <h2 className="font-semibold mb-2">Золотой набор (scripts/eval_golden.py)</h2>
        {ev ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div>Кейсов: <b>{ev.cases}</b></div>
            <div>Groundedness: <b>{pct(ev.groundedness)}</b></div>
            <div>Ожидаемые признаки клиента: <b>{pct(ev.features)}</b></div>
            <div>Ожидаемые факторы: <b>{pct(ev.factors)}</b></div>
            <div>С позицией банка: <b>{pct(ev.bank_view_share)}</b></div>
            <div>Прошли проверку: <b>{pct(ev.ready_share)}</b></div>
            <div>Доработок: <b>{ev.revisions}</b></div>
            <div>₽ на кейс: <b>{ev.cost_rub}</b></div>
          </div>
        ) : <p className="text-sm text-gray-500">Прогона ещё не было.</p>}
      </section>
    </div>
  )
}
