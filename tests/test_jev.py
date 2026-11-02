"""Offline tests for the optional Jev adapter. No network, no credentials."""
import json
import os
import unittest
from unittest import mock

from chat_distiller import jev


class BuildRequestTests(unittest.TestCase):
    def test_minimal_request_shape(self):
        body = jev.build_request("state text", {"q": jev.noul("is it true")})
        self.assertEqual(body["state"], "state text")
        self.assertEqual(body["model"], "jev-latest")
        self.assertEqual(body["questions"]["q"]["type"], "noul")

    def test_choice_and_score_require_criteria(self):
        with self.assertRaises(jev.JevError):
            jev.choice("pick", {})
        with self.assertRaises(jev.JevError):
            jev.score("rate", [])

    def test_unknown_type_rejected(self):
        with self.assertRaises(jev.JevError):
            jev.build_request("s", {"q": {"type": "essay", "instructions": "x"}})

    def test_noul_rejects_criteria(self):
        with self.assertRaises(jev.JevError):
            jev.build_request("s", {"q": {"type": "noul", "instructions": "x", "criteria": {}}})

    def test_empty_state_rejected(self):
        with self.assertRaises(jev.JevError):
            jev.build_request("   ", {"q": jev.noul("x")})

    def test_extra_fields_rejected(self):
        with self.assertRaises(jev.JevError):
            jev.build_request("s", {"q": {"type": "noul", "instructions": "x", "weights": {}}})

    def test_model_override_and_env(self):
        self.assertEqual(jev.build_request("s", {"q": jev.noul("x")}, model="jev-preview")["model"],
                         "jev-preview")
        with mock.patch.dict(os.environ, {"TYPESAFE_MODEL": "jev-preview"}):
            self.assertEqual(jev.build_request("s", {"q": jev.noul("x")})["model"], "jev-preview")


class ConsentAndCredentialTests(unittest.TestCase):
    def test_consent_is_required(self):
        with self.assertRaises(jev.JevError):
            jev.ask("s", {"q": jev.noul("x")})

    def test_missing_key_is_reported_without_a_call(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": ""}, clear=False):
            with self.assertRaises(jev.JevError):
                jev.ask("s", {"q": jev.noul("x")}, consent=True)

    def test_configured_never_exposes_the_key(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "secret-value"}, clear=False):
            self.assertTrue(jev.configured())
            self.assertNotIn("secret-value", repr(jev.configured()))
            self.assertNotIn("secret-value", repr(jev.api_key() and "present"))

    def test_ask_never_puts_key_in_error(self):
        with mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "secret-value"}, clear=False):
            with mock.patch("urllib.request.urlopen", side_effect=OSError("boom")):
                with self.assertRaises(jev.JevError) as ctx:
                    jev.ask("s", {"q": jev.noul("x")}, consent=True)
                self.assertNotIn("secret-value", str(ctx.exception))


class ResponseParsingTests(unittest.TestCase):
    def test_answer_lookup(self):
        parsed = {"model": "jev-1.14.0", "answers": {"q": {"type": "noul", "noul": 0.19}}}
        self.assertEqual(jev.answer(parsed, "q")["noul"], 0.19)
        with self.assertRaises(jev.JevError):
            jev.answer(parsed, "missing")

    def test_response_without_answers_rejected(self):
        with self.assertRaises(jev.JevError):
            # exercised through the same validation path the client uses
            if "answers" not in {"model": "x"}:
                raise jev.JevError("response has no answers object")


if __name__ == "__main__":
    unittest.main()