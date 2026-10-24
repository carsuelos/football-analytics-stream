SHELL := /bin/bash

SCHEMA_DIR := schema/jsonschema
SCHEMAS := $(sort $(wildcard $(SCHEMA_DIR)/*.schema.json))

GO_GEN := simulator/internal/schema/schema_gen.go notifier/internal/schema/schema_gen.go markets/internal/schema/schema_gen.go
GO_MODULES := simulator notifier markets
# CI passes --no-build to smoke-compose: it builds the images beforehand.
COMPOSE_BUILD ?= --build
PY_GEN := engine/src/engine/schema
TS_GEN := dashboard/src/schema
GENERATED := $(GO_GEN) $(PY_GEN) $(TS_GEN)

.DEFAULT_GOAL := help
.PHONY: help setup gen gen-go gen-py gen-ts check-gen lint test fmt ci fetch-data fetch-training sim engine dashboard smoke export backtest evaluate xt dataset train export-model rules webhook markets up down logs smoke-compose cloud-up cloud-down cloud-status lint-infra

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies for all components
	for m in $(GO_MODULES); do (cd $$m && go mod download) || exit 1; done
	cd engine && uv sync
	cd model && uv sync
	cd dashboard && pnpm install --frozen-lockfile

gen: gen-go gen-py gen-ts ## Generate Go, Python and TS types from the JSON Schemas

gen-go:
	cd simulator && go tool go-jsonschema --package schema --struct-name-from-title --tags json \
		--capitalization ID --capitalization XG \
		--output internal/schema/schema_gen.go $(addprefix ../,$(SCHEMAS))
	cd notifier && go tool go-jsonschema --package schema --struct-name-from-title --tags json \
		--capitalization ID --capitalization XG \
		--output internal/schema/schema_gen.go ../$(SCHEMA_DIR)/alert.schema.json ../$(SCHEMA_DIR)/common.schema.json
	cd markets && go tool go-jsonschema --package schema --struct-name-from-title --tags json \
		--capitalization ID \
		--output internal/schema/schema_gen.go ../$(SCHEMA_DIR)/market_board.schema.json \
		../$(SCHEMA_DIR)/price_history.schema.json ../$(SCHEMA_DIR)/common.schema.json

gen-py:
	rm -rf $(PY_GEN)
	cd engine && uv run datamodel-codegen --input ../$(SCHEMA_DIR) --input-file-type jsonschema \
		--output src/engine/schema --output-model-type pydantic_v2.BaseModel \
		--target-python-version 3.13 --disable-timestamp --use-standard-collections \
		--use-union-operator --use-schema-description --use-title-as-name --use-annotated \
		--field-constraints --collapse-root-models --formatters ruff-format
	rm -rf $(PY_GEN)/.ruff_cache

gen-ts:
	rm -rf $(TS_GEN)
	cd dashboard && pnpm exec json2ts --input '../$(SCHEMA_DIR)/*.schema.json' --output src/schema \
		--cwd ../$(SCHEMA_DIR) --no-additionalProperties \
		--bannerComment '// Generated from schema/jsonschema by json-schema-to-typescript. Do not edit; run make gen.'

check-gen: gen ## Fail if generated code differs from what is committed
	@if [ -n "$$(git status --porcelain -- $(GENERATED))" ]; then \
		git status --short -- $(GENERATED); \
		echo "Generated code is out of date. Run 'make gen' and commit the result."; \
		exit 1; \
	fi

lint: ## Lint and type-check all components
	@unformatted=$$(gofmt -l $(GO_MODULES)) && if [ -n "$$unformatted" ]; then echo "gofmt needed:"; echo "$$unformatted"; exit 1; fi
	for m in $(GO_MODULES); do (cd $$m && go vet ./...) || exit 1; done
	cd engine && uv run ruff check . ../scripts && uv run ruff format --check . ../scripts && uv run mypy
	cd model && uv run ruff check . && uv run ruff format --check . && uv run mypy
	cd dashboard && pnpm lint && pnpm typecheck

test: ## Run all tests (including schema contract tests)
	for m in $(GO_MODULES); do (cd $$m && go test ./...) || exit 1; done
	cd engine && uv run pytest
	cd model && uv run pytest
	cd dashboard && pnpm test

fmt: ## Auto-format Go and Python code
	gofmt -w $(GO_MODULES)
	cd engine && uv run ruff check --fix . ../scripts && uv run ruff format . ../scripts
	cd model && uv run ruff check --fix . && uv run ruff format .

ci: check-gen lint test ## Run what CI runs, except the Compose smoke test (make smoke-compose)

fetch-data: ## Download StatsBomb open data (default: 2022 FIFA World Cup) and the xT grid. Extra StatsBomb flags via ARGS="..."
	uv run scripts/fetch_statsbomb.py $(ARGS)
	uv run scripts/fetch_xt_grid.py

fetch-training: ## Download the model's training data (every men's senior season since 2003 except the 2022 World Cup; about 10 GB with the export) into data/training, and export it
	uv run scripts/fetch_statsbomb.py --training --workers 16 $(ARGS)
	cd simulator && go run ./cmd/export -data ../data/training/statsbomb -out ../data/training/feeds

sim: ## Run the simulator on :8080. Pass flags via ARGS="..." (e.g. ARGS="-jitter 3s")
	cd simulator && go run ./cmd/simulator -data ../data/statsbomb $(ARGS)

engine: ## Run the engine against the simulator and serve its API on :8000. Pass flags via ARGS="..." (see ARGS="--help")
	cd engine && uv run engine $(ARGS)

smoke: ## Replay the 2022 final through the simulator and engine, and check the metrics and alerts. Flags via ARGS="..." (see ARGS="--help")
	uv run scripts/smoke_test.py $(ARGS)

export: ## Write every downloaded match as the simulator broadcasts it to data/feeds, for offline replay. Flags via ARGS="..." (see ARGS="--help")
	cd simulator && go run ./cmd/export -data ../data/statsbomb -out ../data/feeds $(ARGS)

backtest: export ## Replay every exported match through the engine offline: one line per match with the score and alerts
	cd engine && uv run python -m engine.backtest ../data/feeds $(ARGS)

evaluate: export ## Replay the 2022 World Cup offline and measure whether the alerts predict goals (lift over chance). Flags via ARGS="..." (see ARGS="--help")
	cd engine && uv run python ../scripts/evaluate_alerts.py $(ARGS)

xt: export ## Compute our own xT grid from the training data (make fetch-training), compare it with the published grid on the World Cup, and write model/artifacts/
	cd model && uv run python -m model.xt $(ARGS)

dataset: export ## Build the goal model's features and labels from the training (make fetch-training) and World Cup feeds into data/model/
	cd model && uv run python -m model.dataset $(ARGS)

train: ## Train and compare the goal models on data/model/ (make dataset), scoring them on the World Cup; writes data/model/results.json. Flags via ARGS="..." (e.g. --horizon 5)
	cd model && uv run python -m model.train $(ARGS)

export-model: ## Fit the shipped goal model on all of data/model/train.npz and write it into the engine (engine/src/engine/detectors/goal_model.json), checking the engine computes what scikit-learn fitted
	cd model && uv run python -m model.export $(ARGS)

rules: export ## Retune the rules (momentum, goal threat, control shift) on the training data, scoring them on the World Cup; prints the engine's new defaults and writes data/model/rules.json
	cd model && uv run python -m model.rules $(ARGS)

dashboard: ## Run the dashboard dev server on :5173, proxying /api to the engine (ENGINE_URL, default http://localhost:8000)
	cd dashboard && pnpm dev $(ARGS)

markets: ## Run the markets service on :8090: the prediction markets' prices for the dashboard's Markets page (make dashboard proxies /api/markets to it)
	cd markets && go run ./cmd/markets $(ARGS)

webhook: ## Run a webhook receiver on :9000 that prints the alerts it gets (for ARGS="--webhook http://localhost:9000")
	uv run scripts/webhook_echo.py $(ARGS)

up: ## Build and start the whole stack in Docker; the dashboard is on http://localhost:3000
	docker compose up -d --build --wait

down: ## Stop the Docker stack
	docker compose down

logs: ## Follow the Docker stack's logs
	docker compose logs -f

smoke-compose: ## Start the Docker stack with events up to 3s late and run the smoke test against it, notifier included. Flags via ARGS="..."
	SIM_JITTER=3s docker compose up -d $(COMPOSE_BUILD) --wait
	uv run scripts/smoke_test.py --external http://localhost:$${DASHBOARD_PORT:-3000} \
		--webhook http://localhost:$${WEBHOOK_PORT:-9000} $(ARGS)

# Azure (docs/AZURE.md). The deploy runs in GitHub Actions, signed in with OIDC:
# these only start it (with gh) and follow it.
cloud-up: ## Deploy the stack to Azure from main (about 5 minutes; about $0.15/hour while up), then print its URL
	gh workflow run deploy.yml --ref main -f action=up
	@sleep 5; gh run watch --exit-status "$$(gh run list --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')"
	@$(MAKE) --no-print-directory cloud-status

cloud-down: ## Take the Azure stack down (the apps and Event Hubs; the rest stays, for next time)
	gh workflow run deploy.yml --ref main -f action=down
	@sleep 5; gh run watch --exit-status "$$(gh run list --workflow deploy.yml --limit 1 --json databaseId --jq '.[0].databaseId')"

cloud-status: ## Whether the Azure stack is up, and its URL
	@gh run list --workflow deploy.yml --limit 3
	@url="$$(az containerapp show -g rg-football-analytics -n dashboard --query properties.configuration.ingress.fqdn -o tsv 2>/dev/null)"; \
		if [ -n "$$url" ]; then echo "Up: https://$$url (user viewer, the DASHBOARD_PASSWORD secret)"; else echo "Down."; fi

lint-infra: ## Build and lint the Bicep
	az bicep lint --file infra/main.bicep
	az bicep lint --file infra/bootstrap/main.bicep
	az bicep lint --file infra/bootstrap/identity.bicep
