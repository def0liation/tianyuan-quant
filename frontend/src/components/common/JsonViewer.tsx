interface JsonViewerProps {
  data: unknown
}

export function JsonViewer({ data }: JsonViewerProps) {
  return (
    <pre className="whitespace-pre-wrap break-words rounded-[var(--institution-radius-md)] border border-[var(--md-sys-color-outline-variant)] bg-[var(--md-sys-color-surface-container-low)] p-4 font-mono text-xs leading-6 text-[var(--md-sys-color-on-surface)] shadow-[var(--md-sys-elevation-1)]">
      {JSON.stringify(data, null, 2)}
    </pre>
  )
}
