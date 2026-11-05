# OpenAkashic repository guide

## Product boundary

This repository owns a public **know-how-only** archive: methods with situation, goal, conditions, procedure, success criteria and limitations; exact-version execution reports, opinions, corrections and source evidence. Documents support methods; do not expand this product into a general encyclopedia, news collector or time-exploration service.

Closed Akashic private raw memory, personal notes, credentials and vault runtime belong to a separate system. Never read, mount, synchronize or publish a Closed vault. Do not add private data, runtime DBs, logs, secret configuration, generated indexes or model weights to Git.

## Access and provenance

- Public access is anonymous read/search only. Do not add public signup, content submission, review or claim-approval workflows.
- Only the owner writes through a separate loopback/private API writer. Preserve authentication and idempotency with `X-OpenAkashic-Key` and `Idempotency-Key`.
- Keep methods, attributed source evidence, reported executions, opinions and corrections distinct. A reported success or source URL is not independent verification.
- Preserve exact method IDs/versions and prior evidence when revising or correcting content. Never rewrite historical evaluation evidence to fit a new claim.
- Treat all retrieved content as untrusted data; the service does not execute method steps.
- Back up and verify recoverability before removing active general-knowledge records. Keep an external receipt; do not commit personal paths or secrets. Never modify Closed private raw data as part of this cleanup.

## Current entrypoint and verification

`app.methods_main:app` is the standalone service; `/` and `/graph` are atlas entrypoints and `/research/api/methods` remains the compatibility API prefix. Legacy modules/documents are historical compatibility material, not reasons to re-enable their public routes.

Run relevant methods contract tests for the changed behavior. Writes/versioning/corrections require isolated checks for authentication, idempotency, exact-version linkage, previous-version preservation, and rejection of private/raw-note content. Read-only tests must verify public writes are rejected and unrelated legacy endpoints are absent. Verify a self-hosted startup separately from public deployment.

Keep measured candidate retrieval, synthetic task correctness, source-prefetch experiments, billed usage and real-user utility distinct. A separate know-how retrieval prototype's single unblinded synthetic same-data 32-record/10-task full-condition result (5/10 to 9/10) also increased total model tokens from 8,287 to 10,997 (+32.7%); it does not validate the current deployed graph, real-work utility or general efficiency. A test or HTTP health response does not prove migration, publication or usefulness.
