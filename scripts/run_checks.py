"""Machine-readable results from real unittest runners; no output-based pass guesses."""
import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite',choices=('backend','gui'),required=True)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    loader = unittest.TestLoader()
    suite = loader.discover(str(ROOT/'tests'),top_level_dir=str(ROOT)) if args.suite=='backend' else loader.loadTestsFromName('tests.gui_regressions')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    data = dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                skipped=len(result.skipped),expected_failures=len(result.expectedFailures),
                unexpected_successes=len(result.unexpectedSuccesses),successful=result.wasSuccessful())
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(data,indent=2)+'\n',encoding='utf8')
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':sys.exit(main())
