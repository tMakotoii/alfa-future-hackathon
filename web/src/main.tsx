import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import './index.css'
import { SessionProvider, useSession } from './session'
import Layout from './components/Layout'
import Login from './pages/Login'
import Home from './pages/Home'
import Feed from './pages/Feed'
import Insight from './pages/Insight'

function Protected() {
  const { me, loading } = useSession()
  if (loading) return <div className="p-8 text-gray-500">Загрузка…</div>
  if (!me) return <Navigate to="/login" replace />
  return <Layout />
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <SessionProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route element={<Protected />}>
            <Route path="/" element={<Home />} />
            <Route path="/feed" element={<Feed />} />
            <Route path="/insight/:newsId" element={<Insight />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  </StrictMode>,
)
