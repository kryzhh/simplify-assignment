"""Quick local source checks. Run with --watch during edits. CI also uses Bandit and pip-audit."""
import argparse
import ast
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def issues_in(path):
    source = path.read_text()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        yield f"{path.name}:{exc.lineno} {exc.msg}"
        return
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = ast.unparse(node.func)
        if name in {"eval", "exec", "pickle.loads", "os.system"}:
            yield f"{path.name}:{node.lineno} unsafe {name}"
        if name.endswith((".execute", ".executemany")) and node.args:
            if isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                yield f"{path.name}:{node.lineno} dynamic SQL"
    if re.search(r'gsk_[a-zA-Z0-9]{24,}', source):
        yield f"{path.name}: possible embedded credential"


def check(watch):
    last = None
    while True:
        paths = sorted((ROOT / "gold").rglob("*.py"))
        snapshot = [(p, p.stat().st_mtime_ns) for p in paths]
        if snapshot != last:
            issues = [msg for path in paths for msg in issues_in(path)]
            print("\n".join(issues) or "Source checks passed", flush=True)
            if not watch:
                return int(bool(issues))
            last = snapshot
        time.sleep(2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    try:
        sys.exit(check(args.watch))
    except KeyboardInterrupt:
        pass
