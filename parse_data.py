from typing import Any

import polars as pl
from git import Repo
from tqdm import tqdm

from src.paths import (
    PYTHON_CODE_FIXES_DATA_PATH,
    PYTHON_CODE_FIXES_WITH_CONTEXT_DATA_PATH,
    PYTHON_VULNERABILITY_FIXES_DATA_PATH,
)
from src.process_code_changes import get_changes

# python_commit_data = commit_data_only_top_langs.filter(pl.col("language") == "Python")
python_vulnerability_fixes = pl.read_parquet(PYTHON_VULNERABILITY_FIXES_DATA_PATH)
print(python_vulnerability_fixes.unique("vulnerability_id").shape[0])
python_vulnerability_fixes = python_vulnerability_fixes.group_by(
    "vulnerability_id",
    "repo",
    "commit",
    "pull_request_number",
    "file",
    "patch",
    "patch_time",
    "commit_source",
    "file_extension",
    "language",
).agg(pl.col("cwe_id"))
python_vulnerability_fixes = python_vulnerability_fixes.unique("patch")
print(python_vulnerability_fixes.unique("vulnerability_id").shape[0])

python_vulnerability_fixes = python_vulnerability_fixes.filter(
    (
        pl.col("file").str.contains(r"\/{0,1}[tT][eE][sS][tT][sS]{0,1}\/")
        | pl.col("patch").str.contains("pytest")
        | pl.col("patch").str.contains("unittest")
    ).not_()
)
python_vulnerability_fixes.unique("vulnerability_id").shape[0]

exclude_langs = [
    "txt",
    "md",
    "JSON",
    "YAML",
    "bugfix",
    "cfg",
    "rst",
    "toml",
    "lock",
    "ini",
    "in",
    "gitignore",
    "sample",
    "pem",
    "feature",
    "tif",
    "security",
    "proto",
    "conf",
    "spec",
    "bin",
    "misc",
    "pyi",
    "pxi",
    "fli",
    "gif",
    "tpl",
    "graphql",
    "http",
    "sgi",
    "pyx",
    "inc",
]
python_vulnerability_fixes = python_vulnerability_fixes.filter(
    (pl.col("file").str.split(".").list.last().is_in(exclude_langs)).not_()
)
python_vulnerability_fixes.unique("vulnerability_id").shape[0]

print(python_vulnerability_fixes.filter(pl.col("commit").is_null()))
python_vulnerability_fixes = python_vulnerability_fixes.with_columns(
    pl.when(pl.col("pull_request_number") == 24391)
    .then(pl.lit("86664c9405136a4904775c52e6caf100a474ec58"))
    .otherwise(pl.col("commit"))
    .alias("commit")
)
print(python_vulnerability_fixes.filter(pl.col("commit").is_null()))
# No changes related to python: https://github.com/pyca/pyopenssl/commit/6bbf44a00b35fb28df1f66aa194b2fe95eab1ab2
# Very big change: https://github.com/transifex/transifex-client/commit/e0d1f8b38ec1a24e2999d63420554d8393206f58
python_vulnerability_fixes = python_vulnerability_fixes.filter(
    ~pl.col("commit").is_in(
        [
            "6bbf44a00b35fb28df1f66aa194b2fe95eab1ab2",
            "e0d1f8b38ec1a24e2999d63420554d8393206f58",
        ]
    )
)
print(python_vulnerability_fixes.filter(pl.col("commit").is_null()))
python_vulnerability_fixes.unique("vulnerability_id").shape[0]

if PYTHON_CODE_FIXES_DATA_PATH.exists():
    print("Reading code fixes")
    code_unit_changes = pl.read_parquet(PYTHON_CODE_FIXES_DATA_PATH).to_dicts()
else:
    code_unit_changes: list[dict[str, Any]] = []

if PYTHON_CODE_FIXES_WITH_CONTEXT_DATA_PATH.exists():
    print("Reading code fixes with context")
    code_context_changes = pl.read_parquet(
        PYTHON_CODE_FIXES_WITH_CONTEXT_DATA_PATH
    ).to_dicts()
else:
    code_context_changes: list[dict[str, Any]] = []

repos: dict[str, Repo] = {}

grouped_vulnerabilities = (
    python_vulnerability_fixes.group_by(
        "repo", "vulnerability_id", "commit", "commit_source", "cwe_id"
    )
    .agg(pl.col("patch"), pl.col("file"), pl.col("language"))
    .sample(fraction=1, shuffle=True)
)
errors: list[dict[str, Any]] = []
checked_commits = set([change["commit"] for change in code_unit_changes])


# grouped_by_repos = grouped_vulnerabilities.group_by("repo").agg(
#     pl.col("vulnerability_id"),
#     pl.col("commit"),
#     pl.col("commit_source"),
#     pl.col("cwe_id"),
#     pl.col("patch"),
#     pl.col("file"),
#     pl.col("language"),
# )
# params = []
# for row in grouped_by_repos.iter_rows(named=True):
#     params_rows = []
#     for i in range(len(row["vulnerability_id"])):
#         params_rows.append(
#             {
#                 "repo": row["repo"],
#                 "vulnerability_id": row["vulnerability_id"][i],
#                 "commit": row["commit"][i],
#                 "commit_source": row["commit_source"][i],
#                 "cwe_id": row["cwe_id"][i],
#                 "patch": row["patch"][i],
#                 "file": row["file"][i],
#                 "language": row["language"][i],
#             }
#         )
#     params.append(params_rows)


# def process(repo_vulnerabilities):
#     for commit_data_row in repo_vulnerabilities:
#         get_changes(commit_data_row)


# multiprocessing.set_start_method("fork")

# with multiprocessing.Pool() as pool:
#     pool.map(process, params)


vulnerabilities_to_check = grouped_vulnerabilities.to_dicts()


for commit_data_row in tqdm(vulnerabilities_to_check):
    if commit_data_row["commit"] == "32de2154ef9f946160e5dc01a4d8a449dd0bd259":
        get_changes(commit_data_row)
