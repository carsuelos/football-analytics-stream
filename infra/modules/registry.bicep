// The private registry the deploy pushes the four images to.
param location string
param suffix string
param tags object

resource registry 'Microsoft.ContainerRegistry/registries@2025-04-01' = {
  name: 'crfootball${suffix}'
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: {
    // Pulls use the apps' managed identity and pushes the deploy's: no passwords.
    adminUserEnabled: false
  }
}

output name string = registry.name
output loginServer string = registry.properties.loginServer
