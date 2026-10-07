#!/usr/bin/env bash
# One-time, free Azure setup for football-analytics-stream. Safe to re-run.
#
#   1. Resource group + monthly budget alert (main.bicep, subscription-scope deployment)
#   2. Register resource providers used later (Container Apps)
#   3. GitHub OIDC: Entra app + federated credential for the main branch,
#      Contributor on the project resource group only (no client secret)
#   4. GitHub repo variables AZURE_CLIENT_ID / AZURE_TENANT_ID / AZURE_SUBSCRIPTION_ID
#
# Prerequisites: az (logged in, Bicep installed), gh (logged in with repo admin).
# Usage: infra/bootstrap/bootstrap.sh [alert-email]
set -euo pipefail

REPO="carsuelos/football-analytics-stream"
LOCATION="westus2"
RG="rg-football-analytics"
APP_NAME="gh-football-analytics-stream"
ALERT_EMAIL="${1:-$(az account show --query user.name -o tsv)}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\n==> %s\n' "$*"; }

# Fail before changing anything if a prerequisite is missing.
for cmd in az gh; do
  command -v "$cmd" >/dev/null || { echo "Missing '$cmd' on PATH." >&2; exit 1; }
done
az account show --output none 2>/dev/null || { echo "Run 'az login' first." >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "Run 'gh auth login' first." >&2; exit 1; }
az bicep version >/dev/null 2>&1 || { echo "Run 'az bicep install' first." >&2; exit 1; }

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"
log "Subscription: $(az account show --query name -o tsv) ($SUBSCRIPTION_ID)"

log "Deploying resource group '$RG' and budget (alerts to $ALERT_EMAIL)"
az deployment sub create \
  --name football-analytics-bootstrap \
  --location "$LOCATION" \
  --template-file "$HERE/main.bicep" \
  --parameters location="$LOCATION" resourceGroupName="$RG" alertEmails="[\"$ALERT_EMAIL\"]" \
  --only-show-errors --output none
RG_ID="$(az group show --name "$RG" --query id -o tsv)"

log "Registering resource providers"
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry \
  Microsoft.EventHub Microsoft.KeyVault Microsoft.Web; do
  az provider register --namespace "$ns" --only-show-errors --output none
done

log "Entra app '$APP_NAME'"
APP_ID="$(az ad app list --display-name "$APP_NAME" --query '[0].appId' -o tsv)"
if [[ -z "$APP_ID" ]]; then
  APP_ID="$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)"
fi
if ! az ad sp show --id "$APP_ID" --only-show-errors --output none 2>/dev/null; then
  az ad sp create --id "$APP_ID" --only-show-errors --output none
fi
SP_OBJECT_ID="$(az ad sp show --id "$APP_ID" --query id -o tsv)"

log "Federated credential for $REPO main branch"
FIC_NAME="github-main"
# Ask GitHub for the exact subject prefix its OIDC tokens use. With immutable
# subjects it embeds owner/repo IDs (repo:owner@id/name@id), so a renamed or
# re-created repo with the same name cannot match.
SUB_PREFIX="$(gh api "repos/$REPO/actions/oidc/customization/sub" --jq '.sub_claim_prefix // empty' 2>/dev/null || true)"
SUBJECT="${SUB_PREFIX:-repo:$REPO}:ref:refs/heads/main"
FIC_JSON="{
  \"name\": \"$FIC_NAME\",
  \"issuer\": \"https://token.actions.githubusercontent.com\",
  \"subject\": \"$SUBJECT\",
  \"audiences\": [\"api://AzureADTokenExchange\"]
}"
CURRENT_SUBJECT="$(az ad app federated-credential list --id "$APP_ID" --query "[?name=='$FIC_NAME'].subject | [0]" -o tsv)"
if [[ -z "$CURRENT_SUBJECT" ]]; then
  az ad app federated-credential create --id "$APP_ID" --only-show-errors --output none --parameters "$FIC_JSON"
elif [[ "$CURRENT_SUBJECT" != "$SUBJECT" ]]; then
  az ad app federated-credential update --id "$APP_ID" --federated-credential-id "$FIC_NAME" \
    --only-show-errors --output none --parameters "$FIC_JSON"
fi
echo "Subject: $SUBJECT"

log "Contributor on $RG"
if [[ -z "$(az role assignment list --assignee "$SP_OBJECT_ID" --scope "$RG_ID" --role Contributor --query '[0].id' -o tsv)" ]]; then
  # A new service principal can take a few seconds to replicate.
  for attempt in 1 2 3 4 5; do
    if az role assignment create --assignee-object-id "$SP_OBJECT_ID" \
      --assignee-principal-type ServicePrincipal --role Contributor --scope "$RG_ID" \
      --only-show-errors --output none; then
      break
    fi
    [[ $attempt == 5 ]] && exit 1
    sleep 10
  done
fi

log "GitHub repository variables"
gh variable set AZURE_CLIENT_ID --repo "$REPO" --body "$APP_ID"
gh variable set AZURE_TENANT_ID --repo "$REPO" --body "$TENANT_ID"
gh variable set AZURE_SUBSCRIPTION_ID --repo "$REPO" --body "$SUBSCRIPTION_ID"

log "Done"
cat <<EOF
Resource group : $RG ($LOCATION)
Budget         : budget-football-analytics, alerts to $ALERT_EMAIL
OIDC app       : $APP_NAME (client id $APP_ID)
Role           : Contributor on $RG
Verify OIDC    : run the "Azure login check" workflow on main (Actions tab)
EOF
