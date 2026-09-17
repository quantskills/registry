import json
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
