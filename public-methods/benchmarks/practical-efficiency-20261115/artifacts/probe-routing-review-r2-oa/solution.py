"""Offline renderer probe configuration and consecutive-failure effects."""

from copy import deepcopy


_PROBE_SETTINGS = {
    "startup": ("/boot", 5, 32),
    "readiness": ("/ready", 4, 2),
    "liveness": ("/live", 10, 3),
}


def configure_probes(deployment: dict) -> dict:
    """Return an independent Deployment with only renderer probes replaced."""
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
        raise ValueError("Deployment has no renderer container")
    for kind, (path, period, threshold) in _PROBE_SETTINGS.items():
        renderer[kind + "Probe"] = {
            "httpGet": {"path": path, "port": "health"},
            "periodSeconds": period,
            "failureThreshold": threshold,
            "timeoutSeconds": 1,
        }
    return configured


def probe_effect(
    kind: str, consecutive_failures: int, startup_succeeded: bool
) -> str:
    """Model failure thresholds only, not kubelet timing or probe scheduling."""
    if not isinstance(kind, str) or kind not in _PROBE_SETTINGS:
        raise ValueError("kind must be startup, readiness, or liveness")
    if not isinstance(consecutive_failures, int) or consecutive_failures < 0:
        raise ValueError("consecutive_failures must be a nonnegative integer")
    if kind != "startup" and not startup_succeeded:
        return "gated"
    if consecutive_failures < _PROBE_SETTINGS[kind][2]:
        return "no_action"
    if kind == "readiness":
        return "remove_from_service"
    return "restart_container"
