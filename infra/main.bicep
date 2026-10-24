// Everything the project runs on in Azure, deployed into the resource group the
// bootstrap made (infra/bootstrap). Two stages:
//
//   - the base, always there and almost free: logs and traces, the registry,
//     Key Vault, the data share and the Container Apps environment;
//   - with deployApps, the running system (apps.bicep): Event Hubs and the five
//     apps, which cost by the hour. `make cloud-down` deletes them again.
//
// The deploy pipeline (.github/workflows/deploy.yml) deploys the base, pushes
// the images and uploads the data, then deploys again with deployApps.
targetScope = 'resourceGroup'

param location string = resourceGroup().location

@description('Also deploy Event Hubs and the apps (needs the images in the registry).')
param deployApps bool = false

@description('The image tag to run, with deployApps.')
param imageTag string = ''

@description('Where the notifier sends alerts (comma-separated URLs). Empty: the stand-in webhook app.')
@secure()
param alertWebhooks string = ''

@description('The dashboard\'s shared password (username: viewer), with deployApps.')
@secure()
param dashboardPassword string = ''

@description('The apps\' managed identity, made by the bootstrap.')
param identityName string = 'id-football-analytics-apps'

// Registry, vault, storage and Event Hubs names are global, so they carry a
// suffix that is the same on every deploy into this resource group.
var suffix = take(uniqueString(resourceGroup().id), 6)
var tags = {
  project: 'football-analytics-stream'
  managedBy: 'bicep'
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: { location: location, suffix: suffix, tags: tags }
}

module registry 'modules/registry.bicep' = {
  name: 'registry'
  params: { location: location, suffix: suffix, tags: tags }
}

module vault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: { location: location, suffix: suffix, tags: tags }
}

module storage 'modules/storage.bicep' = {
  name: 'storage'
  params: { location: location, suffix: suffix, tags: tags }
}

module environment 'modules/environment.bicep' = {
  name: 'environment'
  params: {
    location: location
    suffix: suffix
    tags: tags
    workspaceName: monitoring.outputs.workspaceName
    insightsName: monitoring.outputs.insightsName
    storageAccountName: storage.outputs.accountName
    shareName: storage.outputs.shareName
  }
}

module apps 'modules/apps.bicep' = if (deployApps) {
  name: 'apps'
  params: {
    location: location
    suffix: suffix
    tags: tags
    environmentName: environment.outputs.name
    identityName: identityName
    registryServer: registry.outputs.loginServer
    vaultName: vault.outputs.name
    imageTag: imageTag
    alertWebhooks: alertWebhooks
    dashboardPassword: dashboardPassword
  }
}

output registryName string = registry.outputs.name
output registryServer string = registry.outputs.loginServer
output storageAccountName string = storage.outputs.accountName
output shareName string = storage.outputs.shareName
output environmentName string = environment.outputs.name
output dashboardUrl string = 'https://dashboard.${environment.outputs.defaultDomain}'
output eventHubsNamespace string = deployApps ? apps!.outputs.eventHubsNamespace : ''
