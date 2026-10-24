import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ROLE_LABEL, type Insight as InsightT, type TraceStep } from '../api'
import AffectedMembers from '../components/AffectedMembers'
import ChatPanel from '../components/ChatPanel'
import ClaimList from '../components/ClaimList'
import FeedbackBar from '../components/FeedbackBar'
import ImpactBadge from '../components/ImpactBadge'
import { COMPONENT_LABEL } from '../components/ScoreBadge'
import SourceChip from '../components/SourceChip'
import TracePanel from '../components/TracePanel'
import { useSession } from '../session'

function Section({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <section className="card p-5">
      <h2 className="font-semibold mb-3 flex items-center gap-2">
        <span className="w-6 h-6 rounded-full bg-gray-900 text-white text-xs grid place-items-center">{n}</span>{title}
      </h2>
      {children}
    </section>
  )
}

const PRODUCT_CTA: Record<string, string> = {
  refinancing: 'Обсудить рефинансирование', hedging: 'Обсудить хеджирование', deposit: 'Разместить ликвидность',
  guarantee: 'Обсудить гарантии', leasing: 'Обсудить лизинг',
}

export default function Insight() {
  const { newsId = '' } = useParams()
  const { me } = useSession()
  const [ins, setIns] = useState<InsightT | null>(null)
  const [steps, setSteps] = useState<TraceStep[]>([])
  const [live, setLive] = useState(false)
  const [showTrace, setShowTrace] = useState(false)
  const [error, setError] = useState('')
  const [cta, setCta] = useState('')

  const load = useCallback(async () => {
    try {
      const r = await api.insight(newsId)
      if (r.pending) {
        setLive(true); setSteps([])
        return api.streamTrace(r.trace_id, s => setSteps(prev => [...prev, s]), () => { setLive(false); load() })
      }
      setIns(r.insight)
    } catch (e) { setError((e as Error).message) }
  }, [newsId])

  useEffect(() => {
    let close: (() => void) | undefined
    load().then(c => { close = c ?? undefined })
    return () => close?.()
  }, [load])

  useEffect(() => { if (ins && showTrace && !steps.length) api.trace(ins.trace_id).then(setSteps) }, [ins, showTrace, steps.length])

  if (error) return <div className="card p-6 text-sm text-red-600">{error} · <Link to="/feed" className="underline">к ленте</Link></div>
  if (!ins) return (
    <div className="max-w-3xl space-y-4">
      <div className="card p-6">
        <div className="font-medium">Агент анализирует событие для вашей группы…</div>
        <p className="text-sm text-gray-500 mt-1">Планирует шаги, собирает профиль, контрагентов и позицию банка, затем проверяет вывод.</p>
      </div>
      {live && <div className="card p-5"><TracePanel steps={steps} live /></div>}
    </div>
  )

  const role = me?.role ?? 'CFO'
  const rv = ins.role_views[role]
  return (
    <div className="grid xl:grid-cols-[1fr_24rem] gap-6 max-w-7xl">
      <div className="space-y-4 min-w-0">
        <Link to="/feed" className="text-sm text-gray-500 hover:text-gray-900">← Все инсайты</Link>
        <header className="card p-5">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <ImpactBadge impact={ins.impact} />
            <span className="text-xs text-gray-500">значимость {Math.round(ins.relevance.score * 100)}/100 · акцент для роли «{ROLE_LABEL[role]}»</span>
          </div>
          <h1 className="text-xl font-semibold leading-snug">{rv?.headline || ins.headline}</h1>
          {rv?.focus.length > 0 && <ul className="mt-2 text-sm text-gray-700 list-disc ml-5">{rv.focus.map(f => <li key={f}>{f}</li>)}</ul>}
          {ins.status !== 'ready' && (
            <div className="mt-3 rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm text-amber-800">
              {ins.status === 'rule_only' ? 'Карточка без AI-выводов: показаны факты, разбивка значимости и материалы банка.'
                                          : 'Часть выводов не прошла автоматическую проверку — см. оговорки.'}
            </div>
          )}
          {ins.caveats.length > 0 && <ul className="mt-2 text-xs text-gray-500 list-disc ml-5">{ins.caveats.map(c => <li key={c}>{c}</li>)}</ul>}
        </header>

        <Section n={1} title="Что произошло">
          <div className="text-sm text-gray-500 mb-2">{ins.event.title}{ins.event.date && ` · ${ins.event.date}`}</div>
          <ClaimList claims={ins.event.facts} sources={ins.sources} />
        </Section>

        <Section n={2} title="Почему это важно для вашей группы">
          <ClaimList claims={ins.why_it_matters} sources={ins.sources} />
          {ins.affected_members.length > 0 && <div className="mt-3"><div className="text-xs text-gray-500 mb-1">Затронутые компании группы</div>
            <AffectedMembers members={ins.affected_members} /></div>}
          <details className="mt-3 text-xs text-gray-600">
            <summary className="cursor-pointer text-gray-500">Разбивка значимости</summary>
            <ul className="mt-2 space-y-1">{ins.relevance.components.filter(c => c.value > 0).map(c =>
              <li key={c.name}><b>{COMPONENT_LABEL[c.name] ?? c.name} +{Math.round(c.value * 100)}:</b> {c.evidence}</li>)}</ul>
          </details>
        </Section>

        <Section n={3} title="Возможные последствия">
          {ins.impacts.length ? <ClaimList claims={ins.impacts} sources={ins.sources} />
                              : <p className="text-sm text-gray-500">Последствия не оценивались.</p>}
        </Section>

        <Section n={4} title="Что можно сделать">
          {ins.actions.length ? (
            <ul className="space-y-2">{ins.actions.map((a, i) => (
              <li key={i} className="flex items-start justify-between gap-3 text-sm rounded-lg border border-gray-200 p-3">
                <span>{a.text}</span>
                <button className="btn-ghost py-1 shrink-0" onClick={() => setCta(a.text)}>
                  {(a.product && PRODUCT_CTA[a.product]) || 'Обсудить с менеджером'}
                </button>
              </li>))}
            </ul>
          ) : <p className="text-sm text-gray-500">Конкретных действий не предложено.</p>}
          {cta && <div className="mt-3 rounded-lg bg-emerald-50 border border-emerald-200 p-3 text-sm text-emerald-800">
            Заявка передана персональному менеджеру (демо): «{cta}». <button className="underline ml-2" onClick={() => setCta('')}>Закрыть</button>
          </div>}
        </Section>

        <Section n={5} title="Как оценивает Альфа-Банк">
          {ins.bank_view.available ? <ClaimList claims={ins.bank_view.items} sources={ins.sources} />
                                   : <p className="text-sm text-gray-500">В аналитике Альфа-Банка позиции по этому событию нет.</p>}
        </Section>

        <Section n={6} title="На чём основан вывод">
          <div className="flex flex-wrap gap-1">{ins.sources.filter(s => s.id !== 'f:relevance').map(s => <SourceChip key={s.id} id={s.id} source={s} />)}</div>
          <button className="btn-ghost mt-4" onClick={() => setShowTrace(v => !v)}>{showTrace ? 'Скрыть' : 'Как получен вывод'}</button>
          {showTrace && <div className="mt-4"><TracePanel steps={steps} /></div>}
        </Section>

        <FeedbackBar insightId={ins.insight_id} />
      </div>
      <aside className="xl:sticky xl:top-4 self-start"><ChatPanel insightId={ins.insight_id} sources={ins.sources} /></aside>
    </div>
  )
}
