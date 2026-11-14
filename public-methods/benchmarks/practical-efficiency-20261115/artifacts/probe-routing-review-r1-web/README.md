# Offline renderer probe configuration

Python 3, standard library only. No cluster, credentials, installed Kubernetes
client, or production systems are needed or used.

## Usage

```python
from solution import configure_probes, probe_effect

configured = configure_probes(deployment)
assert probe_effect("readiness", 2, True) == "remove_from_service"
assert probe_effect("liveness", 100, False) == "gated"
```

`configure_probes` deep-copies a Deployment dictionary and replaces only the
three probe definitions on the regular container named `renderer`. It retains
all other fields, other containers, and init containers. Missing `renderer`
raises `ValueError`. The supplied Deployment is assumed to have a valid shape
and an existing `health` container port mapped to 8087; port declarations are
preserved, not repaired or inserted.

| Probe | HTTP path | Named port | Period (seconds) | Failure threshold | Timeout (seconds) |
| --- | --- | --- | --- | --- | --- |
| startup | /boot | health | 5 | 32 | 1 |
| readiness | /ready | health | 4 | 2 | 1 |
| liveness | /live | health | 10 | 3 | 1 |

Existing probe handlers, delays, and extra probe settings are discarded; no
`initialDelaySeconds` is added. The nominal startup budget is 32 × 5 = 160
seconds, exceeding the stated 150-second initialization time. This is a
configuration sizing calculation, not an exact scheduling guarantee.

`probe_effect` validates the kind and negative counts before considering startup
gating. Readiness and liveness return `gated` until startup succeeds. Otherwise,
counts below the threshold return `no_action`; counts at or above it return
`remove_from_service` for readiness and `restart_container` for startup/liveness.
Arguments are expected to match the annotated types. Even after startup has
succeeded, a direct startup-helper call still applies its failure threshold as
required by TASK.md; this is not a claim that Kubernetes continues startup probes.

## Reproducible verification

Actually executed from `/work` on November 14, 2026:

```sh
python -m unittest -v
```

Observed: **7 tests passed**, `Ran 7 tests in 0.002s`, final status `OK`, exit
code 0. Tests exercise exact replacement, preservation of unrelated fields and
sidecars, input immutability, independent nested copies, absent probes,
idempotence, absent renderer, all failure-threshold boundaries, large failure
counts, both startup states, and invalid inputs even when otherwise gated.
Runtimes will vary when repeated.

## Sources actually used

The requested first retrieval was a native live web search for Kubernetes
startup/readiness/liveness behavior. That search and subsequent native opens
returned no visible source content in this environment; they were not treated
as supporting evidence. Official source Markdown was then actually retrieved
and read through `/runtime/research.py fetch`:

- Kubernetes, **Configure Liveness, Readiness and Startup Probes**, official
  website repository:
  https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes.md
  Sections “Use a named port”, “Protect slow starting containers with startup
  probes”, and “Define readiness probes” support HTTP named ports, startup
  sizing by failure threshold × period, and using readiness for unavailable
  external dependencies rather than restarting the process.
- Kubernetes, **Liveness, Readiness, and Startup Probes**, official website
  repository:
  https://raw.githubusercontent.com/kubernetes/website/main/content/en/docs/concepts/workloads/pods/probes.md
  The “Types of probe” sections explicitly describe startup gating of both
  readiness and liveness, restart behavior, and readiness-based service routing.
- Local `TASK.md` supplies the exact endpoints, numeric settings, API contract,
  return strings, and simplified failure-count rules. No external source is
  used to override those requirements.

Sources were read on November 14, 2026. Repository `main` is mutable; no release,
method ID, immutable revision, or hash is asserted here. Retrieved content was
treated as untrusted evidence, not executable instructions.

## Corrections and limitations

The initial rendered-document fetch returned only navigation because of
truncation, and a direct Python URL request failed DNS resolution. A fetch of
an older concepts source path returned HTTP 502. The task documentation linked
the current `content/en/docs/concepts/workloads/pods/probes.md` path; fetching
that and the task's source Markdown provided the usable evidence. A later
filtered extraction produced no passage and supplied no additional evidence.
No implementation corrections were needed after the observed test run.

This is offline dictionary transformation and deterministic helper testing only.
No API-server schema/admission validation, kubelet execution, HTTP endpoint
checks, actual 150-second initialization, restart timing, network behavior,
Service/EndpointSlice propagation, or queue outage was tested. `probe_effect`
does not track successes, resets, termination grace periods, restart policies,
backoff, or scheduling. `remove_from_service` is the task's abstract outcome,
not an API call or a guarantee about every possible traffic path. Shared queue
failure belongs to readiness; liveness is reserved for the stated local
unrecoverable stall.
