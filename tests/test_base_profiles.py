import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from contract_runtime import envelope_semantic_issues, profile_semantic_issues


PROFILES = {
    "event-record": {
        "primary_key": ["event_id", "event_time", "entity_id"],
        "time": "event_time",
        "first": "event_id",
    },
    "factor-panel": {
        "primary_key": ["instrument_id", "timestamp", "factor_id"],
        "time": "timestamp",
        "first": "instrument_id",
    },
    "fundamental-pit": {
        "primary_key": ["instrument_id", "period_end", "available_at", "statement_scope"],
        "time": "point-in-time",
        "first": "instrument_id",
    },
    "futures-contract": {
        "primary_key": ["exchange", "contract_id", "trade_date"],
        "time": "trade_date",
        "first": "exchange",
    },
    "holdings": {
        "primary_key": ["portfolio_id", "instrument_id", "as_of"],
        "time": "as_of",
        "first": "portfolio_id",
    },
    "macro-series": {
        "primary_key": ["series_id", "observation_date", "vintage_date"],
        "time": "vintage",
        "first": "series_id",
    },
    "market-bar": {
        "primary_key": ["instrument_id", "timestamp"],
        "time": "bar_timestamp",
        "first": "instrument_id",
    },
    "option-chain": {
        "primary_key": ["underlying_id", "quote_time", "expiry", "strike", "option_type"],
        "time": "quote_time",
        "first": "underlying_id",
    },
}
KINDS = ("valid", "missing-required", "wrong-type", "wrong-unit-or-version")
WRONG_UNIT_EXPECTATIONS = {
    "event-record": ("/$contract/profile_version", "const"),
    "factor-panel": ("/$contract/profile_version", "const"),
    "fundamental-pit": ("/schema/fields/value/unit", "const"),
    "futures-contract": ("/schema/fields/open_interest/unit", "const"),
    "holdings": ("/$contract/profile_version", "const"),
    "macro-series": ("/payload/records/0/unit", "enum"),
    "market-bar": ("/schema/fields/volume/unit", "const"),
    "option-chain": ("/$contract/profile_version", "const"),
}


def pointer(error):
    return "/" + "/".join(str(part) for part in error.absolute_path)


class BaseProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        envelope_path = ROOT / "schema" / "envelope" / "1.0.0.schema.json"
        cls.envelope = Draft202012Validator(
            json.loads(envelope_path.read_text(encoding="utf-8")),
            format_checker=FormatChecker(),
        )

    def test_index_is_globally_sorted_and_complete(self):
        index = json.loads(
            (ROOT / "schema" / "profiles" / "index.json").read_text(encoding="utf-8")
        )["profiles"]
        self.assertEqual([row["id"] for row in index], sorted(PROFILES))
        self.assertEqual(set(row["id"] for row in index), set(PROFILES))
        for row in index:
            expected = PROFILES[row["id"]]
            self.assertEqual(
                row,
                {
                    "id": row["id"],
                    "version": "1.0.0",
                    "schema": f"base/{row['id']}/1.0.0.schema.json",
                    "kind": "base",
                    "primary_key": expected["primary_key"],
                    "time_semantics": expected["time"],
                },
            )

    def test_all_32_fixture_files_are_physical_and_named(self):
        fixture_root = ROOT / "tests" / "fixtures" / "profiles"
        actual = sorted(
            path.relative_to(fixture_root).as_posix()
            for path in (fixture_root / "base").rglob("*.json")
        )
        expected = sorted(
            f"base/{profile}/{kind}.json"
            for profile in PROFILES
            for kind in KINDS
        )
        self.assertEqual(len(actual), 32)
        self.assertEqual(actual, expected)
        self.assertTrue(all((fixture_root / path).is_file() for path in actual))

    def test_table_driven_profile_fixtures(self):
        fixture_root = ROOT / "tests" / "fixtures" / "profiles" / "base"
        for profile, details in PROFILES.items():
            schema_path = ROOT / "schema" / "profiles" / "base" / profile / "1.0.0.schema.json"
            with self.subTest(profile=profile, schema="exists"):
                self.assertTrue(schema_path.is_file())
            validator = Draft202012Validator(
                json.loads(schema_path.read_text(encoding="utf-8")),
                format_checker=FormatChecker(),
            )
            for kind in KINDS:
                with self.subTest(profile=profile, fixture=kind):
                    document = json.loads(
                        (fixture_root / profile / f"{kind}.json").read_text(encoding="utf-8")
                    )

                    # Layer 1 is deliberately complete before layer 2 runs.
                    envelope_errors = list(self.envelope.iter_errors(document))
                    self.assertEqual(envelope_errors, [])
                    self.assertEqual(envelope_semantic_issues(document), [])

                    profile_errors = list(validator.iter_errors(document))
                    if kind == "valid":
                        self.assertEqual(profile_errors, [])
                        self.assertEqual(profile_semantic_issues(document), [])
                        continue

                    if kind == "missing-required":
                        expected_path, expected_validator = "/payload/records/0", "required"
                    elif kind == "wrong-type":
                        expected_path, expected_validator = (
                            f"/payload/records/0/{details['first']}",
                            "type",
                        )
                    else:
                        expected_path, expected_validator = WRONG_UNIT_EXPECTATIONS[profile]

                    self.assertTrue(
                        any(
                            pointer(error) == expected_path
                            and error.validator == expected_validator
                            for error in profile_errors
                        ),
                        [
                            (pointer(error), error.validator, error.message)
                            for error in profile_errors
                        ],
                    )

    def test_market_bar_semantic_diagnostics_are_exact_and_value_free(self):
        valid_path = (
            ROOT
            / "tests"
            / "fixtures"
            / "profiles"
            / "base"
            / "market-bar"
            / "valid.json"
        )
        valid = json.loads(valid_path.read_text(encoding="utf-8"))
        self.assertEqual(profile_semantic_issues(valid), [])

        high_low = json.loads(json.dumps(valid))
        high_low["payload"]["records"][0].update({"high": 8, "low": 9})
        issues = profile_semantic_issues(high_low)
        self.assertIn(
            {"code": "market-bar-ohlc-range", "path": "/payload/records/0"},
            issues,
        )
        self.assertTrue(all(set(issue) == {"code", "path"} for issue in issues))

        open_outside = json.loads(json.dumps(valid))
        open_outside["payload"]["records"][0]["open"] = 12
        self.assertEqual(
            profile_semantic_issues(open_outside),
            [{"code": "market-bar-open-outside-range", "path": "/payload/records/0/open"}],
        )

        close_outside = json.loads(json.dumps(valid))
        close_outside["payload"]["records"][0]["close"] = 8
        self.assertEqual(
            profile_semantic_issues(close_outside),
            [{"code": "market-bar-close-outside-range", "path": "/payload/records/0/close"}],
        )

        for untrusted in (
            None,
            [],
            {},
            {"$contract": None},
            {"$contract": []},
            {"$contract": {"profile": "market-bar"}, "payload": None},
            {"$contract": {"profile": "market-bar"}, "payload": {"records": {}}},
            {"$contract": {"profile": "market-bar"}, "payload": {"records": [None, [], {"low": "x"}]}},
        ):
            with self.subTest(untrusted=untrusted):
                self.assertEqual(profile_semantic_issues(untrusted), [])


if __name__ == "__main__":
    unittest.main()

