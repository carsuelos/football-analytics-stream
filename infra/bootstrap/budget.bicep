// Monthly cost budget on the resource group it is deployed into.
// Emails at 50%, 80% and 100% of actual spend, plus a forecast warning at 100%.
targetScope = 'resourceGroup'

param amount int
param alertEmails array
param startDate string

var actualThresholds = [50, 80, 100]

resource budget 'Microsoft.Consumption/budgets@2024-08-01' = {
  name: 'budget-football-analytics'
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    notifications: union(
      toObject(
        actualThresholds,
        t => 'actual${t}',
        t => {
          enabled: true
          operator: 'GreaterThanOrEqualTo'
          threshold: t
          thresholdType: 'Actual'
          contactEmails: alertEmails
        }
      ),
      {
        forecast100: {
          enabled: true
          operator: 'GreaterThan'
          threshold: 100
          thresholdType: 'Forecasted'
          contactEmails: alertEmails
        }
      }
    )
  }
}
