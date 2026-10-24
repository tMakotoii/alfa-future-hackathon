import type { TraceStep } from '../api'

const KIND: Record<TraceStep['kind'], [string, string]> = {
  plan: ['План', 'bg-violet-100 text-violet-700'],
  tool: ['Инструмент', 'bg-sky-100 text-sky-700'],
  llm: ['LLM', 'bg-indigo-100 text-indigo-700'],
  check: ['Проверка', 'bg-emerald-100 text-emerald-700'],
  revise: ['Доработка', 'bg-amber-100 text-amber-700'],
}

function brief(v: unknown): string {
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  return s.length > 220 ? s.slice(0, 220) + '…' : s
}

export default function TracePanel({ steps, live = false }: { steps: TraceStep[]; live?: boolean }) {
  const tokens = steps.reduce((a, s) => a + s.tokens, 0)
  const cost = steps.reduce((a, s) => a + s.cost_rub, 0)
  return (
    <div className="space-y-2">
      <div className="text-xs text-gray-500">
        {steps.length} шагов · {tokens.toLocaleString('ru-RU')} токенов · {cost.toFixed(2)} ₽ {live && <span className="animate-pulse">· агент работает…</span>}
      </div>
      <ol className="relative border-l border-gray-200 ml-2 space-y-3">
        {steps.map(s => {
          const out = s.output as Record<string, unknown> | null
          const rejected = out && typeof out === 'object' && 'rejected' in out
          const [label, cls] = KIND[s.kind] ?? ['Шаг', 'bg-gray-100']
          return (
            <li key={s.idx} className="ml-4">
              <span className="absolute -left-1.5 w-3 h-3 rounded-full bg-white border-2 border-gray-300" />
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className={`rounded px-1.5 py-0.5 ${cls}`}>{label}</span>
                <span className={`font-mono ${rejected ? 'text-red-600 line-through' : 'text-gray-800'}`}>{s.name}</span>
                <span className="text-gray-400">{s.ms} мс{s.tokens ? ` · ${s.tokens} ток. · ${s.cost_rub.toFixed(3)} ₽` : ''}</span>
              </div>
              <details className="text-xs text-gray-600 mt-1">
                <summary className="cursor-pointer text-gray-500">{rejected ? `Отклонено: ${brief(out!.rejected)}` : brief(s.output)}</summary>
                <pre className="mt-1 whitespace-pre-wrap break-all bg-gray-50 rounded p-2 max-h-64 overflow-auto">
{JSON.stringify({ вход: s.input, результат: s.output }, null, 2)}
                </pre>
              </details>
            </li>
          )
        })}
      </ol>
    </div>
  )
}
