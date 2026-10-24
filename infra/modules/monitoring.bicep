// Where logs and traces go: a Log Analytics workspace, with Application
// Insights on top of it for traces and the application map.
param location string
param suffix string
param tags object

@description('Most log data a day, in GB: ingestion stops there until the next day, so a noisy bug cannot run up the bill.')
param dailyCapGb string = '0.5'

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  name: 'log-football-${suffix}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json(dailyCapGb) }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-football-${suffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
  }
}

output workspaceName string = workspace.name
output insightsName string = insights.name
