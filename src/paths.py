from pathlib import Path

DATA_PATH = Path("data")
REPOS_PATH = Path.home() / "repos"
VULNERABILITY_FIX_COMMITS = DATA_PATH / "vulnerability_fix_commits.csv"

PYTHON_VULNERABILITY_FIXES_DATA_PATH = DATA_PATH / "python_vulnerability_fixes.parquet"
PYTHON_CODE_FIXES_DATA_PATH = (
    DATA_PATH / "python_vulnerability_fixes_code_unit_changes.parquet"
)
PYTHON_CODE_FIXES_WITH_CONTEXT_DATA_PATH = (
    DATA_PATH / "python_vulnerability_fixes_code_context_changes.parquet"
)

PYTHON_CODE_UNITS_DATA_PATH = DATA_PATH / "code_units"
PYTHON_CODE_CONTEXT_DATA_PATH = DATA_PATH / "context"

PYTHON_VULNERABILITIES_WITHOUT_BALANCING = (
    DATA_PATH / "python_vulnerabilities_without_balancing.parquet"
)
FINAL_VULNERABILITIES_DATA_PATH = DATA_PATH / "final_vulnerabilities.parquet"

SYNTHETIC_DATA_PATH = DATA_PATH / "synthetic_data"
