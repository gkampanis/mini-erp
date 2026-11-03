"""Small shareable diagnostics: allowlisted stack metadata, never exception messages."""
from datetime import datetime,timezone
from pathlib import Path
import json
import platform
import threading
import traceback

_LOCK=threading.Lock()
MAX_BYTES=64*1024

def record(directory,error,area='application'):
    try:
        # No exception text, locals, source lines, absolute paths, identifiers or URLs.
        root=Path(__file__).resolve().parents[2]
        frames=[]
        for frame in traceback.extract_tb(error.__traceback__)[-10:]:
            path=Path(frame.filename).resolve()
            if path.is_relative_to(root/'app') or path.is_relative_to(root/'scripts'):
                frames.append(dict(module=path.relative_to(root).as_posix(),line=frame.lineno))
        item=dict(time=datetime.now(timezone.utc).isoformat(),area=area if area in ('application','worker','callback','camoufox','installation') else 'application',error=type(error).__name__ if type(error).__module__=='builtins' else 'ExternalError',python=platform.python_version(),system=platform.system(),frames=frames)
        folder=Path(directory)/'diagnostics';folder.mkdir(parents=True,exist_ok=True)
        path=folder/'crashlog.jsonl'
        with _LOCK:
            if path.exists() and path.stat().st_size>MAX_BYTES:
                path.replace(folder/'crashlog.previous.jsonl')
            with path.open('a',encoding='utf8') as stream:stream.write(json.dumps(item,ensure_ascii=True)+'\n')
        return path
    except Exception:return None  # Diagnostics must never prevent normal operation.

def export(directory,destination):
    source=Path(directory)/'diagnostics';lines=[]
    for name in ('crashlog.previous.jsonl','crashlog.jsonl'):
        path=source/name
        if path.is_file():lines.extend(path.read_text(encoding='utf8').splitlines())
    lines=lines[-100:]
    # Same existing support export includes the bounded, sanitized RPA reports.
    for path in sorted(source.glob('ebs-failure-*.json'))[-20:]:
        try:lines.append(json.dumps(dict(area='ebs_rpa',report=json.loads(path.read_text(encoding='utf8'))),ensure_ascii=False))
        except (OSError,ValueError):continue
    Path(destination).write_text('\n'.join(lines)+'\n',encoding='utf8')
