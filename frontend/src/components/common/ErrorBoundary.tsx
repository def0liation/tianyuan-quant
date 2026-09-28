import { Component, ReactNode } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { ErrorState } from './ErrorState'

interface ErrorBoundaryProps {
  children: ReactNode
  fallbackLabel?: string
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  render() {
    if (this.state.hasError) {
      const retryAction = (
        <button
          onClick={() => {
            this.setState({ hasError: false, error: null })
            window.location.reload()
          }}
          className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-50"
        >
          <RefreshCw size={14} />
          重新加载
        </button>
      )

      return (
        <div className="flex min-h-[200px] flex-col items-center justify-center gap-4">
          <AlertTriangle size={32} className="text-red-500" />
          <ErrorState
            title={this.props.fallbackLabel || '页面渲染发生错误'}
            message={this.state.error?.message || '未知错误'}
            action={retryAction}
          />
        </div>
      )
    }
    return this.props.children
  }
}
