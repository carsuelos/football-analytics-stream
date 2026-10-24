// One container app, the way all of ours run: as the apps' managed identity
// (which pulls its image and reads its secrets), one revision at a time, with
// the data share mounted read-only at /data if it needs it.
param name string
param location string
param tags object
param environmentId string
param identityId string
param registryServer string
param image string
param args array = []
param env array = []

@description('Key Vault secrets to expose, as { name, keyVaultUrl }; env entries refer to them with secretRef.')
param secrets array = []

@allowed(['external', 'internal', 'none'])
@description('external: on the internet; internal: only to the other apps, at http://<name>; none: no ingress.')
param ingress string = 'none'
param targetPort int = 0

@description('An HTTP path that answers 200 once the app is ready for traffic.')
param readyPath string = ''
param cpu string = '0.25'
param memory string = '0.5Gi'
param minReplicas int = 1
param maxReplicas int = 1
param mountData bool = false

resource app 'Microsoft.App/containerApps@2026-07-01' = {
  name: name
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identityId}': {} }
  }
  properties: {
    environmentId: environmentId
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: [{ server: registryServer, identity: identityId }]
      secrets: [for s in secrets: { name: s.name, keyVaultUrl: s.keyVaultUrl, identity: identityId }]
      ingress: ingress == 'none'
        ? null
        : {
            external: ingress == 'external'
            targetPort: targetPort
            transport: 'http'
            // Inside the environment the apps talk plain HTTP; outside, HTTPS only.
            allowInsecure: ingress == 'internal'
          }
    }
    template: {
      containers: [
        {
          name: name
          image: image
          args: args
          env: env
          resources: { cpu: json(cpu), memory: memory }
          volumeMounts: mountData ? [{ volumeName: 'data', mountPath: '/data' }] : []
          probes: empty(readyPath)
            ? []
            : [
                {
                  type: 'Readiness'
                  httpGet: { path: readyPath, port: targetPort }
                  periodSeconds: 5
                  failureThreshold: 3
                }
              ]
        }
      ]
      volumes: mountData ? [{ name: 'data', storageType: 'AzureFile', storageName: 'data' }] : []
      scale: { minReplicas: minReplicas, maxReplicas: maxReplicas }
    }
  }
}

output fqdn string = ingress == 'none' ? '' : app.properties.configuration.ingress.fqdn
