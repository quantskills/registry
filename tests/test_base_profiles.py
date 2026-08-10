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
    "market-bar": ("/schema/fields/volume/unit", "enum"),
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

    def test_profile_temporal_semantics_are_strict_and_value_free(self):
        temporal = {
            "event-record": (("event_time", "rfc3339"), ("published_at", "rfc3339")),
            "factor-panel": (("timestamp", "rfc3339"),),
            "fundamental-pit": (("period_end", "date"), ("available_at", "rfc3339")),
            "futures-contract": (("trade_date", "date"), ("expiry", "date")),
            "holdings": (("as_of", "rfc3339"),),
            "macro-series": (("observation_date", "date"), ("vintage_date", "date")),
            "market-bar": (("timestamp", "rfc3339"),),
            "option-chain": (("quote_time", "rfc3339"), ("expiry", "date")),
        }
        for profile, fields in temporal.items():
            for field, kind in fields:
                with self.subTest(profile=profile, field=field):
                    document = json.loads(
                        (
                            ROOT
                            / "tests"
                            / "fixtures"
                            / "profiles"
                            / "base"
                            / profile
                            / "valid.json"
                        ).read_text(encoding="utf-8")
                    )
                    document["payload"]["records"][0][field] = (
                        "not-a-dateZ" if kind == "rfc3339" else "2026-02-30"
                    )
                    path = f"/payload/records/0/{field}"
                    self.assertEqual(
                        profile_semantic_issues(document),
                        [{"code": f"profile-{kind}", "path": path}],
                    )
                    for valid in (
                        ("2026-08-10T09:30:00Z", "2026-08-10T17:30:00+08:00")
                        if kind == "rfc3339"
                        else ("2026-08-10",)
                    ):
                        document["payload"]["records"][0][field] = valid
                        self.assertFalse(
                            any(issue["path"] == path for issue in profile_semantic_issues(document))
                        )
                    if kind == "rfc3339":
                        document["payload"]["records"][0][field] = "2026-08-10T09:30:00+99:99"
                        self.assertEqual(
                            profile_semantic_issues(document),
                            [{"code": "profile-rfc3339", "path": path}],
                        )

        for untrusted in (
            {"$contract": {"profile": []}, "payload": {"records": []}},
            {"$contract": {"profile": {}}, "payload": {"records": []}},
            {"$contract": {"profile": "event-record"}, "payload": {"records": [None, [], "x"]}},
            {"$contract": {"profile": "market-bar"}, "payload": {"records": [{"timestamp": {"x": 1}}]}},
            {"$contract": {"profile": "option-chain"}, "payload": {"records": {"0": {}}}},
        ):
            with self.subTest(untrusted=untrusted):
                self.assertEqual(profile_semantic_issues(untrusted), [])

    def test_profile_semantics_reject_non_finite_numbers_without_values(self):
        numeric_fields = {
            "factor-panel": "value",
            "fundamental-pit": "value",
            "futures-contract": "settlement",
            "holdings": "quantity",
            "macro-series": "value",
            "market-bar": "open",
            "option-chain": "strike",
        }
        for profile, field in numeric_fields.items():
            for value in (float("nan"), float("inf"), float("-inf")):
                with self.subTest(profile=profile, field=field, value=value):
                    document = json.loads(
                        (
                            ROOT
                            / "tests"
                            / "fixtures"
                            / "profiles"
                            / "base"
                            / profile
                            / "valid.json"
                        ).read_text(encoding="utf-8")
                    )
                    document["payload"]["records"][0][field] = value
                    path = f"/payload/records/0/{field}"
                    self.assertEqual(
                        profile_semantic_issues(document),
                        [{"code": "profile-finite", "path": path}],
                    )

        document = json.loads(
            (
                ROOT
                / "tests"
                / "fixtures"
                / "profiles"
                / "base"
                / "market-bar"
                / "valid.json"
            ).read_text(encoding="utf-8")
        )
        document["payload"]["records"][0]["open"] = float("nan")
        self.assertEqual(
            profile_semantic_issues(document),
            [{"code": "profile-finite", "path": "/payload/records/0/open"}],
        )
        document["payload"]["records"][0]["open"] = True
        self.assertEqual(profile_semantic_issues(document), [])
        document["payload"]["records"][0]["open"] = "not-a-number"
        self.assertEqual(profile_semantic_issues(document), [])

    def test_profile_terminal_newlines_are_rejected_at_exact_paths(self):
        temporal = {
            "event-record": ("event_time", "published_at"),
            "factor-panel": ("timestamp",),
            "fundamental-pit": ("period_end", "available_at"),
            "futures-contract": ("trade_date", "expiry"),
            "holdings": ("as_of",),
            "macro-series": ("observation_date", "vintage_date"),
            "market-bar": ("timestamp",),
            "option-chain": ("quote_time", "expiry"),
        }
        for profile, fields in temporal.items():
            schema_path = ROOT / "schema" / "profiles" / "base" / profile / "1.0.0.schema.json"
            validator = Draft202012Validator(
                json.loads(schema_path.read_text(encoding="utf-8")),
                format_checker=FormatChecker(),
            )
            document = json.loads(
                (
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "profiles"
                    / "base"
                    / profile
                    / "valid.json"
                ).read_text(encoding="utf-8")
            )
            for field in fields:
                with self.subTest(profile=profile, field=field):
                    document["payload"]["records"][0][field] += "\n"
                    errors = list(validator.iter_errors(document))
                    path = f"/payload/records/0/{field}"
                    self.assertTrue(
                        any(pointer(error) == path for error in errors),
                        [(pointer(error), error.validator) for error in errors],
                    )
                    document["payload"]["records"][0][field] = document["payload"]["records"][0][field].rstrip("\n")

    def test_profile_units_currencies_and_null_policy(self):
        currency_profiles = ("market-bar", "futures-contract", "option-chain")
        for profile in currency_profiles:
            schema_path = ROOT / "schema" / "profiles" / "base" / profile / "1.0.0.schema.json"
            validator = Draft202012Validator(
                json.loads(schema_path.read_text(encoding="utf-8")),
                format_checker=FormatChecker(),
            )
            document = json.loads(
                (
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "profiles"
                    / "base"
                    / profile
                    / "valid.json"
                ).read_text(encoding="utf-8")
            )
            for code in ("USD", "HKD"):
                document["meta"]["currency"] = code
                self.assertEqual(list(validator.iter_errors(document)), [])
            document["meta"]["currency"] = "US$"
            self.assertTrue(
                any(pointer(error) == "/meta/currency" for error in validator.iter_errors(document))
            )
            document["meta"].pop("currency")
            self.assertTrue(
                any(pointer(error) == "/meta" for error in validator.iter_errors(document))
            )

        for profile, field in (
            ("market-bar", "open"),
            ("futures-contract", "settlement"),
            ("holdings", "cost"),
            ("holdings", "portfolio_nav"),
            ("option-chain", "strike"),
            ("option-chain", "bid"),
            ("option-chain", "ask"),
        ):
            document = json.loads(
                (
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "profiles"
                    / "base"
                    / profile
                    / "valid.json"
                ).read_text(encoding="utf-8")
            )
            document["schema"]["fields"][field]["unit"] = "USD"
            validator = Draft202012Validator(
                json.loads(
                    (
                        ROOT
                        / "schema"
                        / "profiles"
                        / "base"
                        / profile
                        / "1.0.0.schema.json"
                    ).read_text(encoding="utf-8")
                )
            )
            self.assertTrue(
                any(
                    pointer(error) == f"/schema/fields/{field}/unit"
                    for error in validator.iter_errors(document)
                )
            )

        factor = json.loads(
            (
                ROOT
                / "tests"
                / "fixtures"
                / "profiles"
                / "base"
                / "factor-panel"
                / "valid.json"
            ).read_text(encoding="utf-8")
        )
        factor["payload"]["records"][0]["value"] = None
        factor["payload"]["records"][0]["missing_policy"] = "keep-null"
        factor_validator = Draft202012Validator(
            json.loads(
                (
                    ROOT
                    / "schema"
                    / "profiles"
                    / "base"
                    / "factor-panel"
                    / "1.0.0.schema.json"
                ).read_text(encoding="utf-8")
            )
        )
        self.assertEqual(list(factor_validator.iter_errors(factor)), [])
        self.assertEqual(profile_semantic_issues(factor), [])
        factor["payload"]["records"][0]["missing_policy"] = "exclude"
        self.assertTrue(
            any(
                pointer(error) == "/payload/records/0/missing_policy"
                for error in factor_validator.iter_errors(factor)
            )
        )
        self.assertEqual(
            profile_semantic_issues(factor),
            [{"code": "factor-panel-nullability", "path": "/payload/records/0/value"}],
        )
        factor["payload"]["records"][0]["value"] = 1.25
        factor["payload"]["records"][0]["missing_policy"] = "keep-null"
        self.assertEqual(list(factor_validator.iter_errors(factor)), [])
        self.assertEqual(profile_semantic_issues(factor), [])

    def test_macro_units_match_descriptors_and_currency_codes_are_exact(self):
        macro_path = (
            ROOT
            / "tests"
            / "fixtures"
            / "profiles"
            / "base"
            / "macro-series"
            / "valid.json"
        )
        document = json.loads(macro_path.read_text(encoding="utf-8"))
        document["schema"]["fields"]["value"]["unit"] = "percent"
        document["payload"]["records"][0]["unit"] = "index"
        self.assertEqual(
            profile_semantic_issues(document),
            [{"code": "macro-series-unit", "path": "/payload/records/0/unit"}],
        )

        document["payload"]["records"][0]["unit"] = "percent"
        self.assertEqual(profile_semantic_issues(document), [])
        document["schema"]["fields"]["value"]["unit"] = "currency"
        document["payload"]["records"][0]["unit"] = "currency"
        document["meta"]["currency"] = "USD"
        self.assertEqual(profile_semantic_issues(document), [])
        document["meta"]["currency"] = "US$"
        self.assertEqual(
            profile_semantic_issues(document),
            [{"code": "macro-series-currency", "path": "/meta/currency"}],
        )
        document["meta"]["currency"] = "HKD"
        self.assertEqual(profile_semantic_issues(document), [])

    def test_controlled_units_and_record_currency_codes_accept_usd_hkd(self):
        cases = (
            ("market-bar", "volume", "lots"),
            ("holdings", "quantity", "contracts"),
            ("option-chain", "contract_multiplier", "units"),
        )
        for profile, field, unit in cases:
            with self.subTest(profile=profile, field=field):
                document = json.loads(
                    (
                        ROOT
                        / "tests"
                        / "fixtures"
                        / "profiles"
                        / "base"
                        / profile
                        / "valid.json"
                    ).read_text(encoding="utf-8")
                )
                document["schema"]["fields"][field]["unit"] = unit
                validator = Draft202012Validator(
                    json.loads(
                        (
                            ROOT
                            / "schema"
                            / "profiles"
                            / "base"
                            / profile
                            / "1.0.0.schema.json"
                        ).read_text(encoding="utf-8")
                    )
                )
                self.assertEqual(list(validator.iter_errors(document)), [])

        for profile in ("fundamental-pit", "holdings"):
            document = json.loads(
                (
                    ROOT
                    / "tests"
                    / "fixtures"
                    / "profiles"
                    / "base"
                    / profile
                    / "valid.json"
                ).read_text(encoding="utf-8")
            )
            validator = Draft202012Validator(
                json.loads(
                    (
                        ROOT
                        / "schema"
                        / "profiles"
                        / "base"
                        / profile
                        / "1.0.0.schema.json"
                    ).read_text(encoding="utf-8")
                )
            )
            for code in ("USD", "HKD"):
                document["payload"]["records"][0]["currency"] = code
                self.assertEqual(list(validator.iter_errors(document)), [])
            document["payload"]["records"][0]["currency"] = "US$"
            self.assertTrue(
                any(
                    pointer(error) == "/payload/records/0/currency"
                    for error in validator.iter_errors(document)
                )
            )

    def test_relaxed_signed_domain_values_remain_schema_valid(self):
        cases = (
            ("market-bar", {"open": -1, "high": 1, "low": -2, "close": 0}),
            ("futures-contract", {"settlement": -1}),
            ("holdings", {"quantity": -1, "weight": -2}),
        )
        for profile, updates in cases:
            with self.subTest(profile=profile):
                document = json.loads(
                    (
                        ROOT
                        / "tests"
                        / "fixtures"
                        / "profiles"
                        / "base"
                        / profile
                        / "valid.json"
                    ).read_text(encoding="utf-8")
                )
                document["payload"]["records"][0].update(updates)
                validator = Draft202012Validator(
                    json.loads(
                        (
                            ROOT
                            / "schema"
                            / "profiles"
                            / "base"
                            / profile
                            / "1.0.0.schema.json"
                        ).read_text(encoding="utf-8")
                    )
                )
                self.assertEqual(list(validator.iter_errors(document)), [])


if __name__ == "__main__":
    unittest.main()
