# Task 3 Report — Catalog Semantic Validation

## Changed files

- `scripts/catalog_contract.py`: deterministic taxonomy, schema, semantic, description, and canonical-JSON helpers.
- `scripts/validate_skill.py`: declaration-v2 audit/enforce integration, path-carrying reports, and quant risk-disclosure gate.
- `tests/test_catalog_contract.py`: semantic-helper coverage.
- `tests/test_validate_skill.py`: audit/enforce, risk documentation, non-triggered, and retained-health-check coverage.

## RED/GREEN evidence

- RED: a deliberately invalid cross-category declaration probe asserted it was valid and failed with `AssertionError` (expected non-zero result); this demonstrates the new semantic boundary is exercised.
- GREEN: `python -m unittest tests.test_catalog_contract tests.test_validate_skill -v` — 8 tests passed.
- GREEN: `python -m unittest discover -s tests -v` — 18 tests passed, including Tasks 1–2 schema/taxonomy tests.

## Commands and results

- `python -m py_compile scripts/catalog_contract.py scripts/validate_skill.py scripts/build_registry.py` — passed.
- `node scripts/validate-registry.mjs` — passed; existing 103-row projection validated.
- `git diff --check` — passed.

## Compatibility notes

- `validate(repo, org_repos)` remains valid and defaults to `contract_mode="audit"`; callers may select `"enforce"` explicitly.
- `Report.add(level, check, detail)` remains valid; it now accepts optional `path` and report items always expose it.
- Required-file, path-reference, hygiene, secret, Python syntax, requires, and description trigger checks are retained. Contract gaps are warnings in audit mode and failures in enforce mode; missing declaration/frontmatter/name and hard safety failures remain failures.

## Self-review

- Semantic classification reads only `schema/taxonomy.v1.json`; it has no category fallback or name/description classification.
- Validation is deterministic, UTF-8 safe, does not alter scanned repositories, and details identify issue classes rather than values from scanned content.
- Risk disclosure is triggered only by the required workflow stages or tags and reads only the permitted documentation files.

## Commit

`5714bb8fb7871544c252e2f89a8bc2a9b0b31a24` (`feat(validation): enforce catalog declaration semantics`).

## Concerns

The historic registry builder still projects legacy category fields; Task 3 intentionally does not alter Task 4 builder behavior or generated artifacts.

## Review Fix Round 1

### Files changed

- `scripts/catalog_contract.py`: Envelope versions now require complete `MAJOR.MINOR.PATCH` semver before major-version acceptance.
- `tests/test_catalog_contract.py`: added malformed `1.invalid` Envelope regression and parameterized coverage for all required Chinese and English prohibited claims plus allowed disclaimers.
- `tests/test_validate_skill.py`: replaced the vacuous check assertion with one temporary repository that positively exercises all eight retained check families.

### Named regression tests

- `CatalogContractTests.test_malformed_envelope_version_is_a_semantic_issue`
- `CatalogContractTests.test_claims_and_repository_name_restating_are_rejected_but_disclaimers_are_allowed`
- `ValidateSkillTests.test_existing_check_families_remain_available`

### Commands and output

- `python -m unittest tests.test_catalog_contract tests.test_validate_skill -v` — 9 tests passed.
- `python -m unittest discover -s tests -v` — 19 tests passed.
- `python -m py_compile scripts/catalog_contract.py scripts/validate_skill.py scripts/build_registry.py` — passed.
- `git diff --check` — passed.

### Commit

`2219adef2c44f772a732f4eee8d8f6dcda1d9449` (`fix(validation): tighten contract regression coverage`).

### Self-review

- `1.invalid` no longer derives a valid major version because matching is anchored to the complete semver string.
- The all-family test produces evidence for required files, description quality/frontmatter, path references, Git hygiene, secrets, risk disclosures, Python syntax, and requires.
- Claim coverage asserts each required phrase creates a prohibited-claim issue while the Chinese and English non-advice disclaimers do not.
