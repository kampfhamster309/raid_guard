# raid_guard — build, push, deploy
#
# Required env vars for push/deploy:
#   UNRAID_HOST   IP or hostname of the Unraid server (e.g. 192.168.1.10)
#
# Optional env vars:
#   TAG           Image tag to build/push (default: latest)

REGISTRY  := $(UNRAID_HOST):5000
PROJECT   := raid_guard
TAG       ?= latest

SERVICES  := backend frontend capture-agent

.PHONY: build push build-push deploy test-suricata test-db test-redis test-ingestor help

build:
	@for svc in $(SERVICES); do \
		echo "==> Building $$svc..."; \
		docker build -t $(REGISTRY)/$(PROJECT)/$$svc:$(TAG) services/$$svc || exit 1; \
	done

push:
	@test -n "$(UNRAID_HOST)" || (echo "ERROR: UNRAID_HOST is not set" && exit 1)
	@for svc in $(SERVICES); do \
		echo "==> Pushing $$svc..."; \
		docker push $(REGISTRY)/$(PROJECT)/$$svc:$(TAG) || exit 1; \
	done

build-push: build push

deploy:
	@test -n "$(UNRAID_HOST)" || (echo "ERROR: UNRAID_HOST is not set" && exit 1)
	docker compose pull
	docker compose up -d

test-suricata:
	@echo "==> Running Suricata config validation test..."
	@bash services/suricata/tests/test_config.sh
	@echo "==> Running Suricata entrypoint unit tests..."
	@bash services/suricata/tests/test_entrypoint.sh

test-db:
	@echo "==> Running database schema integration tests..."
	@bash services/db/tests/test_schema.sh

test-redis:
	@echo "==> Running Redis pub/sub integration tests..."
	@bash services/backend/tests/test_channels.sh

test-ingestor:
	@echo "==> Running ingestor unit tests..."
	@cd services/backend && .venv/bin/python -m pytest tests/test_ingestor.py -v
	@echo "==> Running ingestor integration tests..."
	@bash services/backend/tests/test_ingestor_integration.sh

help:
	@echo "Targets:"
	@echo "  build          Build all service images"
	@echo "  push           Push images to the Unraid registry (requires UNRAID_HOST)"
	@echo "  build-push     Build then push"
	@echo "  deploy         Pull latest images and restart all services (requires UNRAID_HOST)"
	@echo "  test-suricata  Build suricata image and validate config + entrypoint logic"
	@echo "  test-db        Spin up a temporary TimescaleDB container and validate the schema"
	@echo "  test-redis     Spin up a temporary Redis container and validate pub/sub channels"
	@echo "  test-ingestor  Unit + integration tests for the EVE JSON ingestor"
