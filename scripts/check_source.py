"""Offline source checks. CI additionally runs Bandit and pip-audit."""
import ast
import re
from pathlib import Path

root = Path(__file__).resolve().parents[1]
issues = []
for path in sorted((root / "gold").glob("*.py")):
    source = path.read_text()
    for node in ast.walk(ast.parse(source, filename=str(path))):
        if isinstance(node, ast.Call):
            name = ast.unparse(node.func)
            if name in {"eval", "exec", "pickle.loads", "os.system"}:
                issues.append(f"{path.name}:{node.lineno} unsafe {name}")
            if name.endswith((".execute", ".executemany")) and node.args:
                if isinstance(node.args[0], (ast.JoinedStr, ast.BinOp)):
                    issues.append(f"{path.name}:{node.lineno} dynamic SQL")
    if re.search(r'gsk_[a-zA-Z0-9]{24,}', source):
        issues.append(f"{path.name}: possible embedded credential")
if issues:
    raise SystemExit("\n".join(issues))
print("Source checks passed")
