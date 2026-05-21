"""Static checker for task_state SQL scope examples in the repository."""

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage import assert_task_state_sql_scoped  # noqa: E402


def main(argv):
    root = Path(argv[1]) if len(argv) > 1 else Path(".")
    failures = []
    for path in root.rglob("*.py"):
        if any(part.startswith(".") or part == "tests" for part in path.parts):
            continue
        failures.extend(_check_python_file(path))
    for path in root.rglob("*.sql"):
        if any(part.startswith(".") or part == "tests" for part in path.parts):
            continue
        failures.extend(_check_sql_file(path))

    for failure in failures:
        print(failure)
    return 1 if failures else 0


def _check_python_file(path):
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: could not parse Python"]

    failures = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql = node.value
            if "task_state" not in sql.lower():
                continue
            try:
                assert_task_state_sql_scoped(sql)
            except Exception as exc:
                failures.append(f"{path}:{node.lineno}: {exc}")
    return failures


def _check_sql_file(path):
    failures = []
    for offset, statement in enumerate(path.read_text().split(";"), start=1):
        if "task_state" not in statement.lower():
            continue
        try:
            assert_task_state_sql_scoped(statement)
        except Exception as exc:
            failures.append(f"{path}:statement {offset}: {exc}")
    return failures


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
