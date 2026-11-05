# OpenAkashic MCP status

The current OpenAkashic product is a **know-how-only HTTP/OpenAPI service**. Use [the agent guide](../llms-install.md) and [method API contract](../docs/public-methods.md). Public readers need no token or account. The standalone application does not expose a public MCP memory server.

The existing MCP package metadata, installers and registry recipes belong to an earlier capsule/memory integration. They are retained as historical compatibility material, not a supported installation path for this service. Do not run the old provisioning/signup flow or assume registry availability means the current hosted service supports it. No public contribution, review, claim-approval or private-vault access is provided.

For a self-hosted know-how instance, run `app.methods_main:app` as described in [the operations guide](../docs/knowhow-operations.md). Owner writes use the separate private writer's `X-OpenAkashic-Key` and `Idempotency-Key`; a legacy bearer token is not that contract.

[The archived installation document](../docs/legacy-agent-install.md) preserves prior behavior and benchmark context. Its commands and tool lists are historical, not current recommendations. Closed Akashic private memory remains a separate system.
