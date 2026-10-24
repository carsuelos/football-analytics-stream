// The data the apps read but the images can't carry (StatsBomb's licence lets
// us use it, not redistribute it): an Azure Files share the deploy uploads
// data/statsbomb and data/xt to, mounted read-only at /data, as in Compose.
param location string
param suffix string
param tags object

resource account 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: 'stfootball${suffix}'
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    // Container Apps mounts SMB shares with the account key.
    allowSharedKeyAccess: true
    supportsHttpsTrafficOnly: true
  }
}

resource files 'Microsoft.Storage/storageAccounts/fileServices@2025-01-01' = {
  parent: account
  name: 'default'
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2025-01-01' = {
  parent: files
  name: 'data'
  properties: { shareQuota: 1 }
}

output accountName string = account.name
output shareName string = share.name
