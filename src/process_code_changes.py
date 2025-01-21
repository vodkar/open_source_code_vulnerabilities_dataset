import json
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import gitlab
import jedi
import jedi.api
import jedi.common
import whatthepatch
from git import Repo
from github import Auth, Github

from src.paths import DATA_PATH

_AUTH = Auth.Token(os.environ["GITHUB_TOKEN"]")
_GITHUB_CLIENT = Github(auth=_AUTH)
_GITLAB = gitlab.Gitlab(private_token=os.environ["GITLAB_TOKEN"])
LOGGING = logging.getLogger(__name__)


def clear_file_content(content: str):
    return re.sub(r"#.+\n", "\n", content)


def clear_file_content_v2(content: str):
    content = re.sub(r"#.+\n", "\n", content)
    return re.sub(r"\n\n", "\n", content)


def read_lines(file: str, line_numbers: set[int]):
    with open(file) as f:
        return [
            line for i, line in enumerate(f.readlines(), start=1) if i in line_numbers
        ]


def get_function_body_lines(function: jedi.api.classes.Name) -> set[int]:
    body_lines: set[int] = set()
    start = function.get_definition_start_position()
    end = function.get_definition_end_position()
    if start is None or end is None:
        if function.type == "module":
            return set()
        print(function.get_line_code())
        print(function.module_path)
        print(function)
        raise ValueError("Function definition not found")
    line_numbers = list(range(start[0], end[0] + 1))
    body_lines.update(line_numbers)

    parent = function.parent()
    while parent:
        if parent.type == "class" or parent.type == "function":
            start = parent.get_definition_start_position()
            end = parent.defined_names()[0].get_definition_start_position()
            if start is None or end is None:
                print(function.get_line_code())
                print(function)
                raise ValueError("Class definition not found")
            line_numbers = list(range(start[0], end[0]))
            body_lines.update(line_numbers)
        elif parent.type == "module":
            break
        else:
            print(parent.module_path)
            print(parent.get_definition_start_position())
            raise NotImplementedError(f"Parent type {parent.type}")
        parent = parent.parent()

    return body_lines


def get_function_context(
    script: jedi.Script, function: jedi.api.classes.Name
) -> dict[Path, set[int]]:
    if function.module_path is None:
        raise ValueError("Module path not found")
    function_body_lines: set[int] = set()
    start = function.get_definition_start_position()
    end = function.get_definition_end_position()
    if start is None or end is None:
        raise ValueError("Function definition not found")

    function_code = function.get_line_code(after=end[0] - start[0])
    context: dict[Path, set[int]] = defaultdict(set)
    for line_number, line_code in enumerate(function_code.split("\n"), start=start[0]):
        function_body_lines.add(line_number)
        for column_number, _ in enumerate(line_code, start=1):
            names: list[jedi.api.classes.Name] = script.goto(
                line_number, column_number, follow_imports=True
            )

            names_no_follow: list[jedi.api.classes.Name] = script.goto(
                line_number,
                column_number,
            )
            for name in names_no_follow + names:
                if name.module_name.split(".")[0] != function.module_name.split(".")[0]:
                    continue
                if name.module_path is None:
                    raise ValueError(f"Module path not found, for {name}")

                line_numbers = set()
                if name.type == "function":
                    line_numbers = get_function_body_lines(name)
                elif name.type == "param":
                    line_numbers.add(line_number)
                elif (
                    name.type == "statement"
                    or name.type == "class"
                    or name.type == "instance"
                ):
                    line_numbers.update(
                        range(
                            name.get_definition_start_position()[0],
                            name.get_definition_end_position()[0] + 1,
                        )
                    )
                elif name.type == "module":
                    # script_path = name.module_path
                    # context[script_path].update(get_function_body_lines(name))
                    line_numbers.update(get_function_body_lines(name))
                else:
                    print(line_number, column_number)
                    print(name.module_path)
                    raise NotImplementedError(f"Name type {name.type}", name)

                if name.module_path == function.module_path:
                    function_body_lines.update(line_numbers)
                # if not part of current file
                else:
                    context[name.module_path].update(line_numbers)

    context[function.module_path].update(function_body_lines)
    return context


def get_changes_lines_units(
    repo_name: str, file_name: str, fix_changes_line_numbers: list[int]
) -> tuple[str, dict[Path, str]]:
    project = jedi.Project(f"repos/{repo_name}")
    script = jedi.Script(path=f"repos/{repo_name}/{file_name}", project=project)

    functions_body_lines: set[int] = set()
    context_lines: dict[Path, set[int]] = defaultdict(set)
    for fix_line in fix_changes_line_numbers:
        if fix_line in functions_body_lines:
            continue
        line_context = script.get_context(fix_line)
        if line_context.type == "class":
            functions_body_lines.update(get_function_body_lines(line_context))
            for context_file, context_line_numbers in get_function_context(
                script, line_context
            ).items():
                context_lines[context_file].update(context_line_numbers)
        elif line_context.type == "function":
            functions_body_lines.update(get_function_body_lines(line_context))
            for context_file, context_line_numbers in get_function_context(
                script, line_context
            ).items():
                context_lines[context_file].update(context_line_numbers)
        else:
            functions_body_lines.add(fix_line)

    code_unit_data = "\n".join(
        read_lines(f"repos/{repo_name}/{file_name}", functions_body_lines)
    )
    context_data = {
        Path(file): "\n".join(read_lines(str(file), lines))
        for file, lines in context_lines.items()
    }

    return code_unit_data, context_data


def get_changes(
    commit_data_row: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fix_commit = commit_data_row["commit"]
    repo_name = commit_data_row["repo"]
    code_unit_changes_to_return: list[dict[str, Any]] = []
    code_context_changes_to_return: list[dict[str, Any]] = []

    try:
        if os.path.exists(f"repos/{repo_name}"):
            local_repo = Repo(f"repos/{repo_name}")
        elif commit_data_row["commit_source"] == "github":
            repo = _GITHUB_CLIENT.get_repo(repo_name)
            local_repo = Repo.clone_from(repo.clone_url, f"repos/{repo_name}")
        elif commit_data_row["commit_source"] == "gitlab":
            repo = _GITLAB.projects.get(repo_name)
            local_repo = Repo.clone_from(repo.ssh_url_to_repo, f"repos/{repo_name}")

        fix_commit, previous_commit = list(
            local_repo.iter_commits(fix_commit, max_count=2)
        )[:2]
        new_old_file = {}
        for change in fix_commit.diff(previous_commit):
            new_old_file[change.a_path] = change.b_path

        for patch, file, language in zip(
            commit_data_row["patch"],
            commit_data_row["file"],
            commit_data_row["language"],
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

            old_file = new_old_file[file]
            local_repo.git.checkout(fix_commit)

            if language == "Python":
                code_unit_after_fix, code_context_after_fix = get_changes_lines_units(
                    repo_name, file, fix_changes_line_numbers
                )

                local_repo.git.checkout(previous_commit)
                code_unit_before_fix, code_context_before_fix = get_changes_lines_units(
                    repo_name, old_file, previous_changes_line_numbers
                )
            else:
                code_unit_after_fix = clear_file_content(
                    "\n".join(
                        read_lines(
                            f"repos/{repo_name}/{file}", set(fix_changes_line_numbers)
                        )
                    )
                )
                code_context_after_fix = {file: code_unit_after_fix}

                local_repo.git.checkout(previous_commit)
                code_unit_before_fix = clear_file_content(
                    "\n".join(
                        read_lines(
                            f"repos/{repo_name}/{old_file}",
                            set(previous_changes_line_numbers),
                        )
                    )
                )
                code_context_before_fix = {old_file: code_unit_before_fix}

            result_path = DATA_PATH / "code_units" / f"{fix_commit}.json"
            with open(result_path, "w") as f:
                f.write(
                    json.dumps(
                        {
                            "commit": fix_commit,
                            "repo": repo_name,
                            "old_file": old_file,
                            "new_file": file,
                            "patch": patch,
                            "code_unit_before_fix": clear_file_content(
                                code_unit_before_fix
                            ),
                            "code_unit_after_fix": clear_file_content(
                                code_unit_after_fix
                            ),
                        }
                    )
                )

            result_context_path = DATA_PATH / "context" / f"{fix_commit}.json"
            with open(result_context_path, "w") as f:
                f.write(
                    json.dumps(
                        {
                            "commit": fix_commit,
                            "repo": repo_name,
                            "old_file": old_file,
                            "new_file": file,
                            "patch": patch,
                            "code_context_before_fix": code_context_after_fix,
                            "code_context_after_fix": code_context_before_fix,
                        }
                    )
                )

    except Exception as e:
        LOGGING.error(f"Error processing commit {fix_commit}")
        return e
