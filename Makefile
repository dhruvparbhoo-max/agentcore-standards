# Developer entry points. Every target that touches containers checks
# `docker ps` first (Finch: DOCKER=finch).
#
#   make local                 compose stack + the pattern's events/*.json
#   make build                 linux/arm64 images for every unit (QEMU on x86)
#   make doctor ENV=dev        read-only preflight before a deploy
#   make deploy ENV=dev        CDK foundation, push images, agentcore deploy, verify
#   make teardown ENV=dev      always safe to run; removes what deploy created
#   make ci                    the pull request checks, same as .github/workflows/ci.yml

PATTERN ?= _template
ENV ?= dev
DOCKER ?= docker
PLATFORM ?= linux/arm64
TAG ?= arm64
AGENT_URL ?= http://localhost:8080

UV := env -u VIRTUAL_ENV uv
KIT := $(UV) run agentcore-kit

.PHONY: prereqs local local-down build doctor deploy teardown ci

prereqs:
	@$(DOCKER) ps >/dev/null || { echo "'$(DOCKER) ps' failed: start Docker Desktop, the Docker daemon, or 'finch vm start'"; exit 1; }

local: prereqs
	$(DOCKER) compose --profile base build base-agent base-lambda
	$(DOCKER) compose up -d --build --wait
	$(KIT) post-events patterns/$(PATTERN) --url $(AGENT_URL)

local-down:
	$(DOCKER) compose down -t 10

build: prereqs
	$(UV) run python scripts/images.py build --platform $(PLATFORM) --tag $(TAG)

doctor:
	$(KIT) doctor patterns/$(PATTERN) --env $(ENV)

deploy: prereqs
	scripts/deploy.sh $(PATTERN) $(ENV)

teardown:
	scripts/teardown.sh $(PATTERN) $(ENV)

ci:
	$(UV) lock --check
	$(UV) sync --all-packages --locked
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	$(UV) run mypy
	$(UV) run pytest -m "not runtime"
	$(UV) run python scripts/check_boundaries.py
	$(KIT) check-kit
	$(KIT) generate --check
	$(KIT) tool-check
