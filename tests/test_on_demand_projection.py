import json
import hashlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import refresh_on_demand_evaluations as projection


class OnDemandProjectionTests(unittest.TestCase):
    def test_signed_active_suite_cannot_be_relabelled_as_old_model(self):
        private = {'reference_config': {'suite': 'new', 'model': 'gpt-6-sol', 'reasoning_effort': 'medium'}}
        self.assertEqual(projection.model_profile(private, {'suite': 'new'}, 'new'), projection.MODEL_PROFILE)
        private['reference_config']['model'] = 'gpt-5.6-terra'
        with self.assertRaisesRegex(ValueError, 'unsupported evaluation model profile'):
            projection.model_profile(private, {'suite': 'new'}, 'new')
        private['reference_config']['suite'] = 'old'
        self.assertIsNone(projection.model_profile(private, {'suite': 'old'}, 'new'))
        with self.assertRaisesRegex(ValueError, 'signed model suite binding mismatch'):
            projection.model_profile(private, {'suite': 'new'}, 'new')

    def test_queue_binding_uses_authority_unicode_escaping(self):
        value = {"label": "中文"}
        expected = hashlib.sha256(b'{"label":"\\u4e2d\\u6587"}').hexdigest()
        self.assertEqual(projection.queue_digest(value), expected)
        self.assertNotEqual(projection.digest(value), expected)
        self.assertNotEqual(projection.queue_digest({"label": "changed"}), expected)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / 'evaluations', self.root / 'evaluations')
        for name in ('catalog.snapshot.json', 'registry.json'):
            shutil.copyfile(ROOT / name, self.root / name)
        observations = [json.loads(line) for line in
            (self.root / 'evaluations/publications/publication.v12.13.on-demand.jsonl').read_text(encoding='utf-8').splitlines()]
        self.measurements = observations, {'verified': 'test-bound-results'}

    def snapshot(self):
        return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_identical_measurements_produce_no_repeated_update(self):
        with patch.object(projection, 'read_measurements', return_value=self.measurements):
            projection.refresh(self.root, {})
            before = self.snapshot()
            projection.refresh(self.root, {})
        self.assertEqual(before, self.snapshot())

    def test_tampered_history_is_rejected_without_promotion(self):
        path = self.root / 'evaluations/publications/publication.v12.13.jsonl'
        path.write_bytes(path.read_bytes() + b'\n')
        before = self.snapshot()
        with patch.object(projection, 'read_measurements', return_value=self.measurements):
            with self.assertRaisesRegex(ValueError, 'historical publication digest mismatch'):
                projection.refresh(self.root, {})
        self.assertEqual(before, self.snapshot())

    def test_new_model_is_reviewed_without_changing_current_ranking(self):
        observations, evidence = self.measurements
        changed = dict(observations[0], evaluation_profile=projection.MODEL_PROFILE)
        with patch.object(projection, 'read_measurements', return_value=self.measurements):
            projection.refresh(self.root, {})
        previous = (self.root / 'evaluations/current-scores.json').read_bytes()
        measurements = observations + [changed], evidence
        with patch.object(projection, 'read_measurements', return_value=measurements):
            result = projection.refresh(self.root, {})
            before = self.snapshot()
            projection.refresh(self.root, {})
        self.assertEqual(previous, (self.root / 'evaluations/current-scores.json').read_bytes())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(result['model_review_observations'], 1)
        relative = 'model-cohorts/gpt-6-sol-medium.json'
        review = projection.read_json(self.root / 'evaluations' / relative)
        self.assertFalse(review['included_in_current_ranking'])
        self.assertEqual(review['records'], [changed])
        manifest = projection.read_json(self.root / 'evaluations/manifest.json')
        self.assertEqual(manifest['files'][relative], projection.file_digest(self.root / 'evaluations' / relative))
