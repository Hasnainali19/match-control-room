#!/usr/bin/env bash
# Deploy Match Control Room to Azure Container Apps (build in ACR, no local Docker needed).
# Prereqs: az login; az extension add -n containerapp; an Azure OpenAI (AI Foundry) deployment.
set -euo pipefail
RG=${RG:-mcr-rg}; LOC=${LOC:-eastus2}; ACR=${ACR:-mcracr$RANDOM}; ENV=${ENV:-mcr-env}; APP=${APP:-match-control-room}
AOAI_ENDPOINT=${AZURE_OPENAI_ENDPOINT:?set AZURE_OPENAI_ENDPOINT}; AOAI_DEPLOYMENT=${AZURE_OPENAI_DEPLOYMENT:-gpt-4o-mini}
AOAI_RESOURCE_ID=${AOAI_RESOURCE_ID:-}   # /subscriptions/.../Microsoft.CognitiveServices/accounts/<name> (for keyless auth)

az group create -n "$RG" -l "$LOC" -o none
az acr create -g "$RG" -n "$ACR" --sku Basic -o none
az acr build -r "$ACR" -t mcr:latest .
az monitor log-analytics workspace create -g "$RG" -n mcr-logs -o none
az monitor app-insights component create -g "$RG" -a mcr-ai -l "$LOC" --workspace mcr-logs -o none
AI_CONN=$(az monitor app-insights component show -g "$RG" -a mcr-ai --query connectionString -o tsv)
az containerapp env create -g "$RG" -n "$ENV" -l "$LOC" -o none
az containerapp create -g "$RG" -n "$APP" --environment "$ENV" \
  --image "$ACR.azurecr.io/mcr:latest" --registry-server "$ACR.azurecr.io" --registry-identity system \
  --system-assigned --ingress external --target-port 8000 \
  --min-replicas 1 --max-replicas 5 --cpu 0.5 --memory 1Gi \
  --scale-rule-name http --scale-rule-type http --scale-rule-http-concurrency 50 \
  --env-vars AZURE_OPENAI_ENDPOINT="$AOAI_ENDPOINT" AZURE_OPENAI_DEPLOYMENT="$AOAI_DEPLOYMENT" \
             AZURE_OPENAI_USE_MANAGED_IDENTITY=1 APPLICATIONINSIGHTS_CONNECTION_STRING="$AI_CONN" -o none
if [ -n "$AOAI_RESOURCE_ID" ]; then
  PID=$(az containerapp show -g "$RG" -n "$APP" --query identity.principalId -o tsv)
  az role assignment create --assignee "$PID" --role "Cognitive Services OpenAI User" --scope "$AOAI_RESOURCE_ID" -o none
fi
echo "https://$(az containerapp show -g "$RG" -n "$APP" --query properties.configuration.ingress.fqdn -o tsv)"
