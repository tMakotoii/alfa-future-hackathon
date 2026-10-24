import { useState } from 'react'
import { api, type Source } from '../api'

const TYPE_LABEL: Record<Source['type'], string> = { news: 'Новость', bank_analytics: 'Аналитика банка', client_data: 'Данные клиента' }

export default function SourceChip({ id, source }: { id: string; source?: Source }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState<{ title: string; body: string; url?: string; note?: string } | null>(null)

  const toggle = async () => {
    setOpen(o => !o)
    if (text || !source) return
    try {
      if (source.type === 'news') {
        const n = await api.newsSource(id)
        setText({ title: n.title, body: n.body, url: n.url, note: `${n.source} · ${new Date(n.published_at).toLocaleDateString('ru-RU')}` })
      } else if (source.type === 'bank_analytics') {
        const m = id.match(/^b:(.+)#p(\d+)$/)
        if (m) {
          const b = await api.bankSource(m[1], Number(m[2]))
          setText({ title: `${b.doc_title}, стр. ${b.page}`, body: b.text, note: `от ${b.doc_date}${b.stale ? ' · материал может быть неактуален' : ''}` })
        }
      } else {
        setText({ title: 'Признак клиента', body: `${id.replace(/^f:/, '')} — источник: ${source.ref}` })
      }
    } catch (e) { setText({ title: 'Источник недоступен', body: (e as Error).message }) }
  }

  if (!source) return <span className="text-[11px] rounded bg-red-50 text-red-600 px-1.5 py-0.5" title="Ссылка не найдена">?{id}</span>
  return (
    <span className="inline">
      <button onClick={toggle} className="text-[11px] rounded bg-gray-100 hover:bg-gray-200 text-gray-600 px-1.5 py-0.5 mr-1"
              title={source.ref}>
        {TYPE_LABEL[source.type]}{source.type === 'bank_analytics' ? `: ${source.ref}`
          : source.type === 'client_data' ? `: ${id.replace(/^f:/, '')}` : ''}
      </button>
      {open && text && (
        <span className="block mt-2 mb-1 rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-700 whitespace-pre-wrap max-h-60 overflow-auto">
          <span className="block font-medium text-gray-900">{text.title}</span>
          {text.note && <span className="block text-gray-400 mb-1">{text.note}</span>}
          {text.body.slice(0, 2500)}
          {text.url && <a className="block mt-2 text-ai underline" href={text.url} target="_blank" rel="noreferrer">Открыть первоисточник</a>}
        </span>
      )}
    </span>
  )
}
