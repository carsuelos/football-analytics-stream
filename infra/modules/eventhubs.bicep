// The broker while the apps run: an Event Hubs namespace, which speaks Kafka on
// port 9093 (Standard tier; Basic has no Kafka). Each event hub is a topic.
// Its connection string goes into Key Vault for the apps, never into outputs.
param location string
param suffix string
param tags object
param vaultName string

@description('The topics: the broadcast, and what the engine publishes.')
param topics array = ['events', 'metrics', 'alerts']

resource namespace 'Microsoft.EventHub/namespaces@2026-01-01' = {
  name: 'evhns-football-${suffix}'
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Standard', capacity: 1 }
  properties: {
    kafkaEnabled: true
    minimumTlsVersion: '1.2'
  }
}

resource hubs 'Microsoft.EventHub/namespaces/eventhubs@2026-01-01' = [
  for topic in topics: {
    parent: namespace
    name: topic
    properties: {
      partitionCount: 3
      // A day is plenty: the engine only needs the current match.
      messageRetentionInDays: 1
    }
  }
]

// Send and listen, for the three apps; no manage rights.
resource apps 'Microsoft.EventHub/namespaces/authorizationRules@2026-01-01' = {
  parent: namespace
  name: 'apps'
  properties: { rights: ['Send', 'Listen'] }
}

resource vault 'Microsoft.KeyVault/vaults@2025-05-01' existing = {
  name: vaultName
}

resource secret 'Microsoft.KeyVault/vaults/secrets@2025-05-01' = {
  parent: vault
  name: 'eventhubs-connection-string'
  properties: { value: apps.listKeys().primaryConnectionString }
}

output bootstrapServers string = '${namespace.name}.servicebus.windows.net:9093'
output secretUri string = secret.properties.secretUri
output namespaceName string = namespace.name
