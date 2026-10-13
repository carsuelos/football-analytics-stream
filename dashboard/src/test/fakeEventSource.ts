/** Stands in for the browser's EventSource, which jsdom does not have. */
export class FakeEventSource extends EventTarget {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2
  static instances: FakeEventSource[] = []

  readyState = FakeEventSource.CONNECTING
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  readonly url: string

  constructor(url: string) {
    super()
    this.url = url
    FakeEventSource.instances.push(this)
  }

  open() {
    this.readyState = FakeEventSource.OPEN
    this.onopen?.()
  }

  send(type: string, data: unknown) {
    this.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }))
  }

  /** Fails like a dropped connection (the browser retries) or an error reply (it gives up). */
  fail(givesUp: boolean) {
    this.readyState = givesUp ? FakeEventSource.CLOSED : FakeEventSource.CONNECTING
    this.onerror?.()
  }

  close() {
    this.readyState = FakeEventSource.CLOSED
  }
}
