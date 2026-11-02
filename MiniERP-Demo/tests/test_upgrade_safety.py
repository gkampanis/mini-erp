import tempfile,unittest,sqlite3,json
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
import START_DEMO
from app.infrastructure.database import connect
from app.infrastructure import database


class UpgradeSafetyTests(unittest.TestCase):
    def configuration_fixture(self, root):
        # Build an existing installation from SQL, without calling connect or
        # accidentally creating this release's backup before configuration exists.
        db=sqlite3.connect(root/'mini_erp.sqlite3')
        db.execute('CREATE TABLE schema_migrations(version TEXT PRIMARY KEY)')
        for migration in sorted(database.MIGRATIONS.glob('*.sql')):
            db.executescript(migration.read_text(encoding='utf8'))
            db.execute('INSERT INTO schema_migrations VALUES (?)',(migration.name,));db.commit()
        db.execute("INSERT INTO companies(id,vat,name) VALUES (1,'000000001','SYNTHETIC')")
        for identifier,environment in ((1,'production'),(2,'test')):
            db.execute('INSERT INTO counterparties(id,company_id,vat,name,environment) VALUES (?,1,?,?,?)',
                       (identifier,'000000002','SYNTHETIC '+environment,environment))
            db.execute("INSERT INTO account_mappings VALUES (1,?,'64.00.001','synthetic-reviewer')",(identifier,))
            db.execute("INSERT INTO counterparty_accounts(counterparty_id,company_id,purchases_account,expenses_account,preferred_group,approved_by,version) VALUES (?,1,'20.00.001','64.00.001','6','synthetic-reviewer',7)",(identifier,))
            for category,exemption,use_primary,account in ((1,0,1,None),(7,27,0,'64.00.027')):
                db.execute('INSERT INTO counterparty_vat_rules(company_id,environment,counterparty_id,vat_category,vat_exemption,use_primary,account) VALUES (1,?,?,?,?,?,?)',
                           (environment,identifier,category,exemption,use_primary,account))
            db.execute('INSERT INTO sync_preferences VALUES (1,?,1,1)',(environment,))
        db.execute('INSERT INTO ebs_profiles(company_id,profile_json,signature,pilot_note) VALUES (1,?,?,?)',
                   (json.dumps({'synthetic':True,'sequence':['fill','save','new']}),'synthetic-signature','synthetic pilot'))
        db.commit()
        return db

    def configuration_rows(self, db):
        return {table:db.execute('SELECT * FROM '+table+' ORDER BY 1,2').fetchall()
                for table in ('companies','counterparties','account_mappings','counterparty_accounts',
                              'counterparty_vat_rules','ebs_profiles','sync_preferences')}

    def test_configured_installation_and_committed_wal_are_preserved_before_migration(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);source=self.configuration_fixture(root)
            source.execute('PRAGMA journal_mode=WAL')
            source.execute("UPDATE companies SET name='COMMITTED WAL CONFIGURATION'");source.commit()
            expected=self.configuration_rows(source)
            preferences=b'{"theme":"dark","geometry":"1400x900","tables":{"accounts":{"widths":[130,220]}}}'
            (root/'ui-preferences.json').write_bytes(preferences)
            migrations=root/'new-migrations';migrations.mkdir()
            (migrations/'999_upgrade_probe.sql').write_text("CREATE TABLE upgrade_probe(value TEXT); INSERT INTO upgrade_probe VALUES ('new version');",encoding='utf8')
            with patch('app.__version__','synthetic-configured-upgrade'),patch.object(database,'MIGRATIONS',migrations):
                upgraded=connect(root)
                try:
                    upgraded.row_factory=None
                    self.assertEqual(self.configuration_rows(upgraded),expected)
                    self.assertEqual(upgraded.execute('SELECT value FROM upgrade_probe').fetchone(),('new version',))
                    snapshot=root/'backups/synthetic-configured-upgrade'
                    with closing(sqlite3.connect(snapshot/'mini_erp.sqlite3')) as saved:
                        self.assertEqual(self.configuration_rows(saved),expected)
                        self.assertIsNone(saved.execute("SELECT name FROM sqlite_master WHERE name='upgrade_probe'").fetchone())
                        self.assertEqual(saved.execute('PRAGMA integrity_check').fetchone(),('ok',))
                        self.assertEqual(saved.execute('PRAGMA foreign_key_check').fetchall(),[])
                    self.assertEqual((snapshot/'ui-preferences.json').read_bytes(),preferences)
                    self.assertEqual((root/'ui-preferences.json').read_bytes(),preferences)
                finally:
                    upgraded.close();source.close()

    def test_production_data_wins_when_legacy_demo_also_exists(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            for name in ('Data','Demo'):(root/name).mkdir();(root/name/'mini_erp.sqlite3').touch()
            self.assertEqual(START_DEMO.data_directory(root),root/'Data')
    def test_demo_only_and_new_install_locations_are_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.assertEqual(START_DEMO.data_directory(root),root/'Data')
            (root/'Demo').mkdir();(root/'Demo/mini_erp.sqlite3').touch()
            self.assertEqual(START_DEMO.data_directory(root),root/'Demo')
    def test_upgrade_snapshot_keeps_accounts_profiles_preferences_and_is_once_per_version(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);db=connect(root)
            with db:db.execute("INSERT INTO companies(vat,name) VALUES ('000000000','SYNTHETIC')")
            db.close();prefs=b'{"theme":"dark","tables":{"saved":123}}';(root/'ui-preferences.json').write_bytes(prefs)
            with patch('app.__version__','synthetic-upgrade'):
                db=connect(root);db.close()
                directory=root/'backups/synthetic-upgrade'
                self.assertEqual((directory/'ui-preferences.json').read_bytes(),prefs)
                backup=sqlite3.connect(directory/'mini_erp.sqlite3')
                self.assertEqual(backup.execute('SELECT name FROM companies').fetchone()[0],'SYNTHETIC');backup.close()
                before=(directory/'mini_erp.sqlite3').read_bytes()
                db=connect(root)
                with db:db.execute("UPDATE companies SET name='CHANGED'")
                (root/'ui-preferences.json').write_bytes(b'{"theme":"light"}')
                db.close();db=connect(root);db.close()
                self.assertEqual((directory/'mini_erp.sqlite3').read_bytes(),before)
                self.assertEqual((directory/'ui-preferences.json').read_bytes(),prefs)
