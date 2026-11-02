from pathlib import Path
import sqlite3
import json
import shutil
import tempfile

MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations'


def connect(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    if (directory/'mini_erp.sqlite3').is_file():upgrade_backup(directory)
    db = sqlite3.connect(directory / 'mini_erp.sqlite3', timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY)')
    db.commit()
    for path in sorted(MIGRATIONS.glob('*.sql')):
        if not db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (path.name,)).fetchone():
            rebuild = path.name == '016_document_environments.sql'
            if rebuild:db.execute('PRAGMA foreign_keys=OFF')
            try:
                db.executescript('BEGIN IMMEDIATE;\n' + path.read_text())
                if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
                    raise RuntimeError('Migration foreign-key check failed')
                if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Migration integrity check failed')
                db.execute('INSERT INTO schema_migrations VALUES (?)', (path.name,))
                db.commit()
            except Exception:
                db.rollback()
                if rebuild:db.execute('PRAGMA foreign_keys=ON')
                db.close()
                raise
            finally:
                if rebuild:
                    try:db.execute('PRAGMA foreign_keys=ON')
                    except sqlite3.ProgrammingError:pass  # Failed connection was closed above.
    return db


def upgrade_backup(directory):
    """Preserve an existing database before this version can migrate it."""
    from app import __version__
    destination=Path(directory)/'backups'/__version__
    if (destination/'COMPLETE.json').is_file():return destination
    destination.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.snapshot-',dir=destination.parent))
    source=None
    try:
        source=sqlite3.connect((Path(directory)/'mini_erp.sqlite3').resolve().as_uri()+'?mode=ro',uri=True,timeout=15)
        backup(source,staging/'mini_erp.sqlite3')
        preferences=Path(directory)/'ui-preferences.json'
        if preferences.is_file():shutil.copy2(preferences,staging/'ui-preferences.json')
        (staging/'COMPLETE.json').write_text(json.dumps(dict(version=__version__,database='mini_erp.sqlite3',preferences=preferences.is_file(),integrity='ok')),encoding='utf8')
        try:staging.rename(destination)
        except OSError:
            if not (destination/'COMPLETE.json').is_file():raise
    finally:
        if source is not None:source.close()
        if staging.exists():
            if not staging.resolve().is_relative_to(destination.parent.resolve()):raise RuntimeError('Invalid backup staging location')
            shutil.rmtree(staging)
    return destination


def backup(db, path):
    target = sqlite3.connect(path)
    try:
        db.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity check failed')
    finally:
        target.close()
