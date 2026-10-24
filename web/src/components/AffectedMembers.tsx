import type { Insight } from '../api'

export default function AffectedMembers({ members }: { members: Insight['affected_members'] }) {
  if (!members.length) return null
  return (
    <div className="flex flex-wrap gap-2">
      {members.map(m => (
        <span key={m.uid} className="text-xs rounded-lg bg-gray-100 px-2 py-1" title={m.uid}>
          <span className="font-medium">{m.alias || m.uid}</span>{m.reason && <span className="text-gray-500"> · {m.reason}</span>}
        </span>
      ))}
    </div>
  )
}
