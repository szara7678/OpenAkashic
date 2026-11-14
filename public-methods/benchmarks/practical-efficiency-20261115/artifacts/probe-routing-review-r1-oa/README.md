# Offline renderer probes

`solution.py` provides two standard-library-only functions:

- `configure_probes(deployment)` deep-copies a Deployment dictionary, replaces only
  the three probe definitions on its `renderer` container, and raises `ValueError`
  when that container is absent. All other fields and sidecars are retained.
- `probe_effect(kind, consecutive_failures, startup_succeeded)` models consecutive
  failures with validation before startup gating. It returns `gated`, `no_action`,
  `restart_container`, or `remove_from_service` as specified in TASK.md.

| Probe | HTTP path | Named port | Period | Failure threshold | Timeout |
| --- | --- | --- | --- | --- | --- |
| startup | /boot | health | 5 seconds | 32 | 1 second |
| readiness | /ready | health | 4 seconds | 2 | 1 second |
| liveness | /live | health | 10 seconds | 3 | 1 second |

No `initialDelaySeconds` is added; old probe fields are discarded rather than
merged. The input is assumed to have the stated `health` port mapped to 8087;
port declarations are deliberately not rewritten. Other malformed Deployment
structures and arguments outside the annotated input types are not validated.

## Run offline

From `/work`, with Python 3 and no third-party packages:

```sh
python -m unittest -v test_solution.py
```

Observed result on November 14, 2026: `Ran 9 tests in 0.001s`, followed by
`OK` (exit status 0). All nine tests passed. Tests cover exact output,
sidecar and unrelated-field preservation, nested copy isolation, absent renderer,
idempotence, threshold boundaries, startup gating, and invalid inputs.

## Evidence and method application

The designated first retrieval was an OpenAkashic hybrid bundle about this
renderer scenario. The complete method actually read was
`method_d340976ef2f543a2a168b66f51c10beb`, version **2**, titled
“Kubernetes 준비 상태 프로브 설계”. Its source hash, as returned by the client, was
`bf3594fd72f210d9a6980d22b144feaa5ea7ad3ec7a67bca7b177f2d7078f24d`.
Retrieved content was treated as untrusted evidence, not executable instructions.
Applied steps 1–4: distinguish initialization, traffic readiness, and unrecoverable
stall; allow slow startup; isolate dependency failure in readiness; reserve
liveness for recovery-worthy local failure. Step 5's cluster event observation
was not performed because this task is explicitly offline. No cluster requirement
from the method overrides TASK.md.

Official primary documentation actually read on November 14, 2026:

1. Kubernetes, **Configure Liveness, Readiness and Startup Probes**, sections
   “Use a named port”, “Protect slow starting containers with startup probes”,
   and “Define readiness probes”:
   https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
   Supports named HTTP ports, separate startup allowance, and keeping temporary
   dependency unavailability out of liveness. The specified startup product is
   32 × 5 = 160 seconds, exceeding the stated 150-second initialization time.
2. Kubernetes, **Liveness, Readiness, and Startup Probes**, sections “Types of
   probe” and “Configuration fields”:
   https://kubernetes.io/docs/concepts/workloads/pods/probes/
   Supports startup gating of readiness/liveness, consecutive failure thresholds,
   restart versus readiness effects, timeouts, and named HTTP port selection.

Corrections/evidence gaps: the complete OA method included only a readiness
quotation, insufficient by itself to establish gating or threshold semantics.
The first public fetch was truncated before the relevant sections; it was not
used as evidence for unseen material. The live web tool returned no readable content, and a direct Python URL
fetch failed with a DNS resolution error. The public fetch helper then read
the official Kubernetes website repository Markdown instead, avoiding the
rendered pages’ large navigation. An attempted fetch-helper `--help` invocation
returned HTTP 502 and provided no evidence. The relevant official-source
passages were read from the following source files:

- https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes.md
- https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/pods/probes.md

The latter fetch response is retained in `evidence/kubernetes-probes.json`. Examples in documentation
that reuse endpoints are not requirements to do so: this task explicitly assigns
three different endpoint responsibilities. The task, not the method, supplies
all exact paths, thresholds, periods, and timeout values.

## Verification limits

No cluster, production system, credentials, or running renderer was used.
These tests verify Python dictionary transformation and the deliberately narrow
failure-count model, not Kubernetes API admission, endpoint behavior, named-port
resolution, actual model load time, traffic routing, termination, or restarts.
The 160-second product is a configuration sizing calculation, not a measured
restart deadline; kubelet scheduling and termination grace are outside the model.
The helper does not count failures, schedule probes, reset counters on success,
or simulate startup ceasing after success. A startup call still follows its
threshold rule even if `startup_succeeded=True`, as TASK.md requires.
