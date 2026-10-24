// Secrets the apps read at start-up through their managed identity (Key Vault
// Secrets User, granted by the bootstrap): the Event Hubs connection string and
// the alert webhook, if any. Access is by Azure RBAC, not access policies.
param location string
param suffix string
param tags object

resource vault 'Microsoft.KeyVault/vaults@2025-05-01' = {
  name: 'kv-football-${suffix}'
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    softDeleteRetentionInDays: 7
  }
}

output name string = vault.name
