export type Origin = 'fact' | 'bank' | 'ai'
export type Role = 'CEO' | 'CFO' | 'TREASURER'
export type Impact = 'risk' | 'opportunity' | 'neutral' | 'mixed'
export type InsightStatus = 'ready' | 'degraded' | 'rule_only' | 'none'

export interface Claim { text: string; origin: Origin; source_ids: string[] }
export interface Source { id: string; type: 'news' | 'bank_analytics' | 'client_data'; ref: string }
export interface ScoreComponent { name: string; value: number; evidence: string }

export interface FeedItem {
  news_id: string; title: string; source: string; published_at: string; score: number
  components: ScoreComponent[]; impact_hint: Impact; topics: string[]; headline: string; insight_status: InsightStatus
}

export interface ImpactClaim extends Claim { type: 'risk' | 'opportunity'; horizon: string; confidence: 'low' | 'med' | 'high' }
export interface BankItem extends Claim { doc_date: string | null; stale: boolean }

export interface Insight {
  insight_id: string; group_id: string; news_id: string; trace_id: string; status: Exclude<InsightStatus, 'none'>
  impact: Impact; headline: string
  event: { title: string; date: string | null; facts: Claim[] }
  relevance: { score: number; components: ScoreComponent[] }
  affected_members: { uid: string; alias: string; reason: string }[]
  why_it_matters: Claim[]; impacts: ImpactClaim[]
  bank_view: { available: boolean; items: BankItem[] }
  actions: { text: string; product: string | null }[]
  role_views: Record<Role, { headline: string; focus: string[] }>
  caveats: string[]; sources: Source[]
}

export interface TraceStep {
  idx: number; kind: 'plan' | 'tool' | 'llm' | 'check' | 'revise'; name: string
  input: unknown; output: unknown; tokens: number; cost_rub: number; ms: number; ts: string
}

export interface Me {
  login: string; group_id: string; role: Role; display_name: string; demo_mode: boolean
  summary: { revenue_total: number; n_companies: number; sector_mix: { okved2: string; name: string; share: number }[]; regions: string[] }
}

export interface DemoGroup { group_id: string; display_name: string; revenue_total: number; main_okved2: string }
export interface ChatAnswer { claims: Claim[]; sources: Source[]; trace_id: string }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json', ...init?.headers } : init?.headers,
  })
  if (!r.ok) {
    let detail = r.statusText
    try { const j = await r.json(); detail = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail) } catch { /* not json */ }
    throw new ApiError(r.status, detail)
  }
  return r.json() as Promise<T>
}

const post = <T,>(path: string, body: unknown) => req<T>(path, { method: 'POST', body: JSON.stringify(body) })

export const api = {
  login: (login: string) => post<Me>('/api/login', { login }),
  me: () => req<Me>('/api/me'),
  feed: (p: { impact?: string; topic?: string; days?: number } = {}) => {
    const q = new URLSearchParams(Object.entries(p).filter(([, v]) => v !== undefined && v !== '').map(([k, v]) => [k, String(v)]))
    return req<FeedItem[]>(`/api/feed?${q}`)
  },
  insight: async (newsId: string): Promise<{ pending: true; trace_id: string } | { pending: false; insight: Insight }> => {
    const r = await fetch(`/api/insights/${newsId}`, { credentials: 'same-origin' })
    if (r.status === 202) return { pending: true, trace_id: (await r.json()).trace_id }
    if (!r.ok) throw new ApiError(r.status, (await r.json().catch(() => ({}))).detail ?? r.statusText)
    return { pending: false, insight: await r.json() }
  },
  trace: (id: string) => req<TraceStep[]>(`/api/traces/${id}`),
  streamTrace: (id: string, onStep: (s: TraceStep) => void, onDone: (status: string) => void) => {
    const es = new EventSource(`/api/traces/${id}/stream`)
    es.addEventListener('step', e => onStep(JSON.parse((e as MessageEvent).data)))
    es.addEventListener('done', e => { onDone(JSON.parse((e as MessageEvent).data).status); es.close() })
    es.onerror = () => { es.close(); onDone('error') }
    return () => es.close()
  },
  chat: (insightId: string, question: string) => post<ChatAnswer>(`/api/insights/${insightId}/chat`, { question }),
  chatHistory: (insightId: string) =>
    req<{ role: 'user' | 'assistant'; content: { text?: string; claims?: Claim[]; sources?: Source[] }; trace_id: string }[]>(
      `/api/insights/${insightId}/chat`),
  feedback: (insightId: string, verdict: 'up' | 'down', reason?: string) =>
    post<{ ok: true }>(`/api/insights/${insightId}/feedback`, { verdict, reason }),
  manualNews: (body: { text?: string; url?: string }) => post<{ news_id: string; classified: boolean }>('/api/news/manual', body),
  newsSource: (id: string) => req<{ title: string; body: string; url: string; source: string; published_at: string }>(`/api/sources/news/${id}`),
  bankSource: (docId: string, page: number) =>
    req<{ doc_title: string; doc_date: string; stale: boolean; text: string; page: number }>(`/api/sources/bank/${docId}/${page}`),
  metrics: () => req<Record<string, unknown>>('/api/metrics'),
  demoGroups: () => req<DemoGroup[]>('/api/demo/groups'),
  demoSwitch: (body: { group_id?: string; role?: Role }) => post<Me>('/api/demo/switch', body),
}

export const ROLE_LABEL: Record<Role, string> = { CEO: 'Собственник / CEO', CFO: 'Финансовый директор', TREASURER: 'Казначей' }
export const TOPIC_LABEL: Record<string, string> = {
  monetary_policy: 'Ставка ЦБ', inflation: 'Инфляция', fx: 'Курсы', commodities: 'Сырьё', tax: 'Налоги', trade: 'ВЭД',
  sanctions: 'Санкции', construction: 'Стройка', auto: 'Авто', retail: 'Ритейл', logistics: 'Логистика', industry: 'Промышленность',
  it: 'IT', finance_markets: 'Финрынки', gov_spending: 'Госрасходы', labor: 'Труд', corporate: 'Компании', macro: 'Макро', other: 'Прочее',
}
export const fmtBn = (rub: number) => `${(rub / 1e9).toLocaleString('ru-RU', { maximumFractionDigits: 1 })} млрд ₽`
