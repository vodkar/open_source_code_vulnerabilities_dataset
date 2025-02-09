from collections import defaultdict
from pathlib import Path

import jedi
import jedi.api

from src.paths import REPOS_PATH


def cut_home_path(path: Path) -> str:
    if str(REPOS_PATH) in path.parts:
        return "/".join(path.parts[path.parts.index(str(REPOS_PATH)) + 1 :])
    return str(path)


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
    code = function.module_path.read_text().split("\n")
    start_pos = start[0]
    while code[start_pos - 2].strip().startswith("@"):
        start_pos -= 1
    line_numbers = list(range(start[0], end[0] + 1))
    body_lines.update(line_numbers)

    parent = function.parent()
    while parent:
        if parent.type == "class" or parent.type == "function":
            start = parent.get_definition_start_position()
            end = parent.defined_names()[0].get_definition_start_position()[0]
            if start is None or end is None:
                print(function.get_line_code())
                print(function)
                raise ValueError("Class definition not found")
            if parent.type == "function":
                while end - 1 < len(code) and "):" not in code[end - 1]:
                    end += 1
            start_pos = start[0]
            while code[start_pos - 2].strip().startswith("@"):
                start_pos -= 1
            line_numbers = list(range(start_pos, end))
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

            try:
                references: list[jedi.api.classes.Name] = script.get_references(
                    line_number, column_number, include_builtins=False
                )
            except AttributeError:
                references = []

            for name in names_no_follow + names + references:
                if name.module_path is None:
                    continue
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
                    or name.type == "property"
                ):
                    if name.get_definition_start_position():
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


def _get_changes_lines_units(
    repo_name: str, file_name: str, fix_changes_line_numbers: list[int]
) -> tuple[str, dict]:
    project = jedi.Project(f"{REPOS_PATH}/{repo_name}")
    script_path = REPOS_PATH / repo_name / file_name
    script = jedi.Script(path=script_path, project=project)
    script_text = script_path.read_text().split("\n")

    functions_body_lines: set[int] = set()
    context_lines: dict[Path, set[int]] = defaultdict(set)
    for fix_line in fix_changes_line_numbers:
        if fix_line in functions_body_lines:
            continue
        if read_lines(script_path, [fix_line])[0].strip().startswith("@"):
            functions_body_lines.add(fix_line)
            continue
        line_context = script.get_context(fix_line)
        if line_context.type == "class" or line_context.type == "function":
            functions_body_lines.update(get_function_body_lines(line_context))
            # for context_file, context_line_numbers in get_function_context(
            #     script, line_context
            # ).items():
            #     context_lines[context_file].update(context_line_numbers)
        elif script_text[fix_line - 1].strip() == "":
            continue
        else:
            names = script.get_names()
            for idx, name in enumerate(names):
                if (
                    name.get_definition_start_position()[0]
                    <= fix_line
                    <= name.get_definition_end_position()[0]
                ):
                    functions_body_lines.update(
                        range(
                            name.get_definition_start_position()[0],
                            name.get_definition_end_position()[0] + 1,
                        )
                    )
                    break
                if name.get_definition_start_position()[0] > fix_line:
                    functions_body_lines.update(
                        range(
                            names[idx - 1].get_definition_end_position()[0] + 1,
                            name.get_definition_start_position()[0],
                        )
                    )
                    break

    code_unit_data = "".join(
        read_lines(f"{REPOS_PATH}/{repo_name}/{file_name}", functions_body_lines)
    )
    context_data = {
        # cut_home_path(Path(file)): "\n".join(read_lines(str(file), lines))
        # for file, lines in context_lines.items()
    }

    return (
        code_unit_data,
        context_data,
    )
