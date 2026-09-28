import { ReactNode } from 'react'

interface ErrorStateProps {
  message?: string
  title?: string
  action?: ReactNode
}

export function ErrorState({ message, title = '页面发生错误', action }: ErrorStateProps) {
  return (
    <div className="rounded-[var(--institution-radius-md)] border border-[var(--md-sys-color-error-container)] bg-[var(--md-sys-color-error-container)] p-8 text-center text-[var(--md-sys-color-on-error-container)] shadow-[var(--md-sys-elevation-1)]">
      <div className="text-lg font-semibold">{title}</div>
      <p className="mt-2 text-sm leading-6">{message ?? '发生未知错误，请稍后重试。'}</p>
      {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
    </div>
  )
}
