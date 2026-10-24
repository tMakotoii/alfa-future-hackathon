import type { Impact } from '../api'

const STYLE: Record<Impact, [string, string]> = {
  risk: ['Риск', 'bg-red-50 text-red-700 ring-red-200'],
  opportunity: ['Возможность', 'bg-emerald-50 text-emerald-700 ring-emerald-200'],
  neutral: ['Нейтрально', 'bg-gray-100 text-gray-600 ring-gray-200'],
  mixed: ['Смешанное влияние', 'bg-amber-50 text-amber-700 ring-amber-200'],
}

export default function ImpactBadge({ impact }: { impact: Impact }) {
  const [label, cls] = STYLE[impact] ?? STYLE.neutral
  return <span className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ring-1 ${cls}`}>{label}</span>
}
