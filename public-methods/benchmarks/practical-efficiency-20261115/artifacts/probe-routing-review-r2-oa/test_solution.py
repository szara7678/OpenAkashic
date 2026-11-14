"""Standard-library offline contract tests."""

from copy import deepcopy
import unittest

from solution import configure_probes, probe_effect


def deployment_fixture():
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "render-worker", "labels": {"app": "renderer"}},
        "spec": {
            "replicas": 2,
            "selector": {"matchLabels": {"app": "renderer"}},
            "template": {
                "metadata": {"labels": {"app": "renderer"}},
                "spec": {
                    "containers": [
                        {"name": "sidecar", "image": "example/sidecar:test",
                         "readinessProbe": {"exec": {"command": ["true"]}}},
                        {"name": "renderer", "image": "example/renderer:test",
                         "ports": [{"name": "health", "containerPort": 8087}],
                         "env": [{"name": "MODE", "value": "offline"}],
                         "startupProbe": {"exec": {"command": ["old"]}},
                         "readinessProbe": {"tcpSocket": {"port": 80}},
                         "livenessProbe": {"initialDelaySeconds": 999}},
                    ]
                },
            },
        },
    }


class ConfigurationTests(unittest.TestCase):
    def test_exact_configuration_and_preservation(self):
        original = deployment_fixture()
        before = deepcopy(original)
        result = configure_probes(original)
        expected = deepcopy(before)
        renderer = expected["spec"]["template"]["spec"]["containers"][1]
        for kind, path, period, threshold in [
            ("startup", "/boot", 5, 32),
            ("readiness", "/ready", 4, 2),
            ("liveness", "/live", 10, 3),
        ]:
            renderer[kind + "Probe"] = {
                "httpGet": {"path": path, "port": "health"},
                "periodSeconds": period,
                "failureThreshold": threshold,
                "timeoutSeconds": 1,
            }
        self.assertEqual(result, expected)
        self.assertEqual(original, before)
        self.assertIsNot(result, original)

    def test_deep_copy_independence(self):
        original = deployment_fixture()
        result = configure_probes(original)
        result["metadata"]["labels"]["app"] = "changed"
        result["spec"]["template"]["spec"]["containers"][0]["image"] = "changed"
        self.assertEqual(original, deployment_fixture())

    def test_idempotence_and_no_existing_probes(self):
        original = deployment_fixture()
        renderer = original["spec"]["template"]["spec"]["containers"][1]
        for kind in ("startup", "readiness", "liveness"):
            del renderer[kind + "Probe"]
        configured = configure_probes(original)
        self.assertEqual(configure_probes(configured), configured)

    def test_missing_renderer(self):
        original = deployment_fixture()
        original["spec"]["template"]["spec"]["containers"].pop()
        for deployment in (original, {}, {"spec": {"template": {"spec": {}}}}):
            with self.subTest(deployment=deployment):
                before = deepcopy(deployment)
                with self.assertRaises(ValueError):
                    configure_probes(deployment)
                self.assertEqual(deployment, before)


class EffectTests(unittest.TestCase):
    def test_threshold_boundaries(self):
        for kind, threshold, effect in [
            ("startup", 32, "restart_container"),
            ("readiness", 2, "remove_from_service"),
            ("liveness", 3, "restart_container"),
        ]:
            for count in (0, threshold - 1, threshold, threshold + 1, 10000):
                with self.subTest(kind=kind, count=count):
                    self.assertEqual(
                        probe_effect(kind, count, True),
                        "no_action" if count < threshold else effect,
                    )

    def test_startup_gates_readiness_and_liveness(self):
        for kind in ("readiness", "liveness"):
            for count in (0, 1, 2, 3, 32, 10000):
                with self.subTest(kind=kind, count=count):
                    self.assertEqual(probe_effect(kind, count, False), "gated")

    def test_startup_itself_is_not_gated(self):
        self.assertEqual(probe_effect("startup", 31, False), "no_action")
        self.assertEqual(probe_effect("startup", 32, False), "restart_container")

    def test_invalid_kind(self):
        for kind in ("", "boot", "Startup", None, []):
            with self.subTest(kind=kind):
                with self.assertRaises(ValueError):
                    probe_effect(kind, 0, False)

    def test_negative_count_is_rejected_before_gating(self):
        for kind in ("startup", "readiness", "liveness"):
            for startup_succeeded in (False, True):
                with self.subTest(kind=kind, startup_succeeded=startup_succeeded):
                    with self.assertRaises(ValueError):
                        probe_effect(kind, -1, startup_succeeded)

    def test_noninteger_count(self):
        for count in (1.5, "2", None):
            with self.subTest(count=count):
                with self.assertRaises(ValueError):
                    probe_effect("readiness", count, False)


if __name__ == "__main__":
    unittest.main()
