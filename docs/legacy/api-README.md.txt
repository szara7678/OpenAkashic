# OpenAkashic Core Server

OpenAkashic v1 core is a FastAPI + Postgres service for storing and retrieving claims, evidences, mentions, optional entities, claim links, and precomputed capsules.

## Running

```bash
cd /external/legacy-deployment
docker compose up -d --build
```

## Public URLs

```text
https://openakashic.com
https://api.openakashic.com
```

Smoke test:

```bash
cd /external/legacy-deployment
BASE_URL=https://api.openakashic.com ./scripts/smoke_test.sh
```

Closed Akashic is a separate service under:

```text
/external/legacy-deployment
```

## Main API

```text
GET  /health
POST /query
POST /claims
GET  /claims/{id}
PATCH /claims/{id}/status
POST /evidences
GET  /evidences/{id}
POST /capsules
GET  /capsules/{id}
GET  /mentions/search?q=
POST /entities
GET  /entities/search?q=
POST /mcp
```

Mutation endpoints require:

```text
X-OpenAkashic-Key: value from /external/legacy-deployment
```
