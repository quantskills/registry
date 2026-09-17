"""Project verified, queue-bound on-demand measurements without exposing evidence."""
import argparse
import datetime as dt
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile

from export_public_evaluations import (build_record, canonical, digest, file_digest,
    read_json, write_json, expected_scoring_asset_ids, project_current_records,
    select_recommendations, promote_evaluation_artifacts, security_for_request,
    validate_scoring_cohort)
from verify_public_evaluations import verify_publication

PUBLICATION = 'publication.v12.13.on-demand'


def read_measurements(config):
    sys.path.insert(0, str(Path(config['approved_checkout']) / 'src'))
    from quantskills_eval.attestation import verify
    from quantskills_eval.cli import load_keyring
    from quantskills_eval.evaluation import _score, _suite
    source = read_json(Path(config['source_controller_config']))
    if file_digest(Path(config['source_controller_config'])) != config['source_config_sha']:
        raise ValueError('source configuration changed')
    keys = load_keyring(source['keyring'])
    rules = read_json(Path(config['rules']))
    observations, evidence = [], {}
    with sqlite3.connect(Path(config['queue_db']).resolve().as_uri() + '?mode=ro', uri=True) as queue:
        queue.row_factory = sqlite3.Row
        rows = queue.execute("""SELECT f.*,l.result_digest,l.asset_id FROM on_demand_authority_finalizations f
            JOIN on_demand_jobs j USING(request_id) JOIN on_demand_authority_leases l USING(request_id)
            WHERE j.status='measured' AND l.status='measured' AND j.run_id=f.run_id AND l.run_id=f.run_id
            ORDER BY j.updated,j.request_id""").fetchall()
    for row in rows:
        root = Path(config['runs_root']) / 'Bridge' / 'runs' / row['batch_id']
        result, bindings = read_json(root / 'result.json'), read_json(root / 'bindings.json')
        if digest(result) != row['result_digest'] or digest(bindings) != row['stage_digest']:
            raise ValueError('on-demand artifact binding mismatch')
        if result.get('request_id') != row['request_id'] or result.get('asset_id') != row['asset_id'] or result.get('ingest', {}).get('accepted') is not True:
            raise ValueError('on-demand result is not accepted')
        if len(bindings.get('assets', [])) != 1:
            raise ValueError('on-demand asset binding mismatch')
        asset = bindings['assets'][0]
        payload, measurement_digest = verify(result['envelope'], keys)
        if payload['asset_id'] != asset['asset_id'] or payload['commit'] != asset['commit_sha'] or payload['outcome'] != 'complete':
            raise ValueError('signed asset binding mismatch')
        runtime = Path(config['executor_roots'][asset['category'][:2]]) / 'runs' / row['batch_id']
        database = runtime / 'state' / 'evaluation.sqlite3'
        with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            score = db.execute('SELECT * FROM score_records WHERE request_id=?', (payload['request_id'],)).fetchone()
            attestation = db.execute('SELECT * FROM attestations WHERE request_id=?', (payload['request_id'],)).fetchone()
            if score is None or attestation is None or score['measurement_digest'] != measurement_digest or attestation['payload_digest'] != measurement_digest:
                raise ValueError('signed score binding mismatch')
            if json.loads(attestation['envelope']) != payload or json.loads(score['score']) != _score(payload, rules, _suite(rules, asset['category'][:2])):
                raise ValueError('score is not the projection of the signed measurement')
            security = security_for_request(db, payload['request_id'], runtime, asset['asset_id'])
            record = build_record(PUBLICATION, score, attestation, security, digest(result['envelope']), asset['category'][:2])
        observations.append(record)
        evidence[row['request_id']] = {'result_digest': row['result_digest'], 'bindings_digest': row['stage_digest']}
    return observations, evidence


def refresh(root, config):
    evaluation = root / 'evaluations'
    catalog, registry = read_json(root / 'catalog.snapshot.json'), read_json(root / 'registry.json')
    expected = expected_scoring_asset_ids(catalog, registry)
    dataset, manifest = read_json(evaluation / 'current-scores.json'), read_json(evaluation / 'manifest.json')
    observations, evidence = read_measurements(config)
    current = {}
    for publication in dataset['publication_precedence']:
        if publication == PUBLICATION:
            continue
        relative = f'publications/{publication}.jsonl'
        path = evaluation / relative
        if file_digest(path) != manifest['files'].get(relative):
            raise ValueError('historical publication digest mismatch')
        for line in path.read_text(encoding='utf-8').splitlines():
            if line:
                record = json.loads(line)
                current[record['asset_id']] = record
    for record in observations:
        current[record['asset_id']] = record
    records = project_current_records(current, expected)
    validate_scoring_cohort(records)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')
    precedence = [p for p in dataset['publication_precedence'] if p != PUBLICATION]
    if observations:
        precedence.append(PUBLICATION)
    history_count = sum(p['observation_count'] for p in manifest['publications'] if p['publication'] != PUBLICATION) + len(observations)
    # Preserve generation timestamps on an unchanged cycle to avoid noisy PRs.
    changed = records != dataset['records'] or precedence != dataset['publication_precedence'] or dataset['catalog_snapshot_id'] != catalog['snapshot_id'] or history_count != dataset['historical_observation_count']
    generated = now if changed else dataset['generated_at']
    with tempfile.TemporaryDirectory(dir=root, prefix='.on-demand-projection-') as temporary:
        stage_root = Path(temporary)
        stage = stage_root / 'evaluations'
        shutil.copytree(evaluation, stage)
        for name in ('catalog.snapshot.json', 'registry.json'):
            shutil.copyfile(root / name, stage_root / name)
        schema = read_json(stage / 'schemas/current-scores.schema.json')
        allowed = schema['$defs']['record']['properties']['source_publication']['enum']
        if PUBLICATION not in allowed:
            allowed.append(PUBLICATION)
        write_json(stage / 'schemas/current-scores.schema.json', schema)
        dataset.update(generated_at=generated, records=records, record_count=len(records), historical_observation_count=history_count, publication_precedence=precedence, catalog_snapshot_id=catalog['snapshot_id'])
        write_json(stage / 'current-scores.json', dataset)
        if observations:
            (stage / 'publications' / (PUBLICATION + '.jsonl')).write_bytes(b''.join(canonical(r) + b'\n' for r in observations))
        recommended = read_json(stage / 'recommended.snapshot.json')
        recommendations = select_recommendations(records, {r['name'] for r in registry})
        recommended.update(generated_at=generated, records=recommendations, record_count=len(recommendations), catalog_snapshot_id=catalog['snapshot_id'], score_dataset_sha256=file_digest(stage / 'current-scores.json'))
        write_json(stage / 'recommended.snapshot.json', recommended)
        publications = [p for p in manifest['publications'] if p['publication'] != PUBLICATION]
        if observations:
            publications.append({'publication': PUBLICATION, 'observation_count': len(observations), 'control_artifact_sha256': digest(evidence), 'score_rows_root': digest([r['integrity']['score_row_sha256'] for r in observations]), 'attestation_rows_root': digest([r['integrity']['attestation_payload_digest'] for r in observations]), 'signed_envelope_files_root': digest([r['integrity']['signed_envelope_sha256'] for r in observations])})
        readme = stage / 'README.md'
        readme.write_text('# Public Shadow evaluations\n\nMaintainer: abgyjaguo. GPL-3.0-only.\n\nThe generated current score projection contains ' + str(len(records)) + ' assets. Immutable historical observations and verified on-demand screening results remain distinguishable by source publication. Recommendations use the existing category-relative top-quartile policy; this is research material, not endorsement or investment advice. Pending or rejected requests never produce scores.\n\nVerify with `python scripts/verify_public_evaluations.py`. Regenerate on the trusted controller with `python scripts/refresh_on_demand_evaluations.py --config <authority-config>`. No private payloads, candidate code or credentials are published.\n', encoding='utf-8', newline='\n')
        files = {p.relative_to(stage).as_posix(): file_digest(p) for p in sorted(stage.rglob('*')) if p.is_file() and p.name != 'manifest.json'}
        manifest.update(generated_at=generated, record_count=len(records), historical_observation_count=history_count, catalog_snapshot_id=catalog['snapshot_id'], publications=publications, files=files)
        manifest['snapshot_digest'] = digest({k: v for k, v in manifest.items() if k != 'snapshot_digest'})
        write_json(stage / 'manifest.json', manifest)
        result = verify_publication(stage_root)
        promote_evaluation_artifacts(stage, evaluation, [*files, 'manifest.json'])
    return dict(result, on_demand_observations=len(observations))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(json.dumps(refresh(args.root, read_json(args.config)), sort_keys=True))
