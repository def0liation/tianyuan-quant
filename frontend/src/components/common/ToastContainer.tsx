import { useToastStore } from '../../store/useToastStore'
import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-react'

const iconMap = {
  success: CheckCircle,
  error: AlertCircle,
  warning: AlertTriangle,
  info: Info,
}

const styleMap = {
  success: 'border-[var(--md-sys-color-success-container)] bg-[var(--md-sys-color-success-container)] text-[var(--md-sys-color-on-success-container)]',
  error: 'border-[var(--md-sys-color-error-container)] bg-[var(--md-sys-color-error-container)] text-[var(--md-sys-color-on-error-container)]',
  warning: 'border-[var(--md-sys-color-warning-container)] bg-[var(--md-sys-color-warning-container)] text-[var(--md-sys-color-on-warning-container)]',
  info: 'border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface)] text-[var(--md-sys-color-on-surface)]',
}

const iconColorMap = {
  success: 'text-[var(--md-sys-color-success)]',
  error: 'text-[var(--md-sys-color-error)]',
  warning: 'text-[var(--md-sys-color-warning)]',
  info: 'text-[var(--md-sys-color-primary)]',
}

export function ToastContainer() {
  const { toasts, removeToast } = useToastStore()

  if (toasts.length === 0) return null

  return (
    <div className="fixed right-4 top-4 z-[9999] flex w-[calc(100%-2rem)] max-w-sm flex-col gap-2">
      {toasts.map((toast) => {
        const Icon = iconMap[toast.type]
        return (
          <div
            key={toast.id}
            className={`flex items-start gap-3 rounded-[var(--institution-radius-md)] border px-4 py-3 shadow-[var(--md-sys-elevation-2)] transition-all ${styleMap[toast.type]}`}
          >
            <Icon size={18} className={`mt-0.5 shrink-0 ${iconColorMap[toast.type]}`} />
            <span className="flex-1 text-sm leading-5">{toast.message}</span>
            <button
              onClick={() => removeToast(toast.id)}
              className="shrink-0 rounded-full p-1 hover:bg-black/5"
            >
              <X size={14} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
