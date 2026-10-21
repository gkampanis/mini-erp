from pathlib import Path
import hashlib
import os
import tempfile
from app.infrastructure.repository import Repository
from app.infrastructure.importers.excel import preview


class ERP:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.repository = Repository(directory)
        self.db = self.repository.db

    def close(self):
        self.repository.close()

    def company(self, vat, name):
        return self.repository.company(vat, name)

    def search(self, company, query=''):
        return self.repository.search(company, query)

    def detail(self, company, document):
        return self.repository.detail(company, document)

    def _archive(self, item):
        directory = self.directory / 'sources'
        directory.mkdir(exist_ok=True)
        path = directory / (item.sha256 + '.xlsx')
        if path.exists():
            if hashlib.sha256(path.read_bytes()).hexdigest() != item.sha256:
                raise ValueError('Αλλοιωμένο αρχείο προέλευσης')
            return
        fd, temp = tempfile.mkstemp(dir=directory)
        try:
            with os.fdopen(fd, 'wb') as out:
                out.write(item.data)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def commit_import(self, company, item, *, confirmed=False, fail_after=None):
        if not confirmed:
            raise ValueError('Απαιτείται ρητή επιβεβαίωση εισαγωγής')
        if hashlib.sha256(item.data).hexdigest() != item.sha256:
            raise ValueError('Αλλοιωμένο preview')
        # Reparse the original bytes using confirmed mapping; do not trust mutable preview records.
        fd, temp = tempfile.mkstemp(suffix=Path(item.filename).suffix)
        try:
            with os.fdopen(fd,'wb') as out:
                out.write(item.data)
            checked = preview(temp, item.mapping)
        finally:
            os.unlink(temp)
        if not checked.records:
            raise ValueError('Δεν υπάρχουν έγκυρες εγγραφές')
        self._archive(item)  # Content-addressed orphan on rollback is safe; never a partial DB import.
        return self.repository.persist_import(company, item, checked, fail_after)
