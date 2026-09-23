"""Create, verify and restore an immutable research snapshot using the stdlib."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[2]
DATABASE = 'outputs/research/research.sqlite3'
ARCHIVE = 'research-data.tar.gz'


def checksum(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '..' in path.parts or '\\' in name
            or ':' in name or str(path) != name or name == '.'):
        raise ValueError('Unsafe archive path: ' + str(name))
    return path


def read_database(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    return db


def check_database(path):
    with closing(read_database(path)) as db:
        if [r[0] for r in db.execute('PRAGMA integrity_check')] != ['ok']:
            raise ValueError('Database integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('Database foreign-key check failed')


def decode(row):
    result = dict(row)
    for key in list(result):
        if key.endswith('_json'):
            value = result.pop(key)
            result[key[:-5]] = json.loads(value) if value else None
    return result


def create(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError('Choose a new snapshot directory: ' + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    with tempfile.TemporaryDirectory(prefix='.vetting-snapshot-', dir=output.parent) as temp:
        workspace = Path(temp)
        payload, package = workspace / 'payload', workspace / 'package'
        package.mkdir()
        db_path = payload / DATABASE
        db_path.parent.mkdir(parents=True)
        source = read_database(root / DATABASE)
        target = sqlite3.connect(db_path)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
        captured = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        check_database(db_path)
        files = {DATABASE: {'path': DATABASE, 'kind': 'database',
            'bytes': db_path.stat().st_size, 'sha256': checksum(db_path)}}

        def add(path, kind, expected=None, size=None):
            path = Path(path)
            if not path.is_absolute():
                path = root / path
            relative = path.resolve().relative_to(root).as_posix()
            safe_name(relative)
            if relative in files:
                record = files[relative]
                if expected and record['sha256'] != expected:
                    raise ValueError('Conflicting recorded hash: ' + relative)
                if size is not None and record['bytes'] != size:
                    raise ValueError('Conflicting recorded size: ' + relative)
                return
            destination = payload / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
            digest = checksum(destination)
            actual_size = destination.stat().st_size
            if expected and digest != expected:
                raise ValueError('Source differs from recorded hash: ' + relative)
            if size is not None and actual_size != size:
                raise ValueError('Source differs from recorded size: ' + relative)
            files[relative] = {'path': relative, 'kind': kind, 'bytes': actual_size, 'sha256': digest}

        with closing(read_database(db_path)) as db:
            counts = {name: db.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                      for name in ('jobs', 'candidates', 'artifacts', 'evidence', 'reviews', 'events')}
            counts['candidates_by_cohort'] = dict(db.execute(
                'SELECT j.cohort,count(*) FROM candidates c JOIN jobs j ON j.id=c.job_id GROUP BY j.cohort'))
            for row in db.execute('SELECT DISTINCT sha256,size_bytes FROM artifacts'):
                digest, size = row
                if not re.fullmatch('[a-f0-9]{64}', digest):
                    raise ValueError('Invalid artifact digest')
                add('outputs/research/artifacts/' + digest[:2] + '/' + digest, 'artifact', digest, size)
            for row in db.execute('SELECT path,sha256,bytes FROM watch_snapshots'):
                add(row[0], 'archive_metadata', row[1], row[2])
            for row in db.execute('SELECT inputs_json FROM jobs'):
                inputs = json.loads(row[0])
                for path in inputs.get('paths', []):
                    digest = inputs.get('sha256', {}).get(path)
                    if not digest:
                        raise ValueError('Input has no recorded hash: ' + path)
                    add(path, 'lightcurve_input', digest)
            for row in db.execute("SELECT payload_json FROM evidence WHERE kind='model_score' AND state='complete'"):
                model = json.loads(row[0])
                add(model['checkpoint_path'], 'model', model['model_sha256'])
                add(model['normalization_path'], 'normalizer', model['normalization_sha256'])
            for row in db.execute("SELECT payload_json FROM evidence WHERE kind='model_comparison' AND state='complete'"):
                comparison = json.loads(row[0])
                add(comparison['normalization_path'], 'normalizer', comparison['normalization_sha256'])
                for model in comparison['models']:
                    add(model['checkpoint_path'], 'model', model['model_sha256'])
            candidates = []
            for row in db.execute('SELECT c.*,j.cohort FROM candidates c JOIN jobs j ON j.id=c.job_id ORDER BY c.created_at,c.id'):
                candidate = decode(row)
                if candidate['cohort'] == 'synthetic_fixture':
                    continue
                history = [decode(e) for e in db.execute('SELECT * FROM evidence WHERE candidate_id=? ORDER BY rowid', (candidate['id'],))]
                candidate['evidence'] = list({e['kind']: e for e in history}.values())
                candidate['artifacts'] = [decode(a) for a in db.execute('SELECT * FROM artifacts WHERE candidate_id=? ORDER BY id', (candidate['id'],))]
                candidate['reviews'] = [decode(r) for r in db.execute('SELECT * FROM reviews WHERE candidate_id=? ORDER BY revision', (candidate['id'],))]
                candidates.append(candidate)

        # Retain the code needed to view this snapshot, not browser caches or credentials.
        for directory in ('scripts', 'training', 'configs'):
            for path in sorted((root / directory).rglob('*')):
                if path.is_file() and path.suffix in ('.py', '.json', '.js', '.css', '.html') and '__pycache__' not in path.parts:
                    add(path, 'source')
        for name in ('README.md', 'requirements.txt', 'requirements-reference.txt'):
            if (root / name).is_file():
                add(name, 'source')
        try:
            commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        except (OSError, subprocess.SubprocessError):
            commit = None
        save_json(package / 'vetting.json', {'schema_version': 1, 'captured_at_utc': captured,
            'scope': 'Current real-data evidence; full history and synthetic controls are preserved in the database archive',
            'score_semantics': 'Uncalibrated ranking, not planet probability', 'candidates': candidates})
        # Fixed gzip/tar metadata; the manifest records the actual capture time.
        with (package / ARCHIVE).open('wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0, compresslevel=6) as compressed:
                with tarfile.open(fileobj=compressed, mode='w') as archive:
                    for name in sorted(files):
                        path = payload / name
                        info = tarfile.TarInfo(name)
                        info.size, info.mode, info.mtime = path.stat().st_size, 0o644, 0
                        with path.open('rb') as stream:
                            archive.addfile(info, stream)
        manifest = {'schema_version': 1, 'started_at_utc': started, 'captured_at_utc': captured,
            'base_git_commit': commit, 'source_tree_note': 'Exact packaged source bytes are identified by the per-file hashes; they can include uncommitted snapshot-tool changes.',
            'database': DATABASE, 'counts': counts, 'file_counts_by_kind': dict(Counter(r['kind'] for r in files.values())),
            'uncompressed_bytes': sum(r['bytes'] for r in files.values()),
            'archive': {'path': ARCHIVE, 'bytes': (package / ARCHIVE).stat().st_size, 'sha256': checksum(package / ARCHIVE)},
            'vetting_export': {'path': 'vetting.json', 'sha256': checksum(package / 'vetting.json')},
            'files': [files[name] for name in sorted(files)],
            'limits': ['Frozen snapshot, not continuous backup', 'Original absolute provenance paths are retained',
                       'Full training datasets and unrelated experiments are outside this snapshot',
                       'Raw logs, browser profiles, credentials and unreferenced blobs are excluded']}
        save_json(package / 'manifest.json', manifest)
        verify(package)
        package.rename(output)
    return manifest


def verify(snapshot, destination=None):
    snapshot = Path(snapshot).resolve()
    manifest = json.loads((snapshot / 'manifest.json').read_text())
    if manifest['schema_version'] != 1 or manifest['archive']['path'] != ARCHIVE:
        raise ValueError('Unsupported snapshot manifest')
    archive_path = snapshot / ARCHIVE
    if (archive_path.stat().st_size != manifest['archive']['bytes']
            or checksum(archive_path) != manifest['archive']['sha256']):
        raise ValueError('Archive checksum or size mismatch')
    if manifest['vetting_export']['path'] != 'vetting.json' or checksum(snapshot / 'vetting.json') != manifest['vetting_export']['sha256']:
        raise ValueError('Vetting export checksum mismatch')
    expected = {}
    for record in manifest['files']:
        name = str(safe_name(record['path']))
        if name in expected:
            raise ValueError('Duplicate manifest path')
        expected[name] = record
    seen = set()
    with tarfile.open(archive_path, 'r:gz') as archive:
        for member in archive:
            name = str(safe_name(member.name))
            if not member.isfile() or name not in expected or name in seen:
                raise ValueError('Unexpected, duplicate or non-file archive member: ' + name)
            record = expected[name]
            if member.size != record['bytes']:
                raise ValueError('Archive member size mismatch: ' + name)
            h = hashlib.sha256()
            target = None
            if destination is not None:
                path = Path(destination) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                target = path.open('xb')
            try:
                with archive.extractfile(member) as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        h.update(chunk)
                        if target:
                            target.write(chunk)
            finally:
                if target:
                    target.close()
            if h.hexdigest() != record['sha256']:
                raise ValueError('Archive member checksum mismatch: ' + name)
            seen.add(name)
    if seen != set(expected):
        raise ValueError('Archive omits manifest files')
    return manifest


def restore(snapshot, destination):
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError('Restore refuses an existing destination: ' + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.vetting-restore-', dir=destination.parent) as temp:
        payload = Path(temp) / 'payload'
        payload.mkdir()
        manifest = verify(snapshot, payload)
        if manifest['database'] != DATABASE:
            raise ValueError('Unsupported database location')
        check_database(payload / DATABASE)
        payload.rename(destination)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('create')
    make.add_argument('--root', type=Path, default=ROOT)
    make.add_argument('--output', type=Path, required=True)
    for command in ('verify', 'restore'):
        sub = commands.add_parser(command)
        sub.add_argument('--snapshot', type=Path, required=True)
        if command == 'restore':
            sub.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'create':
        result = create(args.root, args.output)
    elif args.command == 'verify':
        result = verify(args.snapshot)
    else:
        result = restore(args.snapshot, args.destination)
    print(json.dumps({'status': 'verified', 'counts': result['counts'], 'files': len(result['files']),
                      'archive_bytes': result['archive']['bytes'], 'archive_sha256': result['archive']['sha256']}, indent=2))


if __name__ == '__main__':
    main()
