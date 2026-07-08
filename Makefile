# Harbor — Makefile
# Docker-first local development. `make up` then `make ingest` then `make fe`.

.PHONY: help up down logs ps ingest bench cache-stats reset-cache providers fe gateway-test health stats fmt clean rebuild

help:
	@echo "Harbor targets:"
	@echo "  make up          - start postgres, redis, gateway, refapp (detached)"
	@echo "  make down        - stop all services"
	@echo "  make logs        - tail all service logs"
	@echo "  make ingest      - embed the starter corpus into pgvector"
	@echo "  make bench       - run the Zipf workload generator against the gateway"
	@echo "  make cache-stats - show gateway semantic cache stats"
	@echo "  make reset-cache - flush Redis + restart gateway (cold cache for a clean bench)"
	@echo "  make providers   - show provider fallback chain + circuit-breaker state"
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

bench:
	docker compose exec refapp python bench/zipf_load.py --n 400 --concurrency 16 --zipf-s 1.2

cache-stats:
	@curl -s localhost:8080/v1/cache/stats | (python3 -m json.tool 2>/dev/null || cat)

reset-cache:
	docker compose exec redis redis-cli FLUSHALL
	docker compose restart gateway
	@echo "waiting for gateway..." && sleep 3 && curl -s localhost:8080/healthz && echo ""

providers:
	@curl -s localhost:8080/v1/providers | (python3 -m json.tool 2>/dev/null || cat)

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
