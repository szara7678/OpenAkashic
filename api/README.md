# OpenAkashic — Core API

FastAPI + PostgreSQL service that stores and retrieves **claims, evidences, mentions, entities, claim links, and precomputed capsules** — the durable, verified layer of the OpenAkashic knowledge network.

> For the notes/vault/agent side, see [`../closed-web/`](../closed-web/).

## Quick start

```bash
cp .env.example .env
# edit .env to set POSTGRES_PASSWORD and OPENAKASHIC_WRITE_API_KEY
docker compose up -d --build
```

The API listens on port `8000` by default. Health check:

```bash
curl http://localhost:8000/health
```

## Main endpoints

```text
GET   /health
POST  /query
POST  /claims               (write — requires X-OpenAkashic-Key)
GET   /claims/{id}
PATCH /claims/{id}/status   (write)
POST  /evidences            (write)
GET   /evidences/{id}
POST  /capsules             (write)
GET   /capsules/{id}
GET   /mentions/search?q=
POST  /entities             (write)
GET   /entities/search?q=
POST  /mcp
```

Mutation endpoints require the write key set in `OPENAKASHIC_WRITE_API_KEY`:

```text
X-OpenAkashic-Key: <value from .env>
```

## Schema

See [`db/`](./db/) for the Postgres schema. The main tables:

- **claims** — atomic factual statements with status (`draft`, `verified`, `retracted`).
- **evidences** — sources that back or refute a claim.
- **capsules** — precomputed answer bundles (claim + evidences + summary).
- **entities** — optional named entities linked to claims.
- **mentions** — surface forms pointing to entities.

## Smoke test

```bash
BASE_URL=http://localhost:8000 ./scripts/smoke_test.sh
```

## Related services

- **[Closed Web](../closed-web/)** — agent-facing knowledge vault + MCP server.
- **Public site** — served separately (e.g. a static site generator or marketing page).
