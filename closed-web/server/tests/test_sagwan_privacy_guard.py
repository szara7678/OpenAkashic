"""Tests for the secret-pattern privacy guardrail in sagwan_loop.

The publication_judge LLM is not enough on its own — `_detect_secret_pattern`
acts as a hard regex floor that downgrades any "published" verdict to private
when the capsule body contains anything that looks like a credential or
session marker.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app import sagwan_loop


class DetectSecretPatternTests(unittest.TestCase):
    def test_clean_text_returns_none(self) -> None:
        self.assertIsNone(sagwan_loop._detect_secret_pattern(""))
        self.assertIsNone(
            sagwan_loop._detect_secret_pattern(
                "## Summary\n일반적인 캡슐 본문. 시크릿 없음.\n## Sources\n- https://example.com/a\n"
            )
        )

    def test_empty_input_returns_none(self) -> None:
        self.assertIsNone(sagwan_loop._detect_secret_pattern(None))  # type: ignore[arg-type]

    def test_openai_api_key_match(self) -> None:
        body = "API key: sk-abcdef0123456789ABCDEF"
        self.assertEqual(sagwan_loop._detect_secret_pattern(body), "openai_api_key")

    def test_openai_proj_key_match(self) -> None:
        body = "key=sk-proj-abcdef0123456789ABCDEFxyz"
        # Order in _SECRET_PATTERNS: openai_api_key matches first since `sk-proj-...`
        # also matches `sk-[A-Za-z0-9_\-]{16,}`. We only assert it gets caught.
        self.assertIsNotNone(sagwan_loop._detect_secret_pattern(body))

    def test_anthropic_key_match(self) -> None:
        body = "Authorization: sk-ant-abcdef0123456789ABCDEF"
        self.assertIsNotNone(sagwan_loop._detect_secret_pattern(body))

    def test_github_pat_match(self) -> None:
        body = "token = ghp_" + "a" * 36
        self.assertEqual(sagwan_loop._detect_secret_pattern(body), "github_pat")

    def test_aws_access_key_match(self) -> None:
        body = "use AKIAIOSFODNN7EXAMPLE for access"
        self.assertEqual(sagwan_loop._detect_secret_pattern(body), "aws_access_key_id")

    def test_slack_bot_token_match(self) -> None:
        body = "slack: xoxb-12345678901-abcdef"
        self.assertEqual(sagwan_loop._detect_secret_pattern(body), "slack_bot_token")

    def test_private_key_block_match(self) -> None:
        body = "key:\n-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
        self.assertEqual(sagwan_loop._detect_secret_pattern(body), "private_key_block")

    def test_ssh_private_block_match(self) -> None:
        # OPENSSH PRIVATE KEY also matches the broader private_key_block pattern,
        # which sits earlier in the list. Either flag is equally protective —
        # what we care about is that the body is detected as secret material.
        body = "-----BEGIN OPENSSH PRIVATE KEY-----\nblob\n"
        self.assertIn(
            sagwan_loop._detect_secret_pattern(body),
            ("ssh_private_block", "private_key_block"),
        )

    def test_bearer_assignment_match(self) -> None:
        body = "use Bearer abcdef0123456789abcdef0123456789ABCDEF"
        self.assertIsNotNone(sagwan_loop._detect_secret_pattern(body))

    def test_authorization_header_match(self) -> None:
        body = "Authorization: Bearer abcdef0123456789abcdefABCDEF"
        self.assertIsNotNone(sagwan_loop._detect_secret_pattern(body))

    def test_password_assignment_match(self) -> None:
        body = "DB_PASSWORD = 'supersecret123'"
        self.assertEqual(sagwan_loop._detect_secret_pattern(body), "password_assignment")

    def test_jwt_token_match(self) -> None:
        body = (
            "token: "
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
            ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ"
            ".SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        )
        self.assertEqual(sagwan_loop._detect_secret_pattern(body), "jwt_token")

    def test_openakashic_admin_token_match(self) -> None:
        body = "CLOSED_AKASHIC_BEARER_TOKEN=abcdef0123456789ABCDEF"
        self.assertEqual(sagwan_loop._detect_secret_pattern(body), "openakashic_admin")

    def test_first_match_wins(self) -> None:
        body = "ghp_" + "a" * 36 + " AKIAIOSFODNN7EXAMPLE"
        # whichever appears first in _SECRET_PATTERNS list (github_pat) should win
        self.assertEqual(sagwan_loop._detect_secret_pattern(body), "github_pat")

    def test_pattern_does_not_false_positive_on_short_strings(self) -> None:
        # Should not flag short prefixes that don't meet the length requirement
        self.assertIsNone(sagwan_loop._detect_secret_pattern("sk-short"))
        self.assertIsNone(sagwan_loop._detect_secret_pattern("ghp_short"))
        self.assertIsNone(sagwan_loop._detect_secret_pattern("AKIA123"))


if __name__ == "__main__":
    unittest.main()
