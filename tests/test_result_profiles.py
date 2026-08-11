import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from contract_runtime import envelope_semantic_issues, profile_semantic_issues


BASE_PROFILES = {
    "event-record": {
        "primary_key": ["event_id", "event_time", "entity_id"],
        "time": "event_time",
    },
    "factor-panel": {
        "primary_key": ["instrument_id", "timestamp", "factor_id"],
        "time": "timestamp",
    },
    "fundamental-pit": {
        "primary_key": ["instrument_id", "period_end", "available_at", "statement_scope"],
        "time": "point-in-time",
    },
    "futures-contract": {
        "primary_key": ["exchange", "contract_id", "trade_date"],
        "time": "trade_date",
    },
    "holdings": {
        "primary_key": ["portfolio_id", "instrument_id", "as_of"],
        "time": "as_of",
    },
    "macro-series": {
        "primary_key": ["series_id", "observation_date", "vintage_date"],
        "time": "vintage",
    },
    "market-bar": {
        "primary_key": ["instrument_id", "timestamp"],
        "time": "bar_timestamp",
    },
    "option-chain": {
        "primary_key": ["underlying_id", "quote_time", "expiry", "strike", "option_type"],
        "time": "quote_time",
    },
}

RESULT_PROFILES = {
    "backtest-result": {
        "primary_key": ["strategy_id", "period_start", "period_end"],
        "time": "backtest_period",
        "first": "strategy_id",
        "temporal": (("period_start", "date"), ("period_end", "date")),
    },
    "evaluation-result": {
        "primary_key": ["subject_id", "evaluated_at"],
        "time": "evaluated_at",
        "first": "subject_id",
        "temporal": (
            ("evaluated_at", "rfc3339"),
            ("sample_start", "date"),
            ("sample_end", "date"),
        ),
    },
    "execution-plan": {
        "primary_key": ["portfolio_id", "as_of"],
        "time": "as_of",
        "first": "portfolio_id",
        "temporal": (("as_of", "rfc3339"),),
    },
    "model-artifact": {
        "primary_key": ["model_id", "training_cutoff"],
        "time": "training_cutoff",
        "first": "model_id",
        "temporal": (("training_cutoff", "rfc3339"),),
    },
    "portfolio-target": {
        "primary_key": ["portfolio_id", "as_of"],
        "time": "as_of",
        "first": "portfolio_id",
        "temporal": (("as_of", "rfc3339"),),
    },
    "ranked-factor-set": {
        "primary_key": ["set_id", "factor_id"],
        "time": "as_of",
        "first": "set_id",
        "temporal": (("as_of", "rfc3339"),),
    },
    "report-artifact": {
        "primary_key": ["report_id", "as_of"],
        "time": "as_of",
        "first": "report_id",
        "temporal": (("as_of", "rfc3339"),),
    },
    "risk-result": {
        "primary_key": ["subject_id", "as_of"],
        "time": "as_of",
        "first": "subject_id",
        "temporal": (("as_of", "rfc3339"),),
    },
}


def pointer(error):
    return "/" + "/".join(str(part) for part in error.absolute_path)


def fixture(profile, kind="valid"):
    return json.loads(
        (
            ROOT
            / "tests"
            / "fixtures"
            / "profiles"
            / "result"
            / profile
            / f"{kind}.json"
        ).read_text(encoding="utf-8")
    )


class ResultProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        envelope_path = ROOT / "schema" / "envelope" / "1.0.0.schema.json"
        cls.envelope = Draft202012Validator(
            json.loads(envelope_path.read_text(encoding="utf-8")),
            format_checker=FormatChecker(),
        )

    def test_all_16_fixture_files_are_physical_and_named(self):
        fixture_root = ROOT / "tests" / "fixtures" / "profiles" / "result"
        actual = sorted(path.relative_to(fixture_root).as_posix() for path in fixture_root.rglob("*.json"))
        expected = sorted(
            f"{profile}/{kind}.json"
            for profile in RESULT_PROFILES
            for kind in ("valid", "missing-required")
        )
        self.assertEqual(len(actual), 16)
        self.assertEqual(actual, expected)
        self.assertTrue(all((fixture_root / path).is_file() for path in actual))

    def test_index_preserves_base_and_is_globally_sorted(self):
        index = json.loads(
            (ROOT / "schema" / "profiles" / "index.json").read_text(encoding="utf-8")
        )["profiles"]
        self.assertEqual(len(index), 16)
        ids = [row["id"] for row in index]
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({row["kind"] for row in index if row["id"] in BASE_PROFILES}, {"base"})
        self.assertEqual({row["kind"] for row in index if row["id"] in RESULT_PROFILES}, {"result"})
        for profile, details in {**BASE_PROFILES, **RESULT_PROFILES}.items():
            row = next(item for item in index if item["id"] == profile)
            kind = "base" if profile in BASE_PROFILES else "result"
            self.assertEqual(
                row,
                {
                    "id": profile,
                    "version": "1.0.0",
                    "schema": f"{kind}/{profile}/1.0.0.schema.json",
                    "kind": kind,
                    "primary_key": details["primary_key"],
                    "time_semantics": details["time"],
                },
            )

    def test_table_driven_result_fixtures(self):
        fixture_root = ROOT / "tests" / "fixtures" / "profiles" / "result"
        for profile, details in RESULT_PROFILES.items():
            schema_path = ROOT / "schema" / "profiles" / "result" / profile / "1.0.0.schema.json"
            with self.subTest(profile=profile, schema="exists"):
                self.assertTrue(schema_path.is_file())
            if not schema_path.is_file():
                continue
            validator = Draft202012Validator(
                json.loads(schema_path.read_text(encoding="utf-8")),
                format_checker=FormatChecker(),
            )
            for kind in ("valid", "missing-required"):
                with self.subTest(profile=profile, fixture=kind):
                    document = json.loads((fixture_root / profile / f"{kind}.json").read_text(encoding="utf-8"))
                    # Layer 1 is deliberately complete before layer 2 runs.
                    self.assertEqual(list(self.envelope.iter_errors(document)), [])
                    self.assertEqual(envelope_semantic_issues(document), [])
                    errors = list(validator.iter_errors(document))
                    if kind == "valid":
                        self.assertEqual(errors, [])
                        self.assertEqual(profile_semantic_issues(document), [])
                    else:
                        self.assertTrue(
                            any(
                                pointer(error) == "/payload/records/0" and error.validator == "required"
                                for error in errors
                            ),
                            [(pointer(error), error.validator, error.message) for error in errors],
                        )

    def test_result_lineage_is_closed_and_strict(self):
        schema_path = ROOT / "schema" / "profiles" / "result" / "evaluation-result" / "1.0.0.schema.json"
        if not schema_path.is_file():
            self.skipTest("result schemas are not implemented yet")
        validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
        source = fixture("evaluation-result")
        cases = (
            ("profile", "bad profile", "pattern", "/payload/records/0/lineage/sources/0/profile"),
            ("version", "1.0", "pattern", "/payload/records/0/lineage/sources/0/version"),
            ("artifact_ref", "", "minLength", "/payload/records/0/lineage/sources/0/artifact_ref"),
            ("sha256", "sha256:" + "0" * 64 + "\n", "pattern", "/payload/records/0/lineage/sources/0/sha256"),
            ("evidence_refs", [""], "minLength", "/payload/records/0/lineage/evidence_refs/0"),
        )
        for field, value, validator_name, expected_path in cases:
            document = json.loads(json.dumps(source))
            if field == "evidence_refs":
                document["payload"]["records"][0]["lineage"][field] = value
            else:
                document["payload"]["records"][0]["lineage"]["sources"][0][field] = value
            errors = list(validator.iter_errors(document))
            self.assertTrue(
                any(pointer(error) == expected_path and error.validator == validator_name for error in errors),
                [(pointer(error), error.validator, error.message) for error in errors],
            )

        document = fixture("evaluation-result")
        document["payload"]["records"][0]["lineage"]["extra"] = True
        errors = list(validator.iter_errors(document))
        self.assertTrue(any(pointer(error) == "/payload/records/0/lineage" and error.validator == "additionalProperties" for error in errors))

    def test_result_lineage_version_syntax_is_exact_for_every_schema(self):
        invalid_versions = ("01.0.0", "1.0.0-.", "1.0.0-a..b", "1.0.0\n")
        for profile in RESULT_PROFILES:
            schema_path = ROOT / "schema" / "profiles" / "result" / profile / "1.0.0.schema.json"
            validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
            for version in invalid_versions:
                with self.subTest(profile=profile, version=repr(version)):
                    document = fixture(profile)
                    document["payload"]["records"][0]["lineage"]["sources"][0]["version"] = version
                    self.assertTrue(
                        any(
                            pointer(error) == "/payload/records/0/lineage/sources/0/version"
                            and error.validator == "pattern"
                            for error in validator.iter_errors(document)
                        )
                    )

    def test_result_schema_fields_are_closed(self):
        for profile in RESULT_PROFILES:
            with self.subTest(profile=profile):
                schema_path = ROOT / "schema" / "profiles" / "result" / profile / "1.0.0.schema.json"
                validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
                document = fixture(profile)
                document["schema"]["fields"]["ghost"] = {"type": "string", "nullable": False}
                self.assertTrue(
                    any(
                        pointer(error) == "/schema/fields" and error.validator == "additionalProperties"
                        for error in validator.iter_errors(document)
                    )
                )

    def test_portfolio_target_weights_and_cash_are_unbounded_numbers(self):
        schema_path = ROOT / "schema" / "profiles" / "result" / "portfolio-target" / "1.0.0.schema.json"
        validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
        document = fixture("portfolio-target")
        record = document["payload"]["records"][0]
        record["target_weights"] = {"SYNTH-001": -2.0, "SYNTH-002": 3.0}
        record["cash_target"] = -0.5
        self.assertEqual(list(validator.iter_errors(document)), [])
        record["target_weights"]["SYNTH-003"] = float("nan")
        self.assertEqual(
            profile_semantic_issues(document),
            [{"code": "profile-finite", "path": "/payload/records/0/target_weights/SYNTH-003"}],
        )

    def test_execution_plan_allows_empty_orders_but_requires_positive_quantity(self):
        schema_path = ROOT / "schema" / "profiles" / "result" / "execution-plan" / "1.0.0.schema.json"
        validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
        document = fixture("execution-plan")
        document["payload"]["records"][0]["simulated_orders"] = []
        self.assertEqual(list(validator.iter_errors(document)), [])
        document = fixture("execution-plan")
        document["payload"]["records"][0]["simulated_orders"][0]["quantity"] = 0
        errors = list(validator.iter_errors(document))
        self.assertTrue(
            any(
                pointer(error) == "/payload/records/0/simulated_orders/0/quantity"
                and error.validator == "exclusiveMinimum"
                for error in errors
            ),
            [(pointer(error), error.validator, error.message) for error in errors],
        )

    def test_result_meta_currency_is_optional_except_backtest(self):
        for profile in RESULT_PROFILES:
            with self.subTest(profile=profile):
                schema_path = ROOT / "schema" / "profiles" / "result" / profile / "1.0.0.schema.json"
                validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
                document = fixture(profile)
                document["meta"].pop("currency")
                errors = list(validator.iter_errors(document))
                if profile == "backtest-result":
                    self.assertTrue(
                        any(pointer(error) == "/meta" and error.validator == "required" for error in errors),
                        [(pointer(error), error.validator, error.message) for error in errors],
                    )
                else:
                    self.assertEqual(errors, [])

    def test_result_periods_are_ordered_after_strict_dates(self):
        backtest = fixture("backtest-result")
        backtest["payload"]["records"][0].update({"period_start": "2026-06-30", "period_end": "2026-01-01"})
        self.assertEqual(
            profile_semantic_issues(backtest),
            [{"code": "backtest-result-period-order", "path": "/payload/records/0/period_end"}],
        )
        backtest["payload"]["records"][0]["period_end"] = "2026-06-30"
        self.assertEqual(profile_semantic_issues(backtest), [])
        backtest["payload"]["records"][0]["period_start"] = []
        self.assertEqual(profile_semantic_issues(backtest), [])

        evaluation = fixture("evaluation-result")
        evaluation["payload"]["records"][0].update({"sample_start": "2026-06-30", "sample_end": "2026-01-01"})
        self.assertEqual(
            profile_semantic_issues(evaluation),
            [{"code": "evaluation-result-sample-order", "path": "/payload/records/0/sample_end"}],
        )
        evaluation["payload"]["records"][0]["sample_end"] = "2026-06-30"
        self.assertEqual(profile_semantic_issues(evaluation), [])

    def test_result_lineage_arrays_reject_duplicates_for_every_schema(self):
        for profile in RESULT_PROFILES:
            schema_path = ROOT / "schema" / "profiles" / "result" / profile / "1.0.0.schema.json"
            validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
            for field, path in (
                ("sources", "/payload/records/0/lineage/sources"),
                ("evidence_refs", "/payload/records/0/lineage/evidence_refs"),
            ):
                with self.subTest(profile=profile, field=field):
                    document = fixture(profile)
                    lineage = document["payload"]["records"][0]["lineage"]
                    lineage[field].append(json.loads(json.dumps(lineage[field][0])))
                    errors = list(validator.iter_errors(document))
                    self.assertTrue(
                        any(pointer(error) == path and error.validator == "uniqueItems" for error in errors),
                        [(pointer(error), error.validator, error.message) for error in errors],
                    )

    def test_execution_plan_forbids_live_submission(self):
        schema_path = ROOT / "schema" / "profiles" / "result" / "execution-plan" / "1.0.0.schema.json"
        if not schema_path.is_file():
            self.skipTest("result schemas are not implemented yet")
        validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")))
        document = fixture("execution-plan")
        document["payload"]["records"][0]["live_submission_allowed"] = True
        errors = list(validator.iter_errors(document))
        self.assertTrue(
            any(
                pointer(error) == "/payload/records/0/live_submission_allowed" and error.validator == "const"
                for error in errors
            ),
            [(pointer(error), error.validator, error.message) for error in errors],
        )
        document = fixture("execution-plan")
        document["payload"]["records"][0]["broker"] = "live"
        errors = list(validator.iter_errors(document))
        self.assertTrue(any(pointer(error) == "/payload/records/0" and error.validator == "additionalProperties" for error in errors))

    def test_result_temporal_semantics_are_strict_and_value_free(self):
        for profile, details in RESULT_PROFILES.items():
            for field, kind in details["temporal"]:
                with self.subTest(profile=profile, field=field):
                    document = fixture(profile)
                    document["payload"]["records"][0][field] = "not-a-dateZ" if kind == "rfc3339" else "2026-02-30"
                    path = f"/payload/records/0/{field}"
                    self.assertEqual(profile_semantic_issues(document), [{"code": f"profile-{kind}", "path": path}])
                    valid_values = (
                        ("2026-08-10T09:30:00Z", "2026-08-10T17:30:00+08:00")
                        if kind == "rfc3339"
                        else ("2026-08-10",)
                    )
                    for valid in valid_values:
                        document["payload"]["records"][0][field] = valid
                        self.assertFalse(any(issue["path"] == path for issue in profile_semantic_issues(document)))
                    if kind == "rfc3339":
                        document["payload"]["records"][0][field] = "2026-08-10T09:30:00+99:99"
                        self.assertEqual(profile_semantic_issues(document), [{"code": "profile-rfc3339", "path": path}])

    def test_result_nested_non_finite_numbers_are_deterministic(self):
        source = fixture("evaluation-result")
        left = json.loads(json.dumps(source))
        left["payload"]["records"][0]["metrics"] = {"z_extra": float("inf"), "a_extra": float("nan"), "nested": [float("-inf")]}
        right = json.loads(json.dumps(source))
        right["payload"]["records"][0]["metrics"] = {"nested": [float("-inf")], "a_extra": float("nan"), "z_extra": float("inf")}
        expected = [
            {"code": "profile-finite", "path": "/payload/records/0/metrics/a_extra"},
            {"code": "profile-finite", "path": "/payload/records/0/metrics/nested/0"},
            {"code": "profile-finite", "path": "/payload/records/0/metrics/z_extra"},
        ]
        self.assertEqual(profile_semantic_issues(left), expected)
        self.assertEqual(profile_semantic_issues(left), profile_semantic_issues(right))

    def test_result_nested_non_finite_paths_escape_pointer_tokens(self):
        left = fixture("evaluation-result")
        left["payload"]["records"][0]["metrics"] = {"x~y": float("inf"), "a/b": float("nan")}
        right = fixture("evaluation-result")
        right["payload"]["records"][0]["metrics"] = {"a/b": float("nan"), "x~y": float("inf")}
        expected = [
            {"code": "profile-finite", "path": "/payload/records/0/metrics/a~1b"},
            {"code": "profile-finite", "path": "/payload/records/0/metrics/x~0y"},
        ]
        self.assertEqual(profile_semantic_issues(left), expected)
        self.assertEqual(profile_semantic_issues(left), profile_semantic_issues(right))

    def test_result_temporal_schema_rejects_terminal_newlines(self):
        for profile, details in RESULT_PROFILES.items():
            schema_path = ROOT / "schema" / "profiles" / "result" / profile / "1.0.0.schema.json"
            if not schema_path.is_file():
                continue
            validator = Draft202012Validator(json.loads(schema_path.read_text(encoding="utf-8")), format_checker=FormatChecker())
            document = fixture(profile)
            for field, _kind in details["temporal"]:
                with self.subTest(profile=profile, field=field):
                    document["payload"]["records"][0][field] += "\n"
                    path = f"/payload/records/0/{field}"
                    errors = list(validator.iter_errors(document))
                    self.assertTrue(any(pointer(error) == path for error in errors), [(pointer(error), error.validator) for error in errors])
                    document["payload"]["records"][0][field] = document["payload"]["records"][0][field].rstrip("\n")

    def test_profile_semantics_tolerate_malformed_result_containers(self):
        for document in (
            None,
            [],
            {},
            {"$contract": None},
            {"$contract": []},
            {"$contract": {"profile": "evaluation-result"}, "payload": None},
            {"$contract": {"profile": "evaluation-result"}, "payload": {"records": {}}},
            {"$contract": {"profile": "evaluation-result"}, "payload": {"records": [None, [], {"evaluated_at": {}}]}},
        ):
            with self.subTest(document=document):
                self.assertEqual(profile_semantic_issues(document), [])


if __name__ == "__main__":
    unittest.main()
