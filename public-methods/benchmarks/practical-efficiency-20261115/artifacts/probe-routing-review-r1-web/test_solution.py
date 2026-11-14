"""Run using python -m unittest -v."""

from copy import deepcopy
import unittest

from solution import configure_probes, probe_effect


def example_deployment():
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "document-worker", "labels": {"app": "render"}},
        "spec": {
            "replicas": 2,
            "selector": {"matchLabels": {"app": "render"}},
            "template": {
                "metadata": {"labels": {"app": "render"}},
                "spec": {
                    "initContainers": [{"name": "setup", "image": "setup:offline"}],
                    "containers": [
                        {"name": "sidecar", "image": "sidecar:offline",
                         "livenessProbe": {"exec": {"command": ["true"]}}},
                        {"name": "renderer", "image": "renderer:offline",
                         "ports": [{"name": "health", "containerPort": 8087}],
                         "env": [{"name": "MODE", "value": "offline"}],
                         "startupProbe": {"exec": {"command": ["false"]},
                                          "initialDelaySeconds": 200},
                         "readinessProbe": {"tcpSocket": {"port": 8087}},
                         "livenessProbe": {"httpGet": {"path": "/old", "port": 80}}},
                        {"name": "logger", "image": "logger:offline"},
                    ],
                },
            },
        },
    }


class ConfigureTests(unittest.TestCase):
    def test_exact_replacement_and_preservation(self):
        original = example_deployment()
        before = deepcopy(original)
        expected = deepcopy(original)
        renderer = expected["spec"]["template"]["spec"]["containers"][1]
        for kind, path, period, threshold in (
            ("startup", "/boot", 5, 32),
            ("readiness", "/ready", 4, 2),
            ("liveness", "/live", 10, 3),
        ):
            renderer[kind + "Probe"] = {
                "httpGet": {"path": path, "port": "health"},
                "periodSeconds": period,
                "failureThreshold": threshold,
                "timeoutSeconds": 1,
            }
        actual = configure_probes(original)
        self.assertEqual(actual, expected)
        self.assertEqual(original, before)

    def test_returned_nested_data_is_independent(self):
        original = example_deployment()
        before = deepcopy(original)
        configured = configure_probes(original)
        configured["metadata"]["labels"]["app"] = "changed"
        configured["spec"]["template"]["spec"]["containers"][0]["image"] = "changed"
        self.assertEqual(original, before)

    def test_idempotent(self):
        configured = configure_probes(example_deployment())
        self.assertEqual(configure_probes(configured), configured)

    def test_missing_renderer(self):
        original = example_deployment()
        original["spec"]["template"]["spec"]["containers"].pop(1)
        for deployment in (original, {}, {"spec": {"template": {"spec": {}}}}):
            with self.subTest(deployment=deployment):
                before = deepcopy(deployment)
                with self.assertRaises(ValueError):
                    configure_probes(deployment)
                self.assertEqual(deployment, before)

    def test_add_probes_when_not_present(self):
        original = example_deployment()
        renderer = original["spec"]["template"]["spec"]["containers"][1]
        for kind in ("startup", "readiness", "liveness"):
            del renderer[kind + "Probe"]
        configured = configure_probes(original)
        updated = configured["spec"]["template"]["spec"]["containers"][1]
        self.assertTrue(all(kind + "Probe" in updated
                            for kind in ("startup", "readiness", "liveness")))
        self.assertNotIn("startupProbe", renderer)


class EffectTests(unittest.TestCase):
    def test_all_boundaries_and_startup_states(self):
        for kind, threshold, effect in (
            ("startup", 32, "restart_container"),
            ("readiness", 2, "remove_from_service"),
            ("liveness", 3, "restart_container"),
        ):
            for startup in (False, True):
                for failures in (0, threshold - 1, threshold, threshold + 1, 10**6):
                    with self.subTest(kind=kind, startup=startup, failures=failures):
                        expected = "no_action" if failures < threshold else effect
                        if not startup and kind != "startup":
                            expected = "gated"
                        self.assertEqual(probe_effect(kind, failures, startup), expected)

    def test_invalid_inputs_even_when_gated(self):
        for startup in (False, True):
            for kind in ("", "boot", "Startup", "unknown"):
                with self.subTest(kind=kind, startup=startup):
                    with self.assertRaises(ValueError):
                        probe_effect(kind, 0, startup)
            for kind in ("startup", "readiness", "liveness"):
                with self.subTest(kind=kind, startup=startup):
                    with self.assertRaises(ValueError):
                        probe_effect(kind, -1, startup)


if __name__ == "__main__":
    unittest.main()
