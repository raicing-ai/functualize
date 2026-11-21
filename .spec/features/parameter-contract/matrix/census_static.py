"""Static reference census for the symbols that derive a parameter's kind, type,
requiredness or flag spelling. Run from the repository root.

For each symbol: where it is defined, how many production references it has
(src/ + plugins/*/*/src, definition line excluded) and how many test references
(tests/ + plugins/*/*/tests). Every number is an `rg -w` count; the command is
printed with it.
"""

from __future__ import annotations

import subprocess

# (symbol, defining file) — the hit set of the derivation-vocabulary search
SYMBOLS = [
    ("parse_annotation", "src/functualize/_cli/annotation_utils.py"),
    ("CLI_COMPATIBLE_TYPES", "src/functualize/_cli/annotation_utils.py"),
    ("_is_di_type", "src/functualize/_cli/annotation_utils.py"),
    ("_is_basemodel_subclass", "src/functualize/_cli/annotation_utils.py"),
    ("is_cli_value_type", "src/functualize/_primitives/parameter_types.py"),
    ("has_explicit_cli_marker", "src/functualize/_primitives/parameter_types.py"),
    ("CLI_VALUE_TYPE_NAMES", "src/functualize/_primitives/parameter_types.py"),
    ("CLI_MARKER_TYPE_NAMES", "src/functualize/_primitives/parameter_types.py"),
    ("INJECTED_PARAM_TYPE_NAMES", "src/functualize/_primitives/capability_names.py"),
    ("_click_type_for", "src/functualize/app/adapters/click_params.py"),
    ("_field_click_type", "src/functualize/app/adapters/click_params.py"),
    ("build_click_params", "src/functualize/app/adapters/click_params.py"),
    ("build_click_params_from_fields", "src/functualize/app/adapters/click_params.py"),
    ("build_click_params_from_descriptor", "src/functualize/app/adapters/click_params.py"),
    ("_option_from_marker", "src/functualize/app/adapters/click_params.py"),
    ("_config_field_option", "src/functualize/app/adapters/click_params.py"),
    ("_config_option_params", "src/functualize/app/adapters/click_params.py"),
    ("_unwrap_optional", "src/functualize/_config/job_config.py"),
    ("_unwrap_list", "src/functualize/_config/job_config.py"),
    ("unwrap_optional_type", "src/functualize/app/utils.py"),
    ("TYPE_MAP", "src/functualize/_primitives/job_schema.py"),
    ("field_property", "src/functualize/_primitives/job_schema.py"),
    ("job_input_schema", "src/functualize/_primitives/job_schema.py"),
    ("_annotation_to_type_str", "src/functualize/_discovery/providers.py"),
    ("_JSON_SCHEMA_TYPE_MAP", "src/functualize/_discovery/schema_extractor.py"),
    ("_TYPE_MAP", "src/functualize/_cli/tui/type_hint_formatter.py"),
    ("_TYPE_MAP", "plugins/adapters/functualize-mcp/src/functualize_mcp/_server.py"),
    ("_TS_TYPE_MAP", "plugins/adapters/functualize-mcp/src/functualize_mcp/_schema_export.py"),
    ("_build_tool_function", "plugins/adapters/functualize-mcp/src/functualize_mcp/_server.py"),
    ("_build_input_schema", "plugins/adapters/functualize-mcp/src/functualize_mcp/_translator.py"),
    ("_merge_group_options", "plugins/adapters/functualize-mcp/src/functualize_mcp/_translator.py"),
    ("build_resolution_plan", "src/functualize/_engine/resolution.py"),
    ("parse_cli_args_to_kwargs", "src/functualize/_cli/tui/cli_arg_parser.py"),
    ("_candidates_flag", "src/functualize/_cli/tui/smart_bar_autocomplete.py"),
    ("_extract_short_names", "src/functualize/_cli/tui/smart_bar_autocomplete.py"),
    ("_cached_positional_params", "src/functualize/_cli/tui/smart_bar_autocomplete.py"),
    ("filter_used_flags", "src/functualize/_cli/completions/flag_filtering.py"),
    ("request_from_envelope", "src/functualize/_types/run_request.py"),
]

PROD = ["src", "plugins/adapters", "plugins/domains", "plugins/substrates", "plugins/credentials"]


def rg(sym: str, paths: list[str], globs: list[str]) -> list[str]:
    cmd = ["rg", "-n", "-w", "--no-heading", sym, *paths, "-g", "*.py", *sum((["-g", g] for g in globs), [])]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return [ln for ln in p.stdout.splitlines() if ln.strip()]


def main() -> None:
    print("symbol | defined in | def line | prod refs | test refs | prod files")
    for sym, file in SYMBOLS:
        prod = [h for h in rg(sym, PROD, ["!**/tests/**"])
                if not h.startswith("plugins/") or "/src/" in h.split(":")[0]]
        defs = [h for h in prod if h.split(":")[0] == file and
                (f"def {sym}(" in h or f"{sym}:" in h.split(":", 2)[2][:len(sym) + 12] or
                 f"{sym} =" in h or f"{sym}: " in h)]
        def_line = defs[0].split(":")[1] if defs else "?"
        prod_refs = [h for h in prod if h not in defs[:1]]
        # a module-private name is only meaningfully referenced from its own file
        tests = [h for h in rg(sym, ["tests", "plugins"], []) if "/tests/" in h or h.startswith("tests/")]
        files = sorted({h.split(":")[0] for h in prod_refs})
        short = [f.replace("src/functualize/", "").replace("plugins/adapters/", "") for f in files]
        print(f"{sym} | {file.replace('src/functualize/', '')} | {def_line} | {len(prod_refs)} | "
              f"{len(tests)} | {', '.join(short)}")


if __name__ == "__main__":
    main()
