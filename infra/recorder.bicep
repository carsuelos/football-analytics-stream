// The price recorder on a schedule (make cloud-record): the markets service
// run as a Container Apps job that records every league's prices to a market
// tape for a few hours, then stops. Nothing else of the stack needs to run.
//
// It writes to its own share, `markets` (the data share is read-only), as
// <UTC date>/<league>.jsonl, which make cloud-tapes downloads into data/markets.
// Deployed on its own, next to the base stage (main.bicep), incrementally.
param location string = resourceGroup().location
param environmentName string
param storageAccountName string
param registryServer string
param identityName string

@description('The markets image tag to run (make cloud-record builds and pushes it).')
param imageTag string

@description('When to start, as a cron expression in UTC, e.g. "0 13 25 10 *".')
param cron string

@description('How long to record, in minutes.')
@minValue(10)
@maxValue(1440)
param minutes int

param tags object = { project: 'football-analytics' }

resource account 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: storageAccountName
}

resource files 'Microsoft.Storage/storageAccounts/fileServices@2025-01-01' existing = {
  parent: account
  name: 'default'
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2025-01-01' = {
  parent: files
  name: 'markets'
  properties: { shareQuota: 1 }
}

resource environment 'Microsoft.App/managedEnvironments@2026-07-01' existing = {
  name: environmentName
}

resource storage 'Microsoft.App/managedEnvironments/storages@2026-07-01' = {
  parent: environment
  name: 'markets'
  properties: {
    azureFile: {
      accountName: account.name
      accountKey: account.listKeys().keys[0].value
      shareName: share.name
      accessMode: 'ReadWrite'
    }
  }
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: identityName
}

resource job 'Microsoft.App/jobs@2026-07-01' = {
  name: 'job-markets-recorder'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Schedule'
      scheduleTriggerConfig: { cronExpression: cron, parallelism: 1, replicaCompletionCount: 1 }
      // It stops itself after `minutes` (-for); the timeout is a backstop.
      replicaTimeout: minutes * 60 + 900
      replicaRetryLimit: 1
      registries: [{ server: registryServer, identity: identity.id }]
    }
    template: {
      containers: [
        {
          name: 'markets'
          image: '${registryServer}/markets:${imageTag}'
          args: ['-record', '/data/markets', '-for', '${minutes}m']
          env: [{ name: 'LOG_FORMAT', value: 'json' }]
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          volumeMounts: [{ volumeName: 'markets', mountPath: '/data/markets' }]
        }
      ]
      volumes: [{ name: 'markets', storageType: 'AzureFile', storageName: storage.name }]
    }
  }
}

output job string = job.name
output share string = share.name
