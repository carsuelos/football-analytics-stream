// The apps' managed identity and what it may do, deployed by bootstrap.sh into
// the project resource group. It needs rights to grant roles (Owner), which the
// deploy pipeline's identity deliberately lacks: it is Contributor only, so it
// can create resources but never widen anyone's access.
targetScope = 'resourceGroup'

param location string = resourceGroup().location

@description('Name of the user-assigned identity the container apps run as.')
param identityName string = 'id-football-analytics-apps'

var tags = {
  project: 'football-analytics-stream'
  managedBy: 'bicep'
}

// Built-in role ids: https://learn.microsoft.com/azure/role-based-access-control/built-in-roles
var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' = {
  name: identityName
  location: location
  tags: tags
}

// At resource-group scope, so they cover the registry and vault the deploy
// creates later, whatever their (generated) names.
resource roles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for role in [acrPull, keyVaultSecretsUser]: {
    name: guid(resourceGroup().id, identity.id, role)
    properties: {
      principalId: identity.properties.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
    }
  }
]

output identityId string = identity.id
output clientId string = identity.properties.clientId
