"""Standard-library offline regression tests."""

from copy import deepcopy
import unittest

from solution import configure_probes, probe_effect


def example_deployment():
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "document-worker", "labels": {"app": "renderer"}},
        "spec": {
            "replicas": 2,
            "selector": {"matchLabels": {"app": "renderer"}},
            "template": {
                "metadata": {"labels": {"app": "renderer"}},
                "spec": {
                    "containers": [
                        {"name": "sidecar", "image": "sidecar:example",
                         "readinessProbe": {"exec": {"command": ["true"]}}},
                        {"name": "renderer", "image": "renderer:example",
                         "ports": [{"name": "health", "containerPort": 8087}],
                         "env": [{"name": "MODE", "value": "offline"}],
                         "startupProbe": {"exec": {"command": ["false"]},
                                          "initialDelaySeconds": 200},
                         "readinessProbe": {"tcpSocket": {"port": 8087}},
                         "livenessProbe": {"httpGet": {"path": "/old", "port": 80},
                                           "initialDelaySeconds": 30}},
                    ],
                    "restartPolicy": "Always",
                },
            },
        },
    }


class ConfigureProbesTests(unittest.TestCase):
    def test_exact_replacement_and_preservation(self):
        original = example_deployment()
        before = deepcopy(original)
        actual = configure_probes(original)
        expected = deepcopy(before)
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
        self.assertEqual(actual, expected)
        self.assertEqual(original, before)

    def test_output_has_no_mutable_input_aliases(self):
        original = example_deployment()
        before = deepcopy(original)
        actual = configure_probes(original)
        actual["metadata"]["labels"]["app"] = "changed"
        actual["spec"]["template"]["spec"]["containers"][0]["image"] = "changed"
        actual["spec"]["template"]["spec"]["containers"][1]["ports"][0]["containerPort"] = 1
        self.assertEqual(original, before)

    def test_idempotent_and_can_add_absent_probes(self):
        original = example_deployment()
        renderer = original["spec"]["template"]["spec"]["containers"][1]
        for key in ("startupProbe", "readinessProbe", "livenessProbe"):
            del renderer[key]
        actual = configure_probes(original)
        self.assertEqual(configure_probes(actual), actual)
        self.assertIn("startupProbe", actual["spec"]["template"]["spec"]["containers"][1])

    def test_missing_renderer(self):
        original = example_deployment()
        original["spec"]["template"]["spec"]["containers"].pop()
        for deployment in (original, {}, {"spec": {"template": {"spec": {"containers": []}}}}):
            with self.subTest(deployment=deployment):
                before = deepcopy(deployment)
                with self.assertRaises(ValueError):
                    configure_probes(deployment)
                self.assertEqual(deployment, before)


class ProbeEffectTests(unittest.TestCase):
    def test_threshold_boundaries(self):
        for kind, threshold, action in (
            ("startup", 32, "restart_container"),
            ("readiness", 2, "remove_from_service"),
            ("liveness", 3, "restart_container"),
        ):
            for count in (0, threshold - 1, threshold, threshold + 1, 100000):
                with self.subTest(kind=kind, count=count):
                    self.assertEqual(probe_effect(kind, count, True),
                                     "no_action" if count < threshold else action)

    def test_gating(self):
        for kind in ("readiness", "liveness"):
            for count in (0, 1, 2, 3, 32, 100000):
                self.assertEqual(probe_effect(kind, count, False), "gated")

    def test_startup_not_gated(self):
        for succeeded in (False, True):
            self.assertEqual(probe_effect("startup", 31, succeeded), "no_action")
            self.assertEqual(probe_effect("startup", 32, succeeded), "restart_container")

    def test_invalid_inputs_even_when_gated(self):
        for succeeded in (False, True):
            for kind in ("", "boot", "Startup", None):
                with self.assertRaises(ValueError):
                    probe_effect(kind, 0, succeeded)
            for kind in ("startup", "readiness", "liveness"):
                with self.assertRaises(ValueError):
                    probe_effect(kind, -1, succeeded)


if __name__ == "__main__":
    unittest.main()
