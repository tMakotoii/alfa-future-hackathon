import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ROLE_LABEL, type DemoGroup, type Role } from '../api'
import { useSession } from '../session'

export default function ContextSwitcher() {
  const { me, setMe, refresh } = useSession()
  const [groups, setGroups] = useState<DemoGroup[]>([])
  const nav = useNavigate()
  useEffect(() => { if (me?.demo_mode) api.demoGroups().then(setGroups).catch(() => {}) }, [me?.demo_mode])
  if (!me) return null

  const switchTo = async (body: { group_id?: string; role?: Role }) => {
    await api.demoSwitch(body)
    await refresh()
  }
  const isDemo = (g: DemoGroup) => g.display_name.startsWith('Группа «')
  return (
    <div className="flex items-center gap-2 text-sm">
      {me.demo_mode && (
        <select className="input py-1.5 max-w-[14rem]" value={me.group_id} aria-label="Клиент"
                onChange={e => switchTo({ group_id: e.target.value })}>
          <optgroup label="Демо-клиенты">
            {groups.filter(isDemo).map(g => <option key={g.group_id} value={g.group_id}>{g.display_name}</option>)}
          </optgroup>
          <optgroup label="Другие группы > 15 млрд ₽">
            {groups.filter(g => !isDemo(g)).map(g => <option key={g.group_id} value={g.group_id}>{g.display_name}</option>)}
          </optgroup>
        </select>
      )}
      <select className="input py-1.5" value={me.role} aria-label="Роль" disabled={!me.demo_mode}
              onChange={e => switchTo({ role: e.target.value as Role })}>
        {(Object.keys(ROLE_LABEL) as Role[]).map(r => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
      </select>
      <button className="text-gray-500 hover:text-gray-900 px-2"
              onClick={async () => { await fetch('/api/logout', { method: 'POST' }); setMe(null); nav('/login') }}>
        Выйти
      </button>
    </div>
  )
}
