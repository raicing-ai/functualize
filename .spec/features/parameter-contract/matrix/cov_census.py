"""Which parameter-derivation functions did the real surfaces execute?

Reads cov/coverage.json (the whole 166-row matrix — CLI, completion, info, MCP
schema + serve, HTTP serve, Lambda, TUI door, SmartBar, config rungs — run under
`coverage run`). For each target function: statements executed / statements.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

SRC = Path("../src").resolve()
COV = json.loads(Path("cov/coverage.json").read_text())
FILES = {str(Path(k).resolve()): v for k, v in COV["files"].items()}

TARGETS = {
    "src/functualize/_cli/annotation_utils.py": ["parse_annotation", "_is_di_type", "_is_basemodel_subclass"],
    "src/functualize/_primitives/parameter_types.py": ["is_cli_value_type", "has_explicit_cli_marker"],
    "src/functualize/app/adapters/click_params.py": [
        "_click_type_for", "_resolve_type_string", "_field_click_type", "build_click_params_from_descriptor",
        "build_click_params_from_fields", "_config_field_option", "_config_option_params",
        "_option_from_marker", "build_click_params", "_get_list_inner_type"],
    "src/functualize/_config/job_config.py": ["_unwrap_optional", "_unwrap_list", "validate_job_config_types"],
    "src/functualize/_discovery/providers.py": ["_annotation_to_type_str", "_unwrap_optional", "_base_type_name"],
    "src/functualize/_discovery/schema_extractor.py": [
        "extract_field_descriptors", "_map_json_schema_type", "_type_from_annotation", "_unwrap_optional_annotation"],
    "src/functualize/_discovery/registry.py": ["JobRegistry._extract_descriptors_from_module"],
    "src/functualize/_primitives/job_schema.py": ["field_property", "job_input_schema"],
    "src/functualize/_engine/resolution.py": ["build_resolution_plan", "_is_optional_type"],
    "src/functualize/_engine/executor.py": ["JobExecutionEngine._resolve_di_parameters", "JobExecutionEngine._di_binding_errors"],
    "src/functualize/_cli/completions/data.py": None,
    "src/functualize/_cli/completions/engine.py": ["SwappableCompleter.get_items", "SwappableCompleter.__init__"],
    "src/functualize/_cli/tui/cli_arg_parser.py": ["parse_cli_args_to_kwargs", "resolve_tui_command"],
    "src/functualize/_cli/tui/smart_bar_autocomplete.py": [
        "SmartBarAutoComplete._candidates_flag", "SmartBarAutoComplete._candidates_group_flags",
        "_extract_short_names", "SmartBarAutoComplete._cached_positional_params"],
    "src/functualize/_cli/tui/type_hint_formatter.py": ["format_type_hint"],
    "plugins/adapters/functualize-mcp/src/functualize_mcp/_server.py": ["_build_tool_function"],
    "plugins/adapters/functualize-mcp/src/functualize_mcp/_translator.py": [
        "JobToolTranslator._build_input_schema", "JobToolTranslator._merge_group_options"],
    "plugins/adapters/functualize-mcp/src/functualize_mcp/_schema_export.py": None,
    "src/functualize/_types/run_request.py": ["request_from_envelope"],
}


def functions(path: Path) -> dict[str, tuple[int, int]]:
    tree = ast.parse(path.read_text())
    out: dict[str, tuple[int, int]] = {}

    def walk(node, prefix=""):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = f"{prefix}{ch.name}"
                if not isinstance(ch, ast.ClassDef):
                    out.setdefault(q, (ch.body[0].lineno, ch.end_lineno))
                walk(ch, q + ".")
    walk(tree)
    return out


def main() -> None:
    print("file | function | lines | executed/statements")
    for rel, names in TARGETS.items():
        path = SRC / rel
        rec = FILES.get(str(path))
        if rec is None:
            print(f"{rel} | (file never imported by any surface) | | 0")
            continue
        execd, missing = set(rec["executed_lines"]), set(rec["missing_lines"])
        fns = functions(path)
        if names is None:
            stmts = len(execd | missing)
            print(f"{rel} | (whole module) | | {len(execd)}/{stmts}")
            continue
        for n in names:
            if n not in fns:
                print(f"{rel} | {n} | ? | not found")
                continue
            a, b = fns[n]
            e = sum(1 for ln in execd if a <= ln <= b)
            m = sum(1 for ln in missing if a <= ln <= b)
            print(f"{rel.replace('src/functualize/', '').replace('plugins/adapters/', '')} | {n} | {a}-{b} | {e}/{e + m}")


if __name__ == "__main__":
    main()
