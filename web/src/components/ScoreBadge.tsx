import type { ScoreComponent } from '../api'

export const COMPONENT_LABEL: Record<string, string> = {
  sector: 'Отрасль', macro: 'Макрофакторы', products: 'Продукты банка', counterparties: 'Контрагенты',
  region: 'Регион', freshness: 'Свежесть', bank_view: 'Позиция банка',
}

export default function ScoreBadge({ score, components }: { score: number; components: ScoreComponent[] }) {
  return (
    <span className="relative group inline-block">
      <span className="inline-flex items-center gap-1 rounded-md bg-gray-900 text-white text-xs px-2 py-0.5 tabular-nums cursor-help">
        {Math.round(score * 100)}<span className="text-gray-400">/100</span>
      </span>
      <span className="invisible group-hover:visible absolute right-0 z-20 mt-2 w-80 card p-3 text-xs text-gray-700 space-y-1.5">
        <span className="block font-medium text-gray-900 mb-1">Почему в ленте — разбивка значимости</span>
        {components.filter(c => c.value > 0).sort((a, b) => b.value - a.value).map(c => (
          <span key={c.name} className="flex gap-2">
            <span className="w-10 shrink-0 tabular-nums text-right font-medium">+{Math.round(c.value * 100)}</span>
            <span><span className="font-medium">{COMPONENT_LABEL[c.name] ?? c.name}:</span> {c.evidence}</span>
          </span>
        ))}
      </span>
    </span>
  )
}
