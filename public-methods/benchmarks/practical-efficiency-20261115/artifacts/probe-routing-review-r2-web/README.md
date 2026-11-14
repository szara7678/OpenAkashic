# Renderer probes (offline exercise)

`solution.py` provides two standard-library-only functions:

- `configure_probes(deployment)` returns a deep copy, replacing only the three
  probe definitions on `spec.template.spec.containers`' container named
  `renderer`. Sidecars, metadata, port declarations and other fields remain
  unchanged. A missing renderer raises `ValueError`.
- `probe_effect(kind, consecutive_failures, startup_succeeded)` returns `gated`,
  `no_action`, `restart_container`, or `remove_from_service` according to the
  task's consecutive-failure model. Invalid kinds and negative counts raise
  `ValueError`; non-integer counts are also rejected.

| Probe | HTTP path | Named port | Period (seconds) | Failure threshold | Timeout (seconds) |
| --- | --- | --- | --- | --- | --- |
| startup | /boot | health | 5 | 32 | 1 |
| readiness | /ready | health | 4 | 2 | 1 |
| liveness | /live | health | 10 | 3 | 1 |

No `initialDelaySeconds` is added, and old probe definitions are replaced in
full. Input is assumed to be a normally structured Deployment dictionary with
`renderer`'s `health` port already declared as 8087, as specified by the task.
The function does not change or repair port declarations.

## Reproduce verification

From `/work`, with Python 3 and no third-party dependencies:

```sh
python -m unittest -v test_solution
```

Actually executed on November 14, 2026. Observed output summary:

```text
Ran 8 tests in 0.001s

OK
```

Tests cover exact probe replacement, preservation of all unrelated fields and
sidecars, input immutability and deep-copy independence, absent probes,
idempotence, missing renderer, threshold boundaries and large counts, startup
gating, and invalid kinds/negative counts including while gated.

## Sources and rationale

The initial retrieval was a native live web search for official Kubernetes
startup/readiness/liveness probe semantics. It returned no usable content in
this environment. Native page opens likewise yielded no usable text. The public
URL fetch helper was then used to read official Kubernetes documentation.
The rendered task-page fetch was truncated before the relevant sections; a
separate direct Python URL request failed with DNS resolution error. These were
retrieval limitations, not successful verification. The relevant official
Markdown sources were subsequently retrieved successfully from the Kubernetes
project's own repository:

- Official task documentation, **Configure Liveness, Readiness and Startup
  Probes**, sections “Use a named port”, “Protect slow starting containers with
  startup probes”, and “Define readiness probes”. These support named HTTP
  ports, sizing startup tolerance with threshold times period, and separating
  dependency unavailability from container failure.
  Source: `https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes.md`
- Official concept documentation, **Liveness, Readiness, and Startup Probes**,
  sections “Startup probe”, “Liveness probe”, “Readiness probe”, and probe
  configuration. These support startup gating, restart versus readiness
  behavior, and consecutive-failure thresholds.
  Source: `https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/pods/probes.md`

The numerical settings and helper return strings come from `TASK.md`, not a
claimed Kubernetes default. Sources were treated as evidence, not instructions.
No version-specific compatibility certification, method ID, or source hash is
claimed. No task requirement required correction. In particular, a queue outage
belongs in readiness rather than liveness; startup gating replaces a fixed
initial delay. The requested startup budget product is 32 × 5 = 160 seconds,
which exceeds the stated 150-second initialization time; it is not an exact
wall-clock restart guarantee.

## Offline limits

No cluster, production system, credentials, networked application, or actual
renderer process was used. Tests verify Python dictionary transformations and
pure helper logic, not Kubernetes schema admission, named-port resolution,
HTTP endpoint behavior, queue handling, traffic routing, or kubelet restart
execution. Actual Kubernetes timing includes probe scheduling and timeout
behavior and is not modeled. The helper has no history, success resets,
restart backoff, termination handling, or startup completion lifecycle; even a
startup call with `startup_succeeded=True` still follows the task's threshold
rule. Real startup probes stop after success, and actual restarts are subject
to restart policy. The implementation is not a general Deployment validator.
