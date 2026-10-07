// Free one-time Azure setup: the project resource group and a monthly budget alert.
// Deployed at subscription scope by bootstrap.sh (az deployment sub create).
targetScope = 'subscription'

@description('Azure region for the resource group (and, later, all project resources).')
param location string = 'westus2'

@description('Name of the project resource group.')
param resourceGroupName string = 'rg-football-analytics'

@description('Monthly budget in the billing currency (USD).')
param budgetAmount int = 50

@description('Email addresses that receive budget alerts.')
param alertEmails array

@description('First day of the first budget month (YYYY-MM-01). Keep it fixed so re-runs do not change it.')
param budgetStartDate string = '2026-10-01'

var tags = {
  project: 'football-analytics-stream'
  managedBy: 'bicep'
}

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module budget 'budget.bicep' = {
  name: 'budget'
  scope: rg
  params: {
    amount: budgetAmount
    alertEmails: alertEmails
    startDate: budgetStartDate
  }
}

output resourceGroupName string = rg.name
output resourceGroupId string = rg.id
