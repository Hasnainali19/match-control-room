# Submission listing

**Name:** Match Control Room
**Tagline:** Statistical Process Control meets the TV gallery: AI agents that spot momentum swings, explain *why* with a live 5 Whys, and put only fact-checked punditry on air.

## Elevator pitch (≈100 words)
Football commentary tells you *what* happened. Match Control Room tells you *when the game is turning, and why*. I borrowed the tool automotive plants use to catch a drifting production line: SPC control charts with Western Electric run rules. A team of 13 AI agents applies it to live match events. When charts go out of control, a Root-Cause agent runs a Lean 5 Whys, for example: *"Rovers' left back's sprint speed is down 29%. Substitute or double up that flank."* Four pundits debate it, a Referee agent fact-checks every number before it reaches air, and a Producer agent personalises the broadcast for analysts or casual fans, in their language.

## Microsoft / Azure tech used
- **GitHub Models (Azure-hosted OpenAI models, e.g. `openai/gpt-4o-mini`).** No-subscription provider with a rate-limit-aware client: cache, request budget, 429 backoff and template fallback. *GitHub has announced the service is retired; the provider stays configurable for any OpenAI-compatible endpoint.*
- **GitHub Copilot.** Used throughout development.
- **Azure OpenAI in Azure AI Foundry.** Pundit takes (JSON mode with structured claims), narration in any language, root-cause translation. All calls go through one gateway with a timeout and circuit breaker.
- **Microsoft Entra ID managed identity.** Keyless access from the app to Azure OpenAI.
- **Azure Container Apps + Azure Container Registry.** Serverless, autoscaling SSE backend built with `az acr build`.
- **Azure Monitor / Application Insights (OpenTelemetry).** A trace span for every agent call, plus structured logs.
- **Microsoft Agent Framework–ready design.** Agents, workflow edges, shared state and retry middleware map one-to-one (documented in the README).

## Highlights for judges
- **Distinct agents:** 13 agents with distinct roles on a shared blackboard, with event-driven handoffs and a fact-checker that guards the generative agents.
- **Chaos-proof:** chaos mode injects a 30% failure rate. Retries, fallbacks and deferred replay keep the score, charts and signals *identical* to a clean run (tested).
- **Validated against hidden ground truth:** validation across 60 matches. The team with momentum scores **1.5×** more often in the 10 minutes after a swing signal. The Root-Cause agent finds the actual fatigued player from evidence alone.
- **Runs anywhere:** fully runnable offline with deterministic templates. Azure OpenAI upgrades it to any language and free-form punditry.
- **Synthetic data only:** fictional clubs and players.
