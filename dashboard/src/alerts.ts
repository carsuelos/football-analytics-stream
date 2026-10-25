import type { AlertType } from './schema/alert.schema'

/** What each alert type is called on screen. */
export const ALERT_NAMES: Record<AlertType, string> = {
  momentum_shift: 'Momentum',
  goal_threat: 'Goal threat',
  control_shift: 'Control',
  goal_chance: 'Goal chance (model)',
}

/** The trained model's alerts, shown apart from the rules': in violet, with their own chime. */
export const isModelAlert = (type: AlertType) => type === 'goal_chance'

