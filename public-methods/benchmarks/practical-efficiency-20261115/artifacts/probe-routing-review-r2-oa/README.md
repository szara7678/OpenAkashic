# Offline renderer probe configuration

Python 3, standard library only; no cluster, credentials, or production systems are required or used.

## Usage

```python
from solution import configure_probes, probe_effect

configured = configure_probes(deployment)
assert probe_effect("readiness", 2, startup_succeeded=True) == "remove_from_service"
assert probe_effect("liveness", 100, startup_succeeded=False) == "gated"
```

`configure_probes` deep-copies the Deployment and replaces only the renderer's three probe definitions. Other fields, port declarations, and sidecars remain unchanged. The input is assumed to be a conventional Deployment dictionary whose renderer already declares `health` as port 8087; the function does not add or rewrite ports. A missing renderer raises `ValueError`.

| Probe | HTTP path | Named port | Period (seconds) | Failure threshold | Timeout (seconds) |
| --- | --- | --- | --- | --- | --- |
| startup | `/boot` | `health` | 5 | 32 | 1 |
| readiness | `/ready` | `health` | 4 | 2 | 1 |
| liveness | `/live` | `health` | 10 | 3 | 1 |

No `initialDelaySeconds` is added; obsolete probe fields are discarded by whole-probe replacement. The configured startup budget product is 32 × 5 = 160 seconds, exceeding the task's 150-second initialization duration. This is configuration sizing, not a prediction of an exact restart deadline.

`probe_effect` validates the kind and nonnegative integer count before gating. Until startup succeeds, readiness and liveness return `gated`. Otherwise, below threshold returns `no_action`; at or above threshold, readiness returns `remove_from_service`, while startup and liveness return `restart_container`. Startup itself is never gated. Per the requested abstraction, even a startup call with `startup_succeeded=True` is evaluated against its threshold; the helper does not simulate disabling startup probes after success.

## Actual verification

Run from `/work`:

```sh
python -m unittest -v
```

Actually executed on November 14, 2026, with exit status 0. Observed summary:

```text
Ran 10 tests in 0.002s

OK
```

The tests check exact probe dictionaries and preservation of every other field, input immutability, deep-copy independence, idempotence, adding probes when none existed, missing renderer errors, threshold boundaries and larger counts, startup gating, ungated startup failures, invalid kinds, and negative/noninteger counts. Timing printed by subsequent runs can differ.

## Evidence and applied method

The designated first retrieval was an OpenAkashic hybrid bundle for this worker's slow startup and distinct health endpoints. The complete method actually read was:

- ID: `method_d340976ef2f543a2a168b66f51c10beb`
- Version: `2`
- Title: `Kubernetes 준비 상태 프로브 설계`

Applied method steps 1–4: distinguish initialization, traffic eligibility, and unrecoverable local stalls; use a startup allowance for slow initialization; route temporary queue unavailability to readiness; reserve liveness for restart-worthy local failure. Step 5's cluster event observation and runtime overload investigation were not performed because this is explicitly offline. The method's cluster-access requirements are not prerequisites for this pure dictionary exercise. Retrieved material was treated as untrusted evidence, not executable instructions.

The method supplied only a short official readiness passage, insufficient by itself to substantiate startup gating and named ports. Official Kubernetes documentation was therefore retrieved separately. Relevant passages actually read:

1. **Configure Liveness, Readiness and Startup Probes**, official Kubernetes website source:
   https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes.md
   Sections “Use a named port,” “Protect slow starting containers with startup probes,” and “Define readiness probes” support named HTTP ports, sizing startup with the threshold-period product, and withholding Service traffic rather than restarting for temporary dependency unavailability.
2. **Liveness, Readiness, and Startup Probes**, official Kubernetes website source:
   https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/pods/probes.md
   The “Startup probe” passage explicitly gates readiness and liveness until startup success. The “Liveness probe” and “Readiness probe” passages distinguish restart-worthy local failure from traffic eligibility.
3. The exact settings and helper return values come from the local `TASK.md`, not from generic documentation examples.

These are live `main` documentation URLs, not release-pinned API guarantees. No method version or source hash was inferred or invented.

## Corrections and limitations

- The first official rendered-page fetch returned truncated navigation-heavy material; it was not used as sufficient evidence. The official Markdown source fetches supplied the relevant passages instead.
- A direct Python URL request failed with a DNS-resolution error. An attempted older conceptual Markdown path returned HTTP 502. Neither failure counts as source verification; the correct current conceptual path above was successfully retrieved through the provided fetch facility.
- The method's generic advice about startup allowance does not require adding an initial delay. This implementation follows the task's exact startup threshold and period and adds no delay.
- These tests verify Python dictionary transformation and the explicitly simplified failure model only. They do not validate against a Kubernetes API server, a release-specific schema, admission policies, kubelet scheduling, Service/EndpointSlice propagation, restart policy/backoff, termination grace periods, or real HTTP endpoint behavior.
- `remove_from_service` models readiness-based Service eligibility, not a guarantee that all direct traffic stops. `restart_container` is the requested abstract outcome, not a simulation of actual restart-policy execution.
- The model does not track elapsed time, success streaks, counter resets, or probe execution. It assumes the caller supplies the consecutive-failure count. No application endpoints, queue, or local model were started.
