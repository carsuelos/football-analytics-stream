import { act, render, renderHook, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useAlertNotifications, useNotifySetting } from './notifications'
import { NotifyToggle } from './NotifyToggle'
import type { Alert } from './schema/alert.schema'
import type { EngineStatus } from './schema/engine_status.schema'
import { alert, ARGENTINA, FRANCE, status } from './test/factories'

class FakeNotification {
  static permission: NotificationPermission = 'granted'
  static requestPermission = vi.fn(async () => FakeNotification.permission)
  static shown: FakeNotification[] = []
  onclick: (() => void) | null = null
  close = vi.fn()
  title: string
  options: NotificationOptions
  constructor(title: string, options: NotificationOptions) {
    this.title = title
    this.options = options
    FakeNotification.shown.push(this)
  }
}

let focused = false

beforeEach(() => {
  FakeNotification.permission = 'granted'
  FakeNotification.shown = []
  focused = false
  vi.stubGlobal('Notification', FakeNotification)
  vi.spyOn(document, 'hasFocus').mockImplementation(() => focused)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const teams = [ARGENTINA, FRANCE]
const at = (match_clock_s: number, overrides: Partial<EngineStatus> = {}) => status({ period: 2, match_clock_s, ...overrides })

function notifying(alerts: Alert[], s: EngineStatus, on = true) {
  return renderHook(({ alerts, s, on }) => useAlertNotifications(on, alerts, s, teams), { initialProps: { alerts, s, on } })
}

it('notifies of an alert as it happens, once, with its team and moment', () => {
  const a = alert()
  const { rerender } = notifying([a], at(4950))
  expect(FakeNotification.shown).toHaveLength(1)
  const [n] = FakeNotification.shown
  expect(n.title).toBe('Control · France')
  expect(n.options.body).toBe(`82:27 · ${a.message}`)
  rerender({ alerts: [a], s: at(4960), on: true })
  expect(FakeNotification.shown).toHaveLength(1)
  n.onclick!()
  expect(n.close).toHaveBeenCalled()
})

it("doesn't notify of the history sent on a connect or seek, or while rebuilding", () => {
  notifying([alert({ match_clock_s: 4000 }), alert({ id: 'other-half', period: 1, match_clock_s: 4940 })], at(4950))
  notifying([alert({ id: 'b' })], at(4950, { state: 'rebuilding' }))
  expect(FakeNotification.shown).toHaveLength(0)
})

it("doesn't notify while this window is focused, nor later for that alert", () => {
  focused = true
  const { rerender } = notifying([alert()], at(4950))
  focused = false
  rerender({ alerts: [alert()], s: at(4955), on: true })
  expect(FakeNotification.shown).toHaveLength(0)
})

it("doesn't notify when off or without permission", () => {
  notifying([alert()], at(4950), false)
  FakeNotification.permission = 'denied'
  expect(FakeNotification.shown).toHaveLength(0)
})

it('asks for permission when turned on, and remembers the choice', async () => {
  FakeNotification.permission = 'default'
  FakeNotification.requestPermission.mockImplementationOnce(async () => {
    FakeNotification.permission = 'granted'
    return 'granted'
  })
  function Toggle() {
    return <NotifyToggle setting={useNotifySetting()} />
  }
  const { unmount } = render(<Toggle />)
  const toggle = screen.getByRole('switch', { name: 'Notify me' })
  expect(toggle).not.toBeChecked()
  await userEvent.click(toggle)
  expect(FakeNotification.requestPermission).toHaveBeenCalled()
  expect(toggle).toBeChecked()
  unmount()
  render(<Toggle />)
  expect(screen.getByRole('switch', { name: 'Notify me' })).toBeChecked()
  await userEvent.click(screen.getByRole('switch', { name: 'Notify me' }))
  expect(screen.getByRole('switch', { name: 'Notify me' })).not.toBeChecked()
})

it('says when the browser blocks notifications', () => {
  FakeNotification.permission = 'denied'
  act(() => {
    render(<NotifyToggle setting={{ on: false, permission: 'denied', toggle: async () => {} }} />)
  })
  expect(screen.getByRole('switch', { name: 'Notifications blocked' })).toBeDisabled()
})
