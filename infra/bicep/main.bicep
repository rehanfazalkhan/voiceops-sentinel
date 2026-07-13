targetScope = 'resourceGroup'

@description('A globally unique prefix for the VoiceOps resources.')
@minLength(3)
param namePrefix string
param location string = resourceGroup().location
@description('Container image already published to an approved registry.')
param containerImage string
@description('Endpoint of a deployed Azure OpenAI resource with the selected model deployment.')
param azureOpenAiEndpoint string
param azureOpenAiDeployment string
param azureOpenAiModel string
param azureOpenAiApiVersion string
@description('Existing Azure Communication Services endpoint. Phone-number assignment is an operational prerequisite.')
param communicationEndpoint string
@description('Public HTTPS callback URL registered with Azure Communication Services.')
param communicationCallbackUrl string
@description('Public WSS media endpoint registered with Azure Communication Services.')
param mediaWebSocketUrl string
@description('Existing Azure Speech endpoint and its region.')
param speechEndpoint string
param speechRegion string
@description('Entra ID values for the operator API.')
param entraIssuer string
param entraAudience string

var suffix = uniqueString(resourceGroup().id, namePrefix)
var logName = take('${namePrefix}-${suffix}-log', 63)
var environmentName = take('${namePrefix}-${suffix}-env', 32)
var appName = take('${namePrefix}-${suffix}-api', 32)
var cosmosName = take(replace('${namePrefix}${suffix}cosmos', '-', ''), 44)
var searchName = take(replace('${namePrefix}-${suffix}-search', '_', ''), 60)
var vaultName = take(replace('${namePrefix}-${suffix}-kv', '_', ''), 24)

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: listKeys(logAnalytics.id, logAnalytics.apiVersion).primarySharedKey
      }
    }
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: vaultName
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    softDeleteRetentionInDays: 90
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    capabilities: [
      {
        name: 'EnableServerless'
      }
    ]
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource callsDatabase 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: 'voiceops'
  properties: {
    resource: {
      id: 'voiceops'
    }
  }
}

resource callsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: callsDatabase
  name: 'calls'
  properties: {
    resource: {
      id: 'calls'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
        includedPaths: [
          {
            path: '/*'
          }
        ]
        excludedPaths: [
          {
            path: '/"_etag"/?'
          }
        ]
      }
    }
  }
}

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: searchName
  location: location
  sku: {
    name: 'standard'
  }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'enabled'
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: appName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    managedEnvironmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'voiceops'
          image: containerImage
          resources: {
            cpu: 0.5
            memory: '1Gi'
          }
          env: [
            { name: 'VOICEOPS_ENVIRONMENT' value: 'production' }
            { name: 'AZURE_OPENAI_ENDPOINT' value: azureOpenAiEndpoint }
            { name: 'AZURE_OPENAI_DEPLOYMENT' value: azureOpenAiDeployment }
            { name: 'AZURE_OPENAI_MODEL' value: azureOpenAiModel }
            { name: 'AZURE_OPENAI_API_VERSION' value: azureOpenAiApiVersion }
            { name: 'AZURE_AI_SEARCH_ENDPOINT' value: 'https://${search.name}.search.windows.net' }
            { name: 'AZURE_AI_SEARCH_INDEX' value: 'voiceops-knowledge' }
            { name: 'AZURE_AI_SEARCH_SEMANTIC_CONFIG' value: 'default' }
            { name: 'AZURE_COSMOS_ENDPOINT' value: cosmos.properties.documentEndpoint }
            { name: 'AZURE_COSMOS_DATABASE' value: 'voiceops' }
            { name: 'AZURE_COSMOS_CONTAINER' value: 'calls' }
            { name: 'AZURE_COMMUNICATION_ENDPOINT' value: communicationEndpoint }
            { name: 'AZURE_COMMUNICATION_CALLBACK_URL' value: communicationCallbackUrl }
            { name: 'AZURE_MEDIA_WEBSOCKET_URL' value: mediaWebSocketUrl }
            { name: 'AZURE_SPEECH_ENDPOINT' value: speechEndpoint }
            { name: 'AZURE_SPEECH_REGION' value: speechRegion }
            { name: 'ENTRA_ISSUER' value: entraIssuer }
            { name: 'ENTRA_AUDIENCE' value: entraAudience }
          ]
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 10
      }
    }
  }
}

output containerAppUrl string = 'https://${app.properties.configuration.ingress.fqdn}'
output managedIdentityPrincipalId string = app.identity.principalId
output keyVaultUri string = vault.properties.vaultUri
output requiredRoleAssignments array = [
  'Cognitive Services OpenAI User on the Azure OpenAI resource'
  'Search Index Data Reader on the Azure AI Search service'
  'Cosmos DB Built-in Data Contributor using Cosmos SQL data-plane RBAC'
  'Key Vault Secrets User on the Key Vault when external secrets are added'
  'Communication Services permissions required by the selected Call Automation configuration'
]
