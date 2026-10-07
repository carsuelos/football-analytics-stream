SHELL := /bin/bash

SCHEMA_DIR := schema/jsonschema
SCHEMAS := $(sort $(wildcard $(SCHEMA_DIR)/*.schema.json))

GO_GEN := simulator/internal/schema/schema_gen.go
PY_GEN := engine/src/engine/schema
TS_GEN := dashboard/src/schema
GENERATED := $(GO_GEN) $(PY_GEN) $(TS_GEN)

.DEFAULT_GOAL := help
.PHONY: help setup gen gen-go gen-py gen-ts check-gen lint test fmt ci fetch-data sim

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install dependencies for all components
	cd simulator && go mod download
	cd engine && uv sync
	cd dashboard && pnpm install --frozen-lockfile

gen: gen-go gen-py gen-ts ## Generate Go, Python and TS types from the JSON Schemas

gen-go:
	cd simulator && go tool go-jsonschema --package schema --struct-name-from-title --tags json \
		--capitalization ID --capitalization XG \
		--output internal/schema/schema_gen.go $(addprefix ../,$(SCHEMAS))

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
	cd simulator && unformatted=$$(gofmt -l .) && if [ -n "$$unformatted" ]; then echo "gofmt needed:"; echo "$$unformatted"; exit 1; fi
	cd simulator && go vet ./...
	cd engine && uv run ruff check . ../scripts && uv run ruff format --check . ../scripts && uv run mypy
	cd dashboard && pnpm lint && pnpm typecheck

test: ## Run all tests (including schema contract tests)
	cd simulator && go test ./...
	cd engine && uv run pytest
	cd dashboard && pnpm test

fmt: ## Auto-format Go and Python code
	cd simulator && gofmt -w .
	cd engine && uv run ruff check --fix . ../scripts && uv run ruff format . ../scripts

ci: check-gen lint test ## Run everything CI runs

fetch-data: ## Download StatsBomb open data (default: 2022 FIFA World Cup). Pass extra flags via ARGS="..."
	uv run scripts/fetch_statsbomb.py $(ARGS)

sim: ## Run the simulator on :8080. Pass flags via ARGS="..." (e.g. ARGS="-jitter 3s")
	cd simulator && go run ./cmd/simulator -data ../data/statsbomb $(ARGS)
