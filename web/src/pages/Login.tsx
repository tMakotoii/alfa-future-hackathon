import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ROLE_LABEL, type Role } from '../api'
import { useSession } from '../session'

const ACCOUNTS: { prefix: string; name: string; note: string }[] = [
  { prefix: 'opt', name: 'Группа «Опт-Импорт»', note: 'Оптовая торговля, 303 млрд ₽, ВЭД и лизинг' },
  { prefix: 'stroy', name: 'Группа «СтройГрупп»', note: 'Строительство, 220 млрд ₽, кредиты и лизинг' },
  { prefix: 'auto', name: 'Группа «АвтоХолдинг»', note: 'Автодилер, 56 млрд ₽, кредитная нагрузка' },
]

export default function Login() {
  const { refresh } = useSession()
  const nav = useNavigate()
  const [error, setError] = useState('')
  const enter = async (login: string) => {
    try { await api.login(login); await refresh(); nav('/') } catch (e) { setError((e as Error).message) }
  }
  return (
    <div className="min-h-screen grid place-items-center p-4">
      <div className="w-full max-w-3xl">
        <div className="flex items-center gap-2 font-semibold text-lg mb-1">
          <span className="w-8 h-8 rounded-md bg-brand text-white grid place-items-center">Б</span> Бизнес-банк · вход
        </div>
        <p className="text-sm text-gray-500 mb-6">Тестовые учётные записи прототипа: выберите клиента и роль пользователя.</p>
        <div className="grid md:grid-cols-3 gap-4">
          {ACCOUNTS.map(a => (
            <div key={a.prefix} className="card p-4">
              <div className="font-medium">{a.name}</div>
              <div className="text-xs text-gray-500 mb-3">{a.note}</div>
              <div className="flex flex-col gap-2">
                {(Object.keys(ROLE_LABEL) as Role[]).map(r => (
                  <button key={r} className="btn-ghost justify-between" onClick={() => enter(`${a.prefix}-${r.toLowerCase()}`)}>
                    {ROLE_LABEL[r]} <span className="text-gray-400 text-xs">{a.prefix}-{r.toLowerCase()}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
        {error && <p className="text-sm text-red-600 mt-4">{error}</p>}
        <p className="text-xs text-gray-400 mt-8 text-center">Прототип для хакатона. Не является продуктом банка.</p>
      </div>
    </div>
  )
}
