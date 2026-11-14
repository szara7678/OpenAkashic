# Synthetic public-reader deployment

`deployment.yaml` defines one `apps/v1` Deployment named `public-reader`,
two replicas, matching selector/template labels, and a `reader` container using
`registry.example.invalid/public-reader:1.0` on port 8080. This is a synthetic
fixture, not a production deployment.

## Probe design and endpoint contract

- Startup: HTTP `/startup`, every 10 seconds, timeout 2 seconds, 18 consecutive
  failures allowed. The configured startup budget is `10 * 18 = 180` seconds,
  within the required 150–180 seconds and with headroom for 150-second initialization.
  Kubernetes suppresses readiness and liveness probes until startup succeeds.
  Startup must only succeed after initialization finishes; repeated startup
  failure eventually causes a container restart.
- Readiness: HTTP `/ready`, every 5 seconds, timeout 2 seconds, failure threshold 1.
  This endpoint must fail when dependencies needed to serve traffic are unavailable
  and recover when they return. Readiness failure marks the pod unready and removes
  it from normal matching Service traffic; readiness failure does not restart it.
  It does not delete the pod. No Service is included in this task.
- Liveness: HTTP `/live`, every 10 seconds, timeout 2 seconds, failure threshold 3.
  This endpoint must reflect local event-loop health, not external dependency
  availability. A deadlocked loop must fail or time out this check; repeated
  liveness failures cause a container restart. Temporary dependency outages alone
  must not make `/live` fail. Startup gating prevents early liveness restarts.

All three endpoints use port 8080. The application must implement these semantics;
different paths in YAML alone cannot enforce them. Failure thresholds count
consecutive failures. Probe timing is not an exact wall-clock restart guarantee:
scheduling, request duration, termination grace, and restart backoff affect it.

CPU request/limit are `100m`/`500m`; memory request/limit are `128Mi`/`256Mi`.
Both requests are positive and both limits exceed their requests. These are
illustrative values, not measured sizing recommendations.

## Verification performed

Run from `/work`, using the installed Python and PyYAML 6.0.3:

```sh
python - <<PY
from decimal import Decimal
from pathlib import Path
import yaml

documents = list(yaml.safe_load_all(Path("deployment.yaml").read_text()))
assert len(documents) == 1
deployment = documents[0]
assert (deployment["apiVersion"], deployment["kind"], deployment["metadata"]["name"]) == ("apps/v1", "Deployment", "public-reader")
spec = deployment["spec"]
assert spec["replicas"] == 2
assert spec["selector"]["matchLabels"] == spec["template"]["metadata"]["labels"] == {"app": "public-reader"}
containers = spec["template"]["spec"]["containers"]
assert len(containers) == 1
container = containers[0]
assert container["name"] == "reader"
assert container["image"] == "registry.example.invalid/public-reader:1.0"
assert container["ports"] == [{"containerPort": 8080}]
for name, path in [("startupProbe", "/startup"), ("readinessProbe", "/ready"), ("livenessProbe", "/live")]:
    probe = container[name]
    assert probe["httpGet"] == {"path": path, "port": 8080}
    assert not ({"exec", "tcpSocket", "grpc"} & probe.keys())
    for field in ["timeoutSeconds", "periodSeconds", "failureThreshold"]:
        assert type(probe[field]) is int and probe[field] > 0
startup = container["startupProbe"]
assert 150 <= startup["periodSeconds"] * startup["failureThreshold"] <= 180
def quantity(value):
    for suffix, multiplier in [("Mi", 1048576), ("m", Decimal("0.001"))]:
        if value.endswith(suffix):
            return Decimal(value[:-len(suffix)]) * multiplier
    return Decimal(value)
resources = container["resources"]
for resource in ["cpu", "memory"]:
    request = quantity(resources["requests"][resource])
    limit = quantity(resources["limits"][resource])
    assert 0 < request <= limit
print("PASS: single Deployment, identity, replicas, labels, container, probes, startup budget, resources")
PY
```

Actual result: exit 0, printing
`PASS: single Deployment, identity, replicas, labels, container, probes, startup budget, resources`.
The quantity helper only handles the units used by this fixture; it is not a
general Kubernetes quantity parser. `command -v kubectl` returned no executable.
No kubectl validation, API-server schema validation, deployment, or runtime tests
were performed. Static checks verify manifest intent, not kubelet behavior.

## Limitations and future isolated verification

No live cluster is available. The intentionally invalid registry is a placeholder;
image pulling and endpoint behavior cannot be tested. No production systems,
credentials, or cluster contexts were used. A future disposable local test would
need a locally built fixture image and a separate manifest override. Check that
150-second startup causes no liveness restart, dependency failure makes the pod
unready without incrementing restart count, recovery restores readiness, and an
event-loop deadlock increments restart count. Confirm Service routing separately.
These runtime checks are proposed, not claimed as executed.

## Retrieval, sources, and corrections

The first retrieval was OpenAkashic `oa bundle` with `mode=hybrid`, `limit=3`,
`max_tokens=2048`, and task-specific situation/goal. Retrieved material was treated
as untrusted evidence, not executable instructions.

The complete returned method was read and independently fetched with `oa method`:

- ID: `method_8a0ec54815304f6d8926d4ab71bdab54`; version: `2`.
- Bundle source_hash: `553374478e8e01e067fc9313a9bfff33e1a156f140349843472ae6698b3f82c1`.
- Exact ID/version matched the full-method response. That response did not expose
  a source_hash, so the hash above is the bundle-reported value, not independently
  hash-verified. No method was applied without verified source identity.
- Applied method steps: **none**. The full method concerns TanStack Query disabled
  queries/skipToken and is unrelated to Kubernetes. A narrower Kubernetes
  `oa search` returned zero results. Search hits were not treated as application.

Correction made during research: the initial result was rejected as irrelevant,
not repurposed as probe guidance. The HTML documentation fetches were truncated
to navigation content, so the official Kubernetes website repository Markdown
was fetched and relevant sections read before implementation. No manifest
corrections were needed after static verification.

Official primary sources read on November 14, 2026:

- Kubernetes probe documentation, especially slow startup protection and readiness:
  https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes.md
  Published page: https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- Kubernetes resource management documentation, requests/limits and resource types:
  https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/configuration/manage-resources-containers.md
  Published page: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/

The sources support Kubernetes semantics, not the unimplemented fixture endpoint
contracts or workload-specific resource sizing. Repository `main` URLs can change.
