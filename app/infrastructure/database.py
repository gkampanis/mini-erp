from pathlib import Path
import sqlite3

MIGRATIONS = Path(__file__).resolve().parents[2] / 'migrations'


def connect(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(directory / 'mini_erp.sqlite3', timeout=15)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('CREATE TABLE IF NOT EXISTS schema_migrations(version TEXT PRIMARY KEY)')
    db.commit()
    for path in sorted(MIGRATIONS.glob('*.sql')):
        if not db.execute('SELECT 1 FROM schema_migrations WHERE version=?', (path.name,)).fetchone():
            try:
                db.executescript('BEGIN IMMEDIATE;\n' + path.read_text() + "\nINSERT INTO schema_migrations VALUES ('" + path.name.replace("'", "''") + "');\nCOMMIT;")
            except Exception:
                db.rollback()
                db.close()
                raise
    return db


def backup(db, path):
    target = sqlite3.connect(path)
    try:
        db.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('Backup integrity check failed')
    finally:
        target.close()
