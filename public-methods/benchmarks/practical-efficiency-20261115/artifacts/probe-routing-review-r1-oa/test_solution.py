"""Runnable offline contract tests using only the Python standard library."""

from copy import deepcopy
import unittest

from solution import configure_probes, probe_effect


class ConfigureProbesTests(unittest.TestCase):
    def setUp(self):
        self.deployment = {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "metadata": {"name": "documents", "labels": {"app": "renderer"}},
            "spec": {
                "replicas": 2,
                "selector": {"matchLabels": {"app": "renderer"}},
                "template": {
                    "metadata": {"labels": {"app": "renderer"}},
                    "spec": {
                        "containers": [
                            {
                                "name": "sidecar",
                                "image": "sidecar:example",
                                "livenessProbe": {"exec": {"command": ["true"]}},
                            },
                            {
                                "name": "renderer",
                                "image": "renderer:example",
                                "ports": [{"name": "health", "containerPort": 8087}],
                                "env": [{"name": "MODEL", "value": "local"}],
                                "startupProbe": {"tcpSocket": {"port": 80}},
                                "readinessProbe": {"exec": {"command": ["false"]}},
                                "livenessProbe": {
                                    "httpGet": {"path": "/old", "port": 80},
                                    "initialDelaySeconds": 999,
                                },
                            },
                        ]
                    },
                },
            },
        }

    def test_exact_configuration_and_preservation(self):
        original = deepcopy(self.deployment)
        result = configure_probes(self.deployment)
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
        self.assertEqual(result, expected)
        self.assertEqual(self.deployment, original)
        self.assertIsNot(result, self.deployment)

    def test_deep_copy_isolation(self):
        original = deepcopy(self.deployment)
        result = configure_probes(self.deployment)
        result["metadata"]["labels"]["app"] = "changed"
        containers = result["spec"]["template"]["spec"]["containers"]
        containers[0]["livenessProbe"]["exec"]["command"].append("changed")
        containers[1]["env"][0]["value"] = "changed"
        self.assertEqual(self.deployment, original)

    def test_absent_renderer(self):
        for deployment in ({}, {"spec": {}}, {"spec": {"template": {"spec": {
            "containers": [{"name": "sidecar"}]
        }}}}):
            with self.subTest(deployment=deployment):
                original = deepcopy(deployment)
                with self.assertRaises(ValueError):
                    configure_probes(deployment)
                self.assertEqual(deployment, original)

    def test_idempotent_and_accepts_minimal_renderer(self):
        deployment = {"spec": {"template": {"spec": {
            "containers": [{"name": "renderer"}]
        }}}}
        result = configure_probes(deployment)
        self.assertEqual(configure_probes(result), result)


class ProbeEffectTests(unittest.TestCase):
    def test_threshold_boundaries(self):
        for kind, threshold, effect in (
            ("startup", 32, "restart_container"),
            ("readiness", 2, "remove_from_service"),
            ("liveness", 3, "restart_container"),
        ):
            for count in (0, threshold - 1, threshold, threshold + 1, 1000000):
                with self.subTest(kind=kind, count=count):
                    expected = "no_action" if count < threshold else effect
                    self.assertEqual(probe_effect(kind, count, True), expected)

    def test_startup_gates_other_probes(self):
        for kind in ("readiness", "liveness"):
            for count in (0, 1, 2, 3, 32, 1000000):
                with self.subTest(kind=kind, count=count):
                    self.assertEqual(probe_effect(kind, count, False), "gated")

    def test_startup_itself_is_not_gated(self):
        for succeeded in (False, True):
            self.assertEqual(probe_effect("startup", 31, succeeded), "no_action")
            self.assertEqual(probe_effect("startup", 32, succeeded), "restart_container")

    def test_invalid_kind(self):
        for kind in ("", "Startup", "boot", "ready", "live"):
            for succeeded in (False, True):
                with self.subTest(kind=kind, succeeded=succeeded):
                    with self.assertRaises(ValueError):
                        probe_effect(kind, 0, succeeded)

    def test_negative_count_is_invalid_even_when_gated(self):
        for kind in ("startup", "readiness", "liveness"):
            for succeeded in (False, True):
                with self.subTest(kind=kind, succeeded=succeeded):
                    with self.assertRaises(ValueError):
                        probe_effect(kind, -1, succeeded)


if __name__ == "__main__":
    unittest.main()
