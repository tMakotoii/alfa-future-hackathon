import { NavLink, Outlet } from 'react-router-dom'
import ContextSwitcher from './ContextSwitcher'
import { useSession } from '../session'
import { fmtBn } from '../api'

const NAV = [
  { to: '/', label: 'Главная', end: true },
  { to: '/accounts', label: 'Счета', stub: true },
  { to: '/payments', label: 'Платежи', stub: true },
  { to: '/feed', label: 'Инсайты' },
  { to: '/metrics', label: 'Метрики' },
]

export default function Layout() {
  const { me } = useSession()
  return (
    <div className="min-h-screen flex flex-col">
      <header className="h-14 bg-white border-b border-gray-200 flex items-center px-4 md:px-6 gap-4">
        <div className="flex items-center gap-2 font-semibold">
          <span className="w-7 h-7 rounded-md bg-brand text-white grid place-items-center text-sm">Б</span>
          <span className="hidden sm:inline">Бизнес-банк</span>
          <span className="text-xs font-normal text-gray-400 hidden md:inline">· прототип</span>
        </div>
        <div className="flex-1" />
        <ContextSwitcher />
      </header>
      <div className="flex flex-1">
        <aside className="hidden md:flex w-56 flex-col border-r border-gray-200 bg-white p-3 gap-1">
          {me && (
            <div className="px-3 py-3 mb-2 rounded-lg bg-gray-50 text-sm">
              <div className="font-medium">{me.display_name}</div>
              <div className="text-gray-500">{fmtBn(me.summary.revenue_total)} · {me.summary.n_companies} компаний</div>
            </div>
          )}
          {NAV.map(n => n.stub
            ? <span key={n.to} className="px-3 py-2 rounded-lg text-sm text-gray-400 cursor-not-allowed" title="Заглушка прототипа">{n.label}</span>
            : <NavLink key={n.to} to={n.to} end={n.end}
                className={({ isActive }) => `px-3 py-2 rounded-lg text-sm ${isActive ? 'bg-brand-soft text-brand-dark font-medium' : 'hover:bg-gray-100'}`}>
                {n.label}{n.to === '/feed' && <span className="ml-2 text-[10px] uppercase bg-brand text-white rounded px-1">AI</span>}
              </NavLink>)}
        </aside>
        <main className="flex-1 min-w-0 p-4 md:p-6"><Outlet /></main>
      </div>
      <footer className="text-center text-xs text-gray-400 py-3 border-t border-gray-200 bg-white">
        Прототип для хакатона. Не является продуктом банка.
      </footer>
    </div>
  )
}
