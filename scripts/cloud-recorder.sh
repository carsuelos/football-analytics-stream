#!/bin/bash
# The price recorder in Azure (infra/recorder.bicep): schedule it, download
# what it recorded, or remove it. Needs `az login` and the base stage deployed.
#
#   scripts/cloud-recorder.sh schedule "2026-10-25 06:00" 11   # local time (America/Los_Angeles), hours
#   scripts/cloud-recorder.sh tapes                            # its tapes into data/markets
#   scripts/cloud-recorder.sh status                           # the job's schedule and runs
#   scripts/cloud-recorder.sh off                              # remove the job (the share and its tapes stay)
set -euo pipefail

RG=${RG:-rg-football-analytics}
TZ_LOCAL=${TZ_LOCAL:-America/Los_Angeles}
JOB=job-markets-recorder
REPO=$(cd "$(dirname "$0")/.." && pwd)

one() { az resource list -g "$RG" --resource-type "$1" --query "[0].name" -o tsv; }

case "${1:-}" in
schedule)
  start=${2:?when to start, e.g. "2026-10-25 06:00" ($TZ_LOCAL)}
  hours=${3:?how many hours}
  # The cron runs in UTC: convert the local start (daylight saving included).
  epoch=$(TZ=$TZ_LOCAL date -j -f "%Y-%m-%d %H:%M" "$start" +%s)
  [ "$epoch" -gt "$(date +%s)" ] || { echo "$start ($TZ_LOCAL) is in the past" >&2; exit 1; }
  cron=$(date -u -r "$epoch" "+%-M %-H %-d %-m *")
  acr=$(one Microsoft.ContainerRegistry/registries)
  env=$(one Microsoft.App/managedEnvironments)
  st=$(one Microsoft.Storage/storageAccounts)
  tag=$(git -C "$REPO" rev-parse --short HEAD)$(git -C "$REPO" diff --quiet -- markets || echo -dirty)

  echo "Building markets:$tag in $acr (about 2 minutes)…"
  az acr build -r "$acr" -t "markets:$tag" "$REPO/markets" --no-logs -o none
  echo "Scheduling $JOB: $start $TZ_LOCAL for ${hours}h (cron \"$cron\" UTC)…"
  az deployment group create -g "$RG" -n football-recorder -f "$REPO/infra/recorder.bicep" -o none -p \
    environmentName="$env" storageAccountName="$st" registryServer="$acr.azurecr.io" \
    identityName=id-football-analytics-apps imageTag="$tag" cron="$cron" hours="$hours"
  echo "Scheduled. It records to the 'markets' share; afterwards: make cloud-tapes, then make cloud-record-off."
  ;;
tapes)
  st=$(one Microsoft.Storage/storageAccounts)
  key=$(az storage account keys list -g "$RG" -n "$st" --query "[0].value" -o tsv)
  mkdir -p "$REPO/data/markets"
  az storage file download-batch --account-name "$st" --account-key "$key" -s markets -d "$REPO/data/markets" -o none
  echo "Downloaded into data/markets:"; (cd "$REPO/data/markets" && find . -name '*.jsonl' -exec ls -lh {} \; | awk '{print "  "$5"\t"$9}')
  ;;
status)
  az containerapp job show -g "$RG" -n "$JOB" --query "{cron:properties.configuration.scheduleTriggerConfig.cronExpression, image:properties.template.containers[0].image, args:join(' ', properties.template.containers[0].args)}" -o table
  az containerapp job execution list -g "$RG" -n "$JOB" --query "[].{name:name,status:properties.status,start:properties.startTime,end:properties.endTime}" -o table
  ;;
off)
  az containerapp job delete -g "$RG" -n "$JOB" --yes -o none && echo "Removed $JOB."
  ;;
*)
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
  ;;
esac
