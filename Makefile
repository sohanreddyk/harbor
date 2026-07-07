# Harbor — Makefile
# Docker-first local development. `make up` then `make ingest` then `make fe`.

.PHONY: help up down logs ps ingest fe gateway-test health stats fmt clean rebuild

help:
	@echo "Harbor targets:"
	@echo "  make up          - start postgres, redis, gateway, refapp (detached)"
	@echo "  make down        - stop all services"
	@echo "  make logs        - tail all service logs"
	@echo "  make ingest      - embed the starter corpus into pgvector"
	@echo "  make stats       - show corpus document/chunk counts"
	@echo "  make health      - hit gateway + refapp health endpoints"
	@echo "  make gateway-test- send a raw streaming request to the gateway"
	@echo "  make fe          - run the React frontend dev server (host)"
	@echo "  make rebuild     - rebuild images without cache"
	@echo "  make clean       - stop and remove volumes (wipes DB + models)"

up:
	@cp -n .env.example .env 2>/dev/null || true
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

ps:
	docker compose ps

ingest:
	docker compose exec refapp python scripts/ingest.py

stats:
	@curl -s localhost:8000/api/corpus/stats | (python3 -m json.tool 2>/dev/null || cat)

health:
	@echo "gateway:" && curl -s localhost:8080/healthz && echo "" \
	  && echo "refapp:" && curl -s localhost:8000/api/health && echo ""

gateway-test:
	curl -N -s localhost:8080/v1/chat/completions \
	  -H 'Content-Type: application/json' \
	  -d '{"model":"mock","stream":true,"messages":[{"role":"user","content":"Context: A Pod is the smallest deployable unit in Kubernetes. Question: what is a pod?"}]}'

fe:
	cd frontend && npm install && npm run dev

rebuild:
	docker compose build --no-cache

clean:
	docker compose down -v
