// The Container Apps environment: the network the apps share (they reach each
// other by name, e.g. http://engine), where their logs go, and the managed
// OpenTelemetry agent that forwards their traces to Application Insights. It
// costs nothing by itself on the Consumption plan, so it stays up between
// deployments and its domain, and so the dashboard's URL, never changes.
param location string
param suffix string
param tags object
param workspaceName string
param insightsName string
param storageAccountName string
param shareName string

resource workspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' existing = {
  name: workspaceName
}

resource insights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: insightsName
}

resource account 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: storageAccountName
}

resource environment 'Microsoft.App/managedEnvironments@2026-07-01' = {
  name: 'cae-football-${suffix}'
  location: location
  tags: tags
  properties: {
    // Each app's stdout and stderr, as ContainerAppConsoleLogs_CL.
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    // The agent injects OTEL_EXPORTER_OTLP_ENDPOINT into every app, which turns
    // their tracing on. Only traces: the logs already go to Log Analytics.
    appInsightsConfiguration: {
      connectionString: insights.properties.ConnectionString
    }
    openTelemetryConfiguration: {
      tracesConfiguration: { destinations: ['appInsights'] }
    }
    workloadProfiles: [
      { name: 'Consumption', workloadProfileType: 'Consumption' }
    ]
  }
}

resource data 'Microsoft.App/managedEnvironments/storages@2026-07-01' = {
  parent: environment
  name: 'data'
  properties: {
    azureFile: {
      accountName: account.name
      accountKey: account.listKeys().keys[0].value
      shareName: shareName
      accessMode: 'ReadOnly'
    }
  }
}

output name string = environment.name
output defaultDomain string = environment.properties.defaultDomain
