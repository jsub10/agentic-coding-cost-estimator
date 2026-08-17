"""Import allowlist. NumPy and the standard library, and nothing else (CLAUDE.md §2).

NumPy is permitted because the Monte Carlo is genuinely vectorisable and the speed buys
larger iteration counts. Anything beyond it is a sign the model is being complicated rather
than the code — so this is checked mechanically rather than trusted.
"""

from __future__ import annotations

import ast
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent

ALLOWED_THIRD_PARTY = {"numpy"}

# Standard-library modules this project may use. Kept explicit rather than probed, so that
# adding one is a deliberate act.
ALLOWED_STDLIB = {"__future__", "argparse", "ast", "json", "math", "pathlib",
                  "sys", "time", "itertools", "collections"}

LOCAL = {"params", "scenarios", "model", "montecarlo", "report", "reference"}

TEST_ONLY = {"pytest"}


def imported_names(path):
    """Every top-level module name imported by a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


# reference_model.py ships with the repository as the *supplied* reference to check the
# build against. It is not project source, so it is excluded from every rule here.
NOT_PROJECT_SOURCE = {"reference_model.py"}


def source_files():
    return sorted(path for path in ROOT.glob("*.py")
                  if path.name not in NOT_PROJECT_SOURCE)


def test_source_files_were_found():
    """Guards the rest of this file against silently checking nothing."""
    found = {path.name for path in source_files()}
    assert found == {"params.py", "scenarios.py", "model.py", "montecarlo.py",
                     "report.py", "__main__.py"}, found


@pytest.mark.parametrize("path", source_files(), ids=lambda p: p.name)
def test_no_unexpected_imports(path):
    allowed = ALLOWED_THIRD_PARTY | ALLOWED_STDLIB | LOCAL
    unexpected = imported_names(path) - allowed
    assert not unexpected, f"{path.name} imports {sorted(unexpected)}"


@pytest.mark.parametrize("banned", ["pandas", "scipy", "matplotlib", "seaborn",
                                    "plotly", "sklearn", "statsmodels", "random"])
def test_banned_libraries_are_not_imported(banned):
    """CLAUDE.md §2 and §8: no pandas, no scipy, no plotting, no global `random`."""
    for path in source_files():
        assert banned not in imported_names(path), f"{path.name} imports {banned}"


def test_params_imports_nothing_from_this_project():
    """CLAUDE.md §3: params.py sits at the bottom of the dependency order."""
    assert not imported_names(ROOT / "params.py") & LOCAL


def test_dependency_direction_is_one_way():
    """CLAUDE.md §3: __main__ -> report -> montecarlo -> model -> scenarios -> params."""
    order = ["params", "scenarios", "model", "montecarlo", "report", "__main__"]
    rank = {name: index for index, name in enumerate(order)}
    for path in source_files():
        this = rank[path.stem]
        for name in imported_names(path) & LOCAL:
            assert rank[name] < this, (
                f"{path.name} imports {name}, which is not below it in the order")


def test_model_and_montecarlo_do_no_io():
    """CLAUDE.md §8: no I/O in model.py or montecarlo.py, not even logging."""
    forbidden = {"open", "print", "input"}
    for name in ("model.py", "montecarlo.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        called = {node.func.id for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert not called & forbidden, f"{name} calls {sorted(called & forbidden)}"
        assert "logging" not in imported_names(ROOT / name)


def test_report_does_no_computation_on_arrays():
    """CLAUDE.md §10: report.py never touches a NumPy array, so it never imports one."""
    assert "numpy" not in imported_names(ROOT / "report.py")


def test_reference_uses_no_numpy():
    """CLAUDE.md §7: the differential reference must be structurally unlike the model."""
    reference = ROOT / "tests" / "reference.py"
    assert "numpy" not in imported_names(reference)


def test_no_classes_are_defined():
    """The owner's instruction, recorded in SPEC.md §11: plain functions and dicts only."""
    offenders = []
    for path in source_files() + [ROOT / "tests" / "reference.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        offenders += [f"{path.name}:{node.name}" for node in ast.walk(tree)
                      if isinstance(node, ast.ClassDef)]
    assert not offenders, f"classes defined: {offenders}"


def test_python_is_recent_enough():
    """CLAUDE.md §2: Python 3.11+."""
    assert sys.version_info >= (3, 11)
