import { ReactNode } from 'react'

interface CardProps {
  title?: string
  children: ReactNode
  className?: string
  action?: ReactNode
}

export function Card({ title, children, className = '', action }: CardProps) {
  return (
    <section className={`material-surface ${className}`}>
      {(title || action) ? (
        <div className="material-surface-header">
          {title ? <h2 className="material-surface-title">{title}</h2> : <span />}
          {action}
        </div>
      ) : null}
      {children}
    </section>
  )
}
