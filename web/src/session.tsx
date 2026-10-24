import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api, type Me } from './api'

interface Session { me: Me | null; loading: boolean; refresh: () => Promise<void>; setMe: (m: Me | null) => void; version: number }
const Ctx = createContext<Session>(null as unknown as Session)

export function SessionProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  const [version, setVersion] = useState(0)  // растёт при смене клиента/роли — страницы перезагружают данные
  const refresh = useCallback(async () => {
    try { setMe(await api.me()) } catch { setMe(null) } finally { setLoading(false); setVersion(v => v + 1) }
  }, [])
  useEffect(() => { refresh() }, [refresh])
  return <Ctx.Provider value={{ me, loading, refresh, setMe, version }}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export const useSession = () => useContext(Ctx)
