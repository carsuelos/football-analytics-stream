// The running system: Event Hubs and the five apps. `make cloud-up` deploys it
// and `make cloud-down` deletes it, while the rest (main.bicep) stays.
//
//   browser ─HTTPS, password─▶ dashboard ─/api─▶ engine ─▶ simulator
//   simulator ─events─▶ Event Hubs ─events─▶ engine ─alerts, metrics─▶ Event Hubs
//   Event Hubs ─alerts─▶ notifier ─▶ webhook (or ALERT_WEBHOOKS)
//   dashboard ─/api/markets─▶ markets ─▶ Kalshi, Polymarket US, Novig
param location string
param suffix string
param tags object
param environmentName string
param identityName string
param registryServer string
param vaultName string

@description('The image tag to run: the commit the deploy built.')
param imageTag string

@description('Where the notifier sends alerts. Empty: the stand-in webhook app, which prints them to its log.')
@secure()
param alertWebhooks string = ''

@description('The dashboard\'s shared password (username: viewer).')
@secure()
@minLength(12)
param dashboardPassword string

resource environment 'Microsoft.App/managedEnvironments@2026-07-01' existing = {
  name: environmentName
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2024-11-30' existing = {
  name: identityName
}

resource vault 'Microsoft.KeyVault/vaults@2025-05-01' existing = {
  name: vaultName
}

module eventHubs 'eventhubs.bicep' = {
  name: 'eventhubs'
  params: { location: location, suffix: suffix, tags: tags, vaultName: vaultName }
}

resource passwordSecret 'Microsoft.KeyVault/vaults/secrets@2025-05-01' = {
  parent: vault
  name: 'dashboard-password'
  properties: { value: dashboardPassword }
}

resource webhookSecret 'Microsoft.KeyVault/vaults/secrets@2025-05-01' = if (!empty(alertWebhooks)) {
  parent: vault
  name: 'alert-webhooks'
  properties: { value: alertWebhooks }
}

var image = '${registryServer}/{0}:${imageTag}'

// Event Hubs speaks Kafka over SASL_SSL with the namespace's connection string
// as the password. The rest are its recommended librdkafka settings: it closes
// connections idle for 4 minutes, and takes up to 20s to answer a produce.
var kafkaSecret = { name: 'eventhubs', keyVaultUrl: eventHubs.outputs.secretUri }
var kafka = [
  { name: 'KAFKA_BOOTSTRAP_SERVERS', value: eventHubs.outputs.bootstrapServers }
  { name: 'KAFKA_SECURITY_PROTOCOL', value: 'SASL_SSL' }
  { name: 'KAFKA_SASL_MECHANISM', value: 'PLAIN' }
  { name: 'KAFKA_SASL_USERNAME', value: '$ConnectionString' }
  { name: 'KAFKA_SASL_PASSWORD', secretRef: 'eventhubs' }
  { name: 'KAFKA_SOCKET_KEEPALIVE_ENABLE', value: 'true' }
  { name: 'KAFKA_METADATA_MAX_AGE_MS', value: '180000' }
]
var producing = [{ name: 'KAFKA_REQUEST_TIMEOUT_MS', value: '60000' }]
var json = [{ name: 'LOG_FORMAT', value: 'json' }]

module simulator 'app.bicep' = {
  name: 'app-simulator'
  params: {
    location: location
    tags: tags
    environmentId: environment.id
    identityId: identity.id
    registryServer: registryServer
    name: 'simulator'
    image: format(image, 'simulator')
    // The data share is mounted read-only here, so no "Add matches".
    args: ['-library=false']
    secrets: [kafkaSecret]
    env: concat(json, kafka, producing)
    ingress: 'internal'
    targetPort: 8080
    readyPath: '/healthz'
    mountData: true
  }
}

module engine 'app.bicep' = {
  name: 'app-engine'
  params: {
    location: location
    tags: tags
    environmentId: environment.id
    identityId: identity.id
    registryServer: registryServer
    name: 'engine'
    image: format(image, 'engine')
    args: ['--simulator', 'http://simulator', '--source', 'kafka']
    secrets: [kafkaSecret]
    env: concat(json, kafka, producing)
    ingress: 'internal'
    targetPort: 8000
    readyPath: '/api/status'
    cpu: '0.5'
    memory: '1Gi'
    mountData: true
  }
}

module markets 'app.bicep' = {
  name: 'app-markets'
  params: {
    location: location
    tags: tags
    environmentId: environment.id
    identityId: identity.id
    registryServer: registryServer
    name: 'markets'
    image: format(image, 'markets')
    env: json
    ingress: 'internal'
    targetPort: 8090
    readyPath: '/healthz'
  }
}

module dashboard 'app.bicep' = {
  name: 'app-dashboard'
  params: {
    location: location
    tags: tags
    environmentId: environment.id
    identityId: identity.id
    registryServer: registryServer
    name: 'dashboard'
    image: format(image, 'dashboard')
    secrets: [{ name: 'password', keyVaultUrl: passwordSecret.properties.secretUri }]
    env: [
      // The full name: nginx's resolver doesn't use the search domains that
      // make plain "engine" work for the other apps.
      { name: 'ENGINE_URL', value: 'http://${engine.outputs.fqdn}' }
      { name: 'MARKETS_URL', value: 'http://${markets.outputs.fqdn}' }
      { name: 'DASHBOARD_PASSWORD', secretRef: 'password' }
    ]
    ingress: 'external'
    targetPort: 8080
    readyPath: '/healthz'
  }
}

module webhook 'app.bicep' = if (empty(alertWebhooks)) {
  name: 'app-webhook'
  params: {
    location: location
    tags: tags
    environmentId: environment.id
    identityId: identity.id
    registryServer: registryServer
    name: 'webhook'
    image: format(image, 'webhook')
    ingress: 'internal'
    targetPort: 9000
    readyPath: '/alerts'
  }
}

module notifier 'app.bicep' = {
  name: 'app-notifier'
  params: {
    location: location
    tags: tags
    environmentId: environment.id
    identityId: identity.id
    registryServer: registryServer
    name: 'notifier'
    image: format(image, 'notifier')
    secrets: concat(
      [kafkaSecret],
      empty(alertWebhooks) ? [] : [{ name: 'webhooks', keyVaultUrl: webhookSecret!.properties.secretUri }]
    )
    env: concat(json, kafka, [
      { name: 'KAFKA_SESSION_TIMEOUT_MS', value: '30000' }
      empty(alertWebhooks)
        ? { name: 'NOTIFIER_WEBHOOKS', value: 'http://webhook' }
        : { name: 'NOTIFIER_WEBHOOKS', secretRef: 'webhooks' }
    ])
  }
}

output dashboardUrl string = 'https://${dashboard.outputs.fqdn}'
output eventHubsNamespace string = eventHubs.outputs.namespaceName
