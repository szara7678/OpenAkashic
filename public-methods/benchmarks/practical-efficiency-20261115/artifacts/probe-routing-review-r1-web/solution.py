"""Offline renderer probe configuration and consecutive-failure effects."""

from copy import deepcopy


_PROBES = {
    "startup": ("/boot", 5, 32),
    "readiness": ("/ready", 4, 2),
    "liveness": ("/live", 10, 3),
}


def configure_probes(deployment: dict) -> dict:
    """Return an independent copy with only renderer's probes replaced.

    The input is a Deployment dictionary whose renderer already exposes the
    named health port on 8087. Other container fields are preserved verbatim.
    """
    configured = deepcopy(deployment)
    containers = (
        configured.get("spec", {})
        .get("template", {})
        .get("spec", {})
        .get("containers", [])
    )
    renderer = next(
        (container for container in containers if container.get("name") == "renderer"),
        None,
    )
    if renderer is None:
        raise ValueError("Deployment has no container named renderer")

    for kind, (path, period, threshold) in _PROBES.items():
        renderer[f"{kind}Probe"] = {
            "httpGet": {"path": path, "port": "health"},
            "periodSeconds": period,
            "failureThreshold": threshold,
            "timeoutSeconds": 1,
        }
    return configured


def probe_effect(
    kind: str, consecutive_failures: int, startup_succeeded: bool
) -> str:
    """Model failure thresholds only, not probe scheduling or elapsed time."""
    if kind not in _PROBES:
        raise ValueError("kind must be startup, readiness, or liveness")
    if consecutive_failures < 0:
        raise ValueError("consecutive_failures must be nonnegative")
    if kind != "startup" and not startup_succeeded:
        return "gated"
    if consecutive_failures < _PROBES[kind][2]:
        return "no_action"
    if kind == "readiness":
        return "remove_from_service"
    return "restart_container"
