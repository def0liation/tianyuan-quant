import { NodeStatus, KillSwitchLevel, PermissionState } from '../types'

export function getStatusColor(status: NodeStatus | KillSwitchLevel | PermissionState) {
  switch (status) {
    case 'PASS':
      return 'bg-emerald-100 text-emerald-800 border-emerald-200'
    case 'WARN':
      return 'bg-amber-100 text-amber-800 border-amber-200'
    case 'REVIEW_ONLY':
      return 'bg-sky-100 text-sky-800 border-sky-200'
    case 'BLOCK_BUY':
      return 'bg-rose-100 text-rose-800 border-rose-200'
    case 'FAIL':
      return 'bg-red-100 text-red-800 border-red-200'
    case 'SKIPPED':
      return 'bg-slate-100 text-slate-800 border-slate-200'
    case 'RUNNING':
      return 'bg-indigo-100 text-indigo-800 border-indigo-200'
    case 'WAIT':
      return 'bg-slate-50 text-slate-700 border-slate-200'
    case 'NONE':
      return 'bg-emerald-100 text-emerald-800 border-emerald-200'
    case 'SOFT':
      return 'bg-amber-100 text-amber-800 border-amber-200'
    case 'HARD':
      return 'bg-rose-100 text-rose-800 border-rose-200'
    case 'COMPLIANCE':
      return 'bg-black text-white border-black'
    case 'ALLOW':
      return 'bg-emerald-100 text-emerald-800 border-emerald-200'
    case 'ALLOW_WITH_DISCOUNT':
      return 'bg-amber-100 text-amber-800 border-amber-200'
    case 'BLOCKED':
      return 'bg-rose-100 text-rose-800 border-rose-200'
    default:
      return 'bg-slate-100 text-slate-800 border-slate-200'
  }
}
