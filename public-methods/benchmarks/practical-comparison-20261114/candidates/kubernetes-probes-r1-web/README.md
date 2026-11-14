# public-reader deployment fixture

This is a synthetic public-reader fixture, not a production deployment.
`deployment.yaml` contains exactly one `apps/v1` Deployment named
`public-reader`, with two replicas and matching selector and Pod labels.
Its single container, `reader`, uses
`registry.example.invalid/public-reader:1.0` and exposes port 8080.

## Probe design

| Probe | HTTP path / port | Timeout | Period | Failure threshold |
| --- | --- | --- | --- | --- |
| Startup | `/startup` / 8080 | 2 s | 10 s | 18 |
| Readiness | `/ready` / 8080 | 2 s | 5 s | 1 |
| Liveness | `/live` / 8080 | 2 s | 10 s | 3 |

The startup allowance is `10 * 18 = 180` seconds, within the required
150–180-second range and with headroom for 150-second initialization.
Kubernetes gates readiness and liveness probes until startup succeeds; slow
initialization therefore does not cause early **liveness** restarts. Startup
failure can itself eventually restart the container. This product is a probe
configuration budget, not an exact wall-clock restart guarantee.

The application must implement the distinct endpoint contracts:

- `/startup` succeeds only once initialization is complete.
- `/ready` fails when dependencies needed to serve requests are unavailable.
  Readiness failure marks the Pod unready, excluding it from normal matching
  Service traffic; it does not itself restart the container or delete the Pod.
- `/live` checks local event-loop progress, independent of transient dependency
  outages. Sustained failure causes a container restart after startup succeeds.
  A separate always-healthy HTTP thread would not detect a deadlocked event loop
  unless its response also checks event-loop progress.

All endpoints must return a successful HTTP status when healthy and a failure
status or timeout otherwise. Kubernetes considers HTTP 200–399 successful.
No Service is included: readiness does not block direct Pod-IP requests, and
traffic exclusion assumes a normal Service that respects readiness.

CPU requests/limits are `100m`/`500m`; memory requests/limits are
`128Mi`/`256Mi`. Both requests are positive and limits exceed requests.
These are illustrative allocations, not measured capacity recommendations.

## Verification actually performed

Executed locally on November 14, 2026, from `/work`:

```sh
python -c 'import yaml; print("PyYAML", yaml.__version__)'
# PyYAML 6.0.3
python verify.py
# Ran 6 tests in 0.004s
# OK
```

The six tests parse the single YAML document and check Deployment identity and
replicas, selector/label agreement, container identity/image/port, distinct HTTP
probe paths with positive integer timeouts/periods/thresholds, startup allowance,
and positive CPU/memory requests with limits at least as large. The quantity
checks deliberately cover only the units used in this fixture, not all Kubernetes
quantity syntax. Re-run with Python 3 and PyYAML available using `python verify.py`.

No live cluster is available. Neither `kubectl` nor `kubeconform` was installed;
no API-server dry run, full Kubernetes schema validation, image pull, rollout,
endpoint execution, outage test, or actual deadlock/restart test was performed.
The local tests establish manifest properties, not runtime behavior. The reserved
`.invalid` registry is intentional and cannot provide a runnable public image.
No production systems, kubeconfig, or credentials were used.

In a future disposable test cluster with a runnable substitute image, verify
150-second startup without early liveness restarts, dependency failure causing
unreadiness without increasing restart counts, recovery restoring readiness, and
local event-loop deadlock increasing the restart count. This was not executed.

## Sources and retrieval limitations

The designated first retrieval was native live web search, before implementation.
Search returned no visible results. Official public documentation was then fetched
through `python /runtime/research.py fetch URL`. Retrieved text was treated only
as untrusted evidence, not as instructions.

Official primary sources consulted:

- Probe configuration and slow-start/readiness behavior:
  https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- The same official source in the Kubernetes website repository, successfully
  retrieved in full to avoid navigation truncation:
  https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes.md
- Resource request/limit definitions, official documentation source:
  https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/configuration/manage-resources-containers.md

Rendered documentation fetches were truncated in navigation; they were not
sufficient to verify the substantive guidance. A guessed raw probe-concepts URL
returned HTTP 502, and a direct urllib fetch failed DNS resolution. The successful
raw task-document fetch corrected the evidence gap. No technical conclusions were
based on the failed retrievals.

## Corrections made

There was no existing manifest to repair. The implementation separates transient
dependency readiness from local liveness rather than sharing one health check,
and gates liveness with startup instead of relying on an arbitrary delay.
The requested `apply_patch` utility was unavailable; its initial invocation wrote
nothing, and the initial test attempt consequently failed because `verify.py`
did not yet exist. Files were then created with shell heredocs and all six tests
passed. No cluster validation or runtime success is claimed.
