"""Machine-readable results from real unittest runners; no output-based pass guesses."""
import argparse
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite',choices=('backend','gui'),required=True)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--test',action='append',default=[],help='Run only these explicit unittest selectors')
    parser.add_argument('--gui-module',choices=tuple('tests.'+p.stem for p in sorted((ROOT/'tests').glob('gui_*.py'))))
    args = parser.parse_args()
    if args.suite=='gui' and args.gui_module is None and not args.test:
        # Independent Tk interpreters must finish on their owning main thread.
        # Run every GUI module, retaining its real structured unittest result.
        results=[]
        with tempfile.TemporaryDirectory(prefix='mini-erp-gui-checks-') as folder:
            for path in sorted((ROOT/'tests').glob('gui_*.py')):
                # gui_smoke is a script, run explicitly by the delivery gate.
                # It has no unittest cases and must not be an empty suite here.
                if path.stem=='gui_smoke':continue
                report=Path(folder)/(path.stem+'.json')
                run=subprocess.run([sys.executable,__file__,'--suite','gui','--gui-module','tests.'+path.stem,'--report',str(report)],cwd=ROOT)
                if not report.exists():raise RuntimeError('GUI runner did not produce a report: '+path.stem)
                result=json.loads(report.read_text());result['successful']=result['successful'] and run.returncode==0
                results.append(result)
        data={key:sum(r[key] for r in results) for key in ('tests','failures','errors','skipped','expected_failures','unexpected_successes')}
        data['successful']=all(r['successful'] for r in results)
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8')
        return 0 if data['successful'] else 1
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromNames(args.test) if args.test else loader.loadTestsFromName(args.gui_module) if args.gui_module else loader.discover(str(ROOT/'tests'),pattern='test*.py',top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                skipped=len(result.skipped),expected_failures=len(result.expectedFailures),
                unexpected_successes=len(result.unexpectedSuccesses),successful=result.wasSuccessful())
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':sys.exit(main())
