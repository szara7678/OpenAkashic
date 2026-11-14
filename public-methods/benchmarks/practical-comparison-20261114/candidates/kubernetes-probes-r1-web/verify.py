import unittest
from decimal import Decimal
from pathlib import Path

import yaml


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        documents = list(yaml.safe_load_all(Path(__file__).with_name("deployment.yaml").read_text()))
        assert len(documents) == 1, "Expected exactly one YAML document"
        cls.deployment = documents[0]
        cls.spec = cls.deployment["spec"]
        cls.containers = cls.spec["template"]["spec"]["containers"]
        cls.container = cls.containers[0]

    def test_identity(self):
        self.assertEqual(self.deployment["apiVersion"], "apps/v1")
        self.assertEqual(self.deployment["kind"], "Deployment")
        self.assertEqual(self.deployment["metadata"]["name"], "public-reader")
        self.assertEqual(self.spec["replicas"], 2)

    def test_labels(self):
        expected = {"app": "public-reader"}
        self.assertEqual(self.spec["selector"]["matchLabels"], expected)
        self.assertEqual(self.spec["template"]["metadata"]["labels"], expected)

    def test_container(self):
        self.assertEqual(len(self.containers), 1)
        self.assertEqual(self.container["name"], "reader")
        self.assertEqual(self.container["image"], "registry.example.invalid/public-reader:1.0")
        self.assertEqual(self.container["ports"], [{"containerPort": 8080}])

    def test_probes(self):
        for name, path in (("startupProbe", "/startup"), ("readinessProbe", "/ready"), ("livenessProbe", "/live")):
            with self.subTest(probe=name):
                probe = self.container[name]
                self.assertEqual(probe["httpGet"], {"path": path, "port": 8080})
                self.assertFalse(set(probe) & {"exec", "tcpSocket", "grpc"})
                for field in ("timeoutSeconds", "periodSeconds", "failureThreshold"):
                    self.assertIs(type(probe[field]), int)
                    self.assertGreater(probe[field], 0)

    def test_startup_budget(self):
        probe = self.container["startupProbe"]
        budget = probe["periodSeconds"] * probe["failureThreshold"]
        self.assertGreaterEqual(budget, 150)
        self.assertLessEqual(budget, 180)

    def test_resources(self):
        resources = self.container["resources"]
        for resource, suffix, multiplier in (("cpu", "m", Decimal("0.001")), ("memory", "Mi", Decimal(2 ** 20))):
            with self.subTest(resource=resource):
                quantities = []
                for category in ("requests", "limits"):
                    value = resources[category][resource]
                    self.assertTrue(value.endswith(suffix))
                    quantities.append(Decimal(value[:-len(suffix)]) * multiplier)
                self.assertGreater(quantities[0], 0)
                self.assertGreaterEqual(quantities[1], quantities[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
