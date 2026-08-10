import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from validate_contract import _canonical_diagnostics, load_profile_index, resolve_profile, validate_contract


def read_fixture(relative):
    return json.loads((ROOT / "tests" / "fixtures" / relative).read_text(encoding="utf-8"))


def run_cli(path, *args, cwd=ROOT):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "validate_contract.py"), str(path), *args],
        cwd=cwd,
        text=True,
        capture_output=True,
    )


class ContractRuntimeTests(unittest.TestCase):
    def test_package_import_is_supported(self):
        completed = subprocess.run(
            [sys.executable, "-B", "-c", "from scripts.validate_contract import validate_contract"],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_library_api_and_exact_profile_resolution(self):
        index = load_profile_index(ROOT)
        self.assertEqual(
            resolve_profile("market-bar", "1.0.0", index),
            Path("base/market-bar/1.0.0.schema.json"),
        )
        self.assertIsNone(resolve_profile("market-bar", "1.0.1", index))
        self.assertIsNone(resolve_profile("missing", "1.0.0", index))
        self.assertIsNone(
            resolve_profile(
                "market-bar",
                "1.0.0",
                {"profiles": [{"id": "market-bar", "version": "1.0.0", "kind": "result", "schema": "base/market-bar/1.0.0.schema.json"}]},
            )
        )

    def test_canonical_diagnostics_deduplicate_identical_entries(self):
        duplicate = {"layer": "profile", "code": "type", "path": "/payload/\ud800"}
        self.assertEqual(_canonical_diagnostics([duplicate, dict(duplicate)]), [duplicate])

    def test_valid_base_and_result_documents(self):
        for relative, profile in (
            ("profiles/base/market-bar/valid.json", "market-bar"),
            ("profiles/result/evaluation-result/valid.json", "evaluation-result"),
        ):
            with self.subTest(profile=profile):
                result = validate_contract(read_fixture(relative), ROOT)
                self.assertEqual(
                    result,
                    {
                        "status": "valid",
                        "envelope": {"name": "quantskills-envelope", "version": "1.0.0"},
                        "profile": {"id": profile, "version": "1.0.0"},
                        "errors": [],
                        "warnings": [],
                    },
                )

    def test_envelope_layer_precedes_profile_layer(self):
        document = read_fixture("profiles/base/market-bar/valid.json")
        document["meta"]["generated_at"] = "not-a-date"
        document["payload"]["records"][0]["open"] = "wrong-type"
        result = validate_contract(document, ROOT)
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(result["errors"])
        self.assertTrue(all(error["layer"] == "envelope" for error in result["errors"]))
        self.assertFalse(any(error["path"].startswith("/payload") for error in result["errors"]))

        document = read_fixture("profiles/base/market-bar/valid.json")
        document["schema"]["fields"]["volume"]["unit"] = "bad-unit"
        result = validate_contract(document, ROOT)
        self.assertEqual(result["errors"], [{"layer": "profile", "code": "enum", "path": "/schema/fields/volume/unit"}])

    def test_root_schema_diagnostic_uses_empty_rfc6901_pointer(self):
        document = read_fixture("profiles/base/market-bar/valid.json")
        document["extra"] = True
        result = validate_contract(document, ROOT)
        self.assertEqual(
            result["errors"],
            [{"layer": "envelope", "code": "additionalProperties", "path": ""}],
        )

    def test_semantic_diagnostics_are_value_free_and_profile_scoped(self):
        market = read_fixture("profiles/base/market-bar/valid.json")
        market["payload"]["records"][0].update({"high": 1, "low": 2})
        result = validate_contract(market, ROOT)
        self.assertIn(
            {"layer": "profile", "code": "market-bar-ohlc-range", "path": "/payload/records/0"},
            result["errors"],
        )

        evaluation = read_fixture("profiles/result/evaluation-result/valid.json")
        evaluation["payload"]["records"][0]["metrics"] = {"z": float("inf"), "a/b": float("nan")}
        result = validate_contract(evaluation, ROOT)
        self.assertEqual(
            result["errors"],
            [
                {"layer": "profile", "code": "profile-finite", "path": "/payload/records/0/metrics/a~1b"},
                {"layer": "profile", "code": "profile-finite", "path": "/payload/records/0/metrics/z"},
            ],
        )

        evaluation["payload"]["records"][0].update({"sample_start": "2026-06-30", "sample_end": "2026-01-01"})
        result = validate_contract(evaluation, ROOT)
        self.assertIn(
            {"layer": "profile", "code": "evaluation-result-sample-order", "path": "/payload/records/0/sample_end"},
            result["errors"],
        )
        self.assertTrue(all(set(error) == {"layer", "code", "path"} for error in result["errors"]))

    def test_schema_errors_are_stable_deduplicated_and_value_free(self):
        source = read_fixture("profiles/result/evaluation-result/valid.json")
        first = json.loads(json.dumps(source))
        first["payload"]["records"][0].pop("subject_id")
        first["schema"]["fields"]["ghost"] = {"type": "string", "nullable": False}
        second = json.loads(json.dumps(source))
        second["schema"]["fields"] = {"ghost": {"type": "string", "nullable": False}, **second["schema"]["fields"]}
        second["payload"]["records"][0].pop("subject_id")
        result_one = validate_contract(first, ROOT)
        result_two = validate_contract(second, ROOT)
        self.assertEqual(result_one, result_two)
        self.assertEqual(
            result_one["errors"],
            [
                {"layer": "profile", "code": "additionalProperties", "path": "/schema/fields"},
                {"layer": "profile", "code": "required", "path": "/payload/records/0"},
            ],
        )

    def test_unknown_or_malformed_identity_never_falls_back(self):
        cases = (
            ("envelope", "name", "other-envelope", "/$contract/envelope"),
            ("envelope", "version", "1.0.1", "/$contract/envelope_version"),
            ("profile", "id", "market-bar\n", "/$contract/profile"),
            ("profile", "version", "1.0.1", "/$contract/profile_version"),
        )
        for kind, field, value, path in cases:
            with self.subTest(kind=kind, field=field):
                document = read_fixture("profiles/base/market-bar/valid.json")
                contract = document["$contract"]
                contract["envelope" if kind == "envelope" and field == "name" else "envelope_version" if kind == "envelope" else "profile" if field == "id" else "profile_version"] = value
                result = validate_contract(document, ROOT)
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(result["errors"][0]["path"], path)

        document = read_fixture("profiles/base/market-bar/valid.json")
        document["$contract"] = []
        result = validate_contract(document, ROOT)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["profile"], None)

    def test_path_escape_is_rejected(self):
        document = read_fixture("profiles/base/market-bar/valid.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "schema" / "envelope").mkdir(parents=True)
            (root / "schema" / "profiles").mkdir(parents=True)
            shutil.copy2(ROOT / "schema" / "envelope" / "index.json", root / "schema" / "envelope" / "index.json")
            shutil.copy2(ROOT / "schema" / "envelope" / "1.0.0.schema.json", root / "schema" / "envelope" / "1.0.0.schema.json")
            (root / "schema" / "profiles" / "index.json").write_text(
                json.dumps({"profiles": [{"id": "market-bar", "version": "1.0.0", "schema": "../escape.json", "kind": "base"}]}),
                encoding="utf-8",
            )
            result = validate_contract(document, root)
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["errors"][0]["code"], "profile-index")

    def test_malformed_profile_indexes_fail_closed(self):
        base_row = {
            "id": "market-bar",
            "version": "1.0.0",
            "schema": "base/market-bar/1.0.0.schema.json",
            "kind": "base",
        }
        cases = (
            ("duplicate", [base_row, dict(base_row)]),
            ("profile", [{**base_row, "id": "market-bar\n"}]),
            ("version", [{**base_row, "version": "01.0.0"}]),
            ("kind", [{**base_row, "kind": "unknown"}]),
        )
        document = read_fixture("profiles/base/market-bar/valid.json")
        for label, rows in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "schema" / "envelope").mkdir(parents=True)
                (root / "schema" / "profiles").mkdir(parents=True)
                shutil.copy2(ROOT / "schema" / "envelope" / "index.json", root / "schema" / "envelope" / "index.json")
                shutil.copy2(ROOT / "schema" / "envelope" / "1.0.0.schema.json", root / "schema" / "envelope" / "1.0.0.schema.json")
                (root / "schema" / "profiles" / "index.json").write_text(json.dumps({"profiles": rows}), encoding="utf-8")
                result = validate_contract(document, root)
                self.assertEqual(result["status"], "unknown")
                self.assertEqual(result["errors"], [{"layer": "profile", "code": "profile-index", "path": "/schema/profiles/index.json"}])

    def test_unknown_identity_and_duplicate_indexes_are_redacted_and_fail_closed(self):
        document = read_fixture("profiles/base/market-bar/valid.json")
        document["$contract"]["envelope_version"] = "01.0.0"
        result = validate_contract(document, ROOT)
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["envelope"])
        self.assertIsNone(result["profile"])

        document = read_fixture("profiles/base/market-bar/valid.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "schema" / "envelope").mkdir(parents=True)
            (root / "schema" / "profiles").mkdir(parents=True)
            (root / "schema" / "envelope" / "index.json").write_text(
                '{"name":"quantskills-envelope","name":"other","versions":{"1.0.0":"1.0.0.schema.json"}}',
                encoding="utf-8",
            )
            result = validate_contract(document, root)
            self.assertEqual(result["status"], "unknown")
            self.assertIsNone(result["envelope"])
            self.assertIsNone(result["profile"])
            self.assertEqual(result["errors"], [{"layer": "envelope", "code": "envelope-index", "path": "/schema/envelope/index.json"}])

    def test_envelope_index_requires_exact_safe_structure(self):
        document = read_fixture("profiles/base/market-bar/valid.json")
        for index in (
            {"name": "quantskills-envelope", "versions": {"01.0.0": "1.0.0.schema.json"}},
            {"name": "quantskills-envelope", "versions": {"1.0.0": "../escape.json"}},
            {"name": "quantskills-envelope", "versions": {"1.0.0": "1.0.0.schema.json"}, "extra": True},
        ):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "schema" / "envelope").mkdir(parents=True)
                (root / "schema" / "profiles").mkdir(parents=True)
                (root / "schema" / "envelope" / "index.json").write_text(json.dumps(index), encoding="utf-8")
                result = validate_contract(document, root)
                self.assertEqual(result["status"], "unknown")
                self.assertIsNone(result["envelope"])
                self.assertIsNone(result["profile"])

    def test_duplicate_profile_index_json_keys_fail_closed(self):
        document = read_fixture("profiles/base/market-bar/valid.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "schema" / "envelope").mkdir(parents=True)
            (root / "schema" / "profiles").mkdir(parents=True)
            shutil.copy2(ROOT / "schema" / "envelope" / "index.json", root / "schema" / "envelope" / "index.json")
            shutil.copy2(ROOT / "schema" / "envelope" / "1.0.0.schema.json", root / "schema" / "envelope" / "1.0.0.schema.json")
            (root / "schema" / "profiles" / "index.json").write_text('{"profiles":[],"profiles":[]}', encoding="utf-8")
            result = validate_contract(document, root)
        self.assertEqual(result["status"], "unknown")
        self.assertIsNone(result["envelope"])
        self.assertIsNone(result["profile"])
        self.assertEqual(result["errors"], [{"layer": "profile", "code": "profile-index", "path": "/schema/profiles/index.json"}])

    def test_unsafe_schema_path_and_unresolved_refs_fail_closed(self):
        document = read_fixture("profiles/base/market-bar/valid.json")
        base_row = {
            "id": "market-bar",
            "version": "1.0.0",
            "kind": "base",
        }
        cases = (
            ("nul-path", {**base_row, "schema": "\u0000schema.json"}, None),
            (
                "internal-ref",
                {**base_row, "schema": "base/market-bar/1.0.0.schema.json"},
                {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": "#/$defs/missing"},
            ),
            (
                "external-ref",
                {**base_row, "schema": "base/market-bar/1.0.0.schema.json"},
                {"$schema": "https://json-schema.org/draft/2020-12/schema", "$ref": "https://example.invalid/schema"},
            ),
        )
        for label, row, schema in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "schema" / "envelope").mkdir(parents=True)
                (root / "schema" / "profiles" / "base" / "market-bar").mkdir(parents=True)
                shutil.copy2(ROOT / "schema" / "envelope" / "index.json", root / "schema" / "envelope" / "index.json")
                shutil.copy2(ROOT / "schema" / "envelope" / "1.0.0.schema.json", root / "schema" / "envelope" / "1.0.0.schema.json")
                (root / "schema" / "profiles" / "index.json").write_text(json.dumps({"profiles": [row]}), encoding="utf-8")
                if schema is not None:
                    (root / "schema" / "profiles" / row["schema"]).write_text(json.dumps(schema), encoding="utf-8")
                result = validate_contract(document, root)
                self.assertEqual(result["status"], "unknown")
                expected = (
                    {"layer": "profile", "code": "profile-index", "path": "/schema/profiles/index.json"}
                    if label == "nul-path"
                    else {"layer": "profile", "code": "profile-schema", "path": "/schema/profile"}
                )
                self.assertEqual(result["errors"], [expected])

    def test_cli_exit_codes_json_shape_and_relative_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            valid = root / "valid.json"
            valid.write_text(json.dumps(read_fixture("profiles/base/market-bar/valid.json")), encoding="utf-8")
            invalid_document = read_fixture("profiles/base/market-bar/valid.json")
            invalid_document["payload"]["records"][0]["high"] = 1
            invalid_document["payload"]["records"][0]["low"] = 2
            invalid = root / "invalid.json"
            invalid.write_text(json.dumps(invalid_document), encoding="utf-8")
            unknown_document = read_fixture("profiles/base/market-bar/valid.json")
            unknown_document["$contract"]["profile_version"] = "1.0.1"
            unknown = root / "unknown.json"
            unknown.write_text(json.dumps(unknown_document), encoding="utf-8")

            for path, code, status in ((valid, 0, "valid"), (invalid, 1, "invalid"), (unknown, 2, "unknown")):
                with self.subTest(path=path.name):
                    completed = run_cli(path, "--json")
                    self.assertEqual(completed.returncode, code, completed.stderr)
                    parsed = json.loads(completed.stdout)
                    self.assertEqual(set(parsed), {"status", "envelope", "profile", "errors", "warnings"})
                    self.assertEqual(parsed["status"], status)
            relative = run_cli(Path("tests/fixtures/profiles/base/market-bar/valid.json"), "--json", cwd=ROOT)
            self.assertEqual(relative.returncode, 0, relative.stderr)
            absolute = run_cli(valid.resolve(), "--json")
            self.assertEqual(absolute.returncode, 0, absolute.stderr)

    def test_cli_rejects_unreadable_nonstandard_and_duplicate_json(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = run_cli(root / "missing.json", "--json")
            self.assertEqual(missing.returncode, 2)
            malformed = root / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            self.assertEqual(run_cli(malformed, "--json").returncode, 2)
            for constant in ("NaN", "Infinity", "-Infinity"):
                nonstandard = root / f"nonstandard-{constant.replace('-', 'minus')}.json"
                nonstandard.write_text('{"x": ' + constant + '}', encoding="utf-8")
                self.assertEqual(run_cli(nonstandard, "--json").returncode, 2)
            duplicate = root / "duplicate.json"
            duplicate.write_text('{"x": 1, "x": 2}', encoding="utf-8")
            self.assertEqual(run_cli(duplicate, "--json").returncode, 2)

    def test_cli_json_is_ascii_safe_for_unicode_and_surrogate_pointers(self):
        document = read_fixture("profiles/base/market-bar/valid.json")
        document["schema"]["fields"]["\ud800"] = {"type": "not-a-field-type"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unicode.json"
            path.write_text(json.dumps(document, ensure_ascii=True), encoding="utf-8")
            environment = {**os.environ, "PYTHONIOENCODING": "cp1252"}
            completed = subprocess.run(
                [sys.executable, str(SCRIPTS / "validate_contract.py"), str(path), "--json"],
                cwd=ROOT,
                env=environment,
                text=True,
                encoding="ascii",
                errors="strict",
                capture_output=True,
            )
        self.assertEqual(completed.returncode, 1, completed.stderr)
        self.assertEqual(completed.stdout.count("\n"), 1)
        parsed = json.loads(completed.stdout)
        self.assertIn({"layer": "envelope", "code": "enum", "path": "/schema/fields/\ud800/type"}, parsed["errors"])


if __name__ == "__main__":
    unittest.main()
