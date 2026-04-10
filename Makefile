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

.PHONY: build push build-push deploy help

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

help:
	@echo "Targets:"
	@echo "  build       Build all service images"
	@echo "  push        Push images to the Unraid registry (requires UNRAID_HOST)"
	@echo "  build-push  Build then push"
	@echo "  deploy      Pull latest images and restart all services (requires UNRAID_HOST)"
