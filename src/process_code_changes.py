import json
import logging
import os
import re
import shutil
import tempfile
import token
import tokenize
from pathlib import Path
from time import sleep
from typing import Any
from uuid import uuid4

import gitlab
import jedi
import jedi.api
import jedi.settings
import whatthepatch
from black import FileMode, format_str
from git import GitCommandError, Repo
from github import Auth, Github

from src.get_changes_lines_units import (
    _get_changes_lines_units,
    cut_home_path,
    read_lines,
)
from src.paths import DATA_PATH, REPOS_PATH

# jedi.settings.fast_parser = False

_AUTH = Auth.Token(os.environ["GITHUB_TOKEN"])
_GITHUB_CLIENT = Github(auth=_AUTH)
_GITLAB = gitlab.Gitlab(private_token=os.environ["GITLAB_TOKEN"])
LOGGING = logging.getLogger(__name__)
ALLOWED_LANGS = [
    "C/C++",
    "HTML",
    "JavaScript/TypeScript",
    "Shell",
    "Jinja2",
]


def git_checkout(repo: Repo, commit: str):
    try:
        repo.git.checkout(commit)
    except GitCommandError:
        repo.git.reset("--hard", commit)
        repo.git.checkout(commit)
    # clear_jedi_cache()
    sleep(0.5)


def clear_jedi_cache():
    shutil.rmtree(jedi.settings.cache_directory, ignore_errors=True)


def remove_comments(content: str) -> str:
    tempfile_name = tempfile.mktemp()
    with open(tempfile_name, "w") as f:
        f.write(content)
    with open(tempfile_name) as source, open(tempfile_name + ",strip", "w") as mod:
        prev_toktype = token.INDENT
        last_lineno = -1
        last_col = 0

        tokgen = tokenize.generate_tokens(source.readline)
        for toktype, ttext, (slineno, scol), (elineno, ecol), ltext in tokgen:
            if 0:  # Change to if 1 to see the tokens fly by.
                print(
                    "%10s %-14s %-20r %r"
                    % (
                        tokenize.tok_name.get(toktype, toktype),
                        "%d.%d-%d.%d" % (slineno, scol, elineno, ecol),
                        ttext,
                        ltext,
                    )
                )
            if slineno > last_lineno:
                last_col = 0
            if scol > last_col:
                mod.write(" " * (scol - last_col))
            if toktype == token.STRING and prev_toktype == token.INDENT:
                continue
            elif toktype == tokenize.COMMENT:
                continue
            else:
                mod.write(ttext)
            prev_toktype = toktype
            last_col = ecol
            last_lineno = elineno

    with open(tempfile_name + ",strip") as f:
        return f.read()


def clear_file_content(content: str):
    new_content = remove_comments(content)
    try:
        new_content = format_str(new_content, mode=FileMode())
    except:
        # If comments removing broke syntax, we dont remove commits.
        new_content = format_str(content, mode=FileMode())
    return re.sub(r"\n\s*\n", "\n", new_content)


def get_changes(commit_data_row: dict[str, Any]) -> None:
    fix_commit = commit_data_row["commit"]
    repo_name = commit_data_row["repo"]
    commit_data_row["temp_id"] = [uuid4() for _ in range(len(commit_data_row["file"]))]

    try:
        if os.path.exists(f"{REPOS_PATH}/{repo_name}"):
            local_repo = Repo(f"{REPOS_PATH}/{repo_name}")
        elif commit_data_row["commit_source"] == "github":
            repo = _GITHUB_CLIENT.get_repo(repo_name)
            local_repo = Repo.clone_from(repo.clone_url, f"{REPOS_PATH}/{repo_name}")
        elif commit_data_row["commit_source"] == "gitlab":
            repo = _GITLAB.projects.get(repo_name)
            local_repo = Repo.clone_from(
                repo.ssh_url_to_repo, f"{REPOS_PATH}/{repo_name}"
            )

        try:
            fix_commit = local_repo.commit(fix_commit)
        except ValueError:
            return
        git_checkout(local_repo, fix_commit)
        previous_commit = local_repo.head.commit.parents[0]

        new_old_file = {}
        deleted_old_files = set()
        for file, stats in fix_commit.stats.files.items():
            if stats["change_type"] == "M":
                new_old_file[file] = Path(file)
            elif stats["change_type"] == "A":
                new_old_file[file] = None
            elif stats["change_type"] == "D":
                deleted_old_files.add(file)
            else:
                new_old_file[file] = None
                raise Exception("File not found")

        after_fix_data = {}
        after_fix_context_data = {}
        for patch, file, language, temp_id in zip(
            commit_data_row["patch"],
            commit_data_row["file"],
            commit_data_row["language"],
            commit_data_row["temp_id"],
        ):
            diffs = whatthepatch.parse_patch(patch)

            fix_changes_line_numbers: list[int] = []
            previous_changes_line_numbers: list[int] = []
            for diff in diffs:
                for change in diff.changes:
                    if change.new is None:
                        previous_changes_line_numbers.append(change.old)
                    elif change.old is None:
                        fix_changes_line_numbers.append(change.new)
                    # Ignore unchanged lines

            if language == "Python":
                if file not in deleted_old_files:
                    code_unit_after_fix, code_context_after_fix = (
                        _get_changes_lines_units(
                            repo_name, file, fix_changes_line_numbers
                        )
                    )
                    code_context_after_fix = clear_file_content(code_unit_after_fix)
                    code_unit_after_fix = clear_file_content(code_unit_after_fix)
                else:
                    code_unit_after_fix = ""
                    code_context_after_fix = {}
            elif language in ALLOWED_LANGS:
                if file not in deleted_old_files:
                    code_unit_after_fix = "".join(
                        read_lines(
                            f"{REPOS_PATH}/{repo_name}/{file}",
                            set(fix_changes_line_numbers),
                        )
                    )
                    code_context_after_fix = {file: code_unit_after_fix}
                else:
                    code_unit_after_fix = ""
                    code_context_after_fix = {}
            else:
                continue

            after_fix_data[temp_id] = {
                "commit": str(fix_commit),
                "repo": repo_name,
                "new_file": file,
                "patch": patch,
                "code_unit_after_fix": code_unit_after_fix,
                "vulnerability_id": commit_data_row["vulnerability_id"],
                "cwe_id": commit_data_row["cwe_id"],
            }
            after_fix_context_data[temp_id] = {
                "commit": str(fix_commit),
                "repo": repo_name,
                "new_file": file,
                "patch": patch,
                "code_context_after_fix": code_context_after_fix,
                "vulnerability_id": commit_data_row["vulnerability_id"],
                "cwe_id": commit_data_row["cwe_id"],
            }

        git_checkout(local_repo, previous_commit)
        before_fix_data = {}
        before_fix_context_data = {}
        for patch, file, language, temp_id in zip(
            commit_data_row["patch"],
            commit_data_row["file"],
            commit_data_row["language"],
            commit_data_row["temp_id"],
        ):
            diffs = whatthepatch.parse_patch(patch)

            fix_changes_line_numbers: list[int] = []
            previous_changes_line_numbers: list[int] = []
            for diff in diffs:
                for change in diff.changes:
                    if change.new is None:
                        previous_changes_line_numbers.append(change.old)
                    elif change.old is None:
                        fix_changes_line_numbers.append(change.new)
                    # Ignore unchanged lines

            if file in deleted_old_files:
                old_file = Path(file)
            else:
                old_file = new_old_file[file]

            if language == "Python":
                if old_file:
                    code_unit_before_fix, code_context_before_fix = (
                        _get_changes_lines_units(
                            repo_name, old_file, previous_changes_line_numbers
                        )
                    )
                    code_unit_before_fix = clear_file_content(code_unit_before_fix)
                else:
                    code_unit_before_fix = ""
                    code_context_before_fix = {}
            elif language in ALLOWED_LANGS:
                if old_file:
                    code_unit_before_fix = "".join(
                        read_lines(
                            f"{REPOS_PATH}/{repo_name}/{old_file}",
                            set(previous_changes_line_numbers),
                        )
                    )
                    code_context_before_fix = {
                        cut_home_path(old_file): code_unit_before_fix
                    }
                else:
                    code_unit_before_fix = ""
                    code_context_before_fix = {}
            else:
                continue

            before_fix_data[temp_id] = {
                "commit": str(fix_commit),
                "repo": repo_name,
                "old_file": cut_home_path(old_file) if old_file else None,
                "patch": patch,
                "code_unit_before_fix": code_unit_before_fix,
                "vulnerability_id": commit_data_row["vulnerability_id"],
                "cwe_id": commit_data_row["cwe_id"],
            }
            before_fix_context_data[temp_id] = {
                "commit": str(fix_commit),
                "repo": repo_name,
                "old_file": cut_home_path(old_file) if old_file else None,
                "patch": patch,
                "code_context_before_fix": code_context_before_fix,
                "vulnerability_id": commit_data_row["vulnerability_id"],
                "cwe_id": commit_data_row["cwe_id"],
            }

        result_directory = DATA_PATH / "code_units" / str(fix_commit)

        for after_fix_id, after_fix in after_fix_data.items():
            before_fix = before_fix_data[after_fix_id]
            result_file = (
                result_directory
                / f"{after_fix['new_file'] or before_fix['old_file']}.json"
            )
            fix_data = after_fix | before_fix

            result_file.parent.mkdir(parents=True, exist_ok=True)
            with result_file.open("w") as f:
                f.write(json.dumps(fix_data))

        # result_directory = DATA_PATH / "context" / str(fix_commit)
        # for after_fix_context_id, after_fix_context in after_fix_context_data.items():
        #     before_fix_context = before_fix_context_data[after_fix_context_id]
        #     result_file = (
        #         result_directory
        #         / f"{after_fix_context['new_file'] or before_fix_context['old_file']}.json"
        #     )
        #     fix_context_data = after_fix_context | before_fix_context
        #     del fix_context_data["temp_id"]

        #     result_file.parent.mkdir(parents=True, exist_ok=True)
        #     with result_file.open("w") as f:
        #         f.write(json.dumps(fix_context_data))

    except Exception:
        LOGGING.error(f"Error processing commit {fix_commit}")
        LOGGING.error(commit_data_row)
        raise
