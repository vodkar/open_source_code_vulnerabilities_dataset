import os
import tempfile

import jedi
import polars as pl

from src.paths import PYTHON_CODE_FIXES_DATA_PATH


def try_convert_to_python3(code: str) -> str:
    try:
        file_name = tempfile.mktemp()
        with open(file_name, "w") as temp_file:
            temp_file.write(code)
            temp_file.seek(0)

            os.system(f"2to3 -w {file_name}")
            return "".join(temp_file.readlines())
    except:
        return code


code_unit_changes_df = pl.read_parquet(PYTHON_CODE_FIXES_DATA_PATH)

total = 0
errors_count = 0
bad_commits = set()
for row in code_unit_changes_df.sample(fraction=1, shuffle=True).iter_rows(named=True):
    file_extension = row["new_file"].split(".")[-1]
    if file_extension in {"py", "pyi", "pyx", "pxi"}:
        total += 1
        script = jedi.Script(code=row["code_unit_after_fix"])
        errors = script.get_syntax_errors()
        if errors and row["commit"]:
            python3_code = try_convert_to_python3(row["code_unit_after_fix"])
            script = jedi.Script(code=python3_code)
            errors = script.get_syntax_errors()
            if not errors:
                continue

            # shutil.rmtree(PYTHON_CODE_UNITS_DATA_PATH / row["commit"], ignore_errors=True)
            # shutil.rmtree(PYTHON_CODE_CONTEXT_DATA_PATH / row["commit"], ignore_errors=True)
            print(row["vulnerability_id"], row["repo"], row["new_file"], row["commit"])
            print(row["code_unit_after_fix"])
            print(errors)
            break
            bad_commits.add(row["commit"])
            errors_count += 1

print(errors_count, total)
