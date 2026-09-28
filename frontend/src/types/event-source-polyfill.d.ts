declare module 'event-source-polyfill' {
  export interface EventSourcePolyfillOptions {
    headers?: Record<string, string>
    withCredentials?: boolean
    heartbeatTimeout?: number
  }

  export class EventSourcePolyfill extends EventSource {
    constructor(url: string, options?: EventSourcePolyfillOptions)
  }

  export const NativeEventSource: typeof EventSource | undefined
}
