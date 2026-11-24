"""Cross-surface predicates over surf_analyze.table(). Prints counts and row ids.

W-inject   a caller-supplied value replaced an injected/provided parameter
W-type     a supplied value reached the job as a different type than the CLI delivers
W-default  an omitted parameter reached the job as something other than the CLI's default
W-crash    an omitted required parameter ended in a raw TypeError/500 instead of a refusal
W-accept   one surface accepts the supplied value and another refuses it (both measured)
W-fat      Lambda's documented fat event {"job","kwargs"} ignored its kwargs
W-bar      SmartBar flag set != the flags `func <job> --help` shows
W-collapse a repeated flag in the TUI reached the job as one value
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from surf_analyze import table

out = json.loads(Path("out.json").read_text())
HELP = {r["id"]: r["runs"]["help"]["stdout"] for r in out["rows"]}
#: The probed parameter's own annotation: W-collapse is about the value the job
#: is observed receiving, so a row whose *other* parameter is a list (G157's
#: `q`) is not a collapse of the probed `p: str`.
PROBE_DECL = {
    r["id"]: (m.group(1) if (m := re.search(rf"\b{r['probe']}: ([^=]+?)(?:,\s*\w+:|=|$)", r["decl"])) else r["decl"])
    for r in out["rows"]
}
INJECTED_ROWS = {f"E{n:03d}" for n in range(108, 142)} | {"H162", "H163", "H164", "H165"}
WIRE = ("tui_given", "mcp_given", "http_given", "lambda_given")
#: `INVOCATION_ONLY` rows (the declaration table's verdict): a command line has
#: no spelling for them, so the CLI and TUI refusal is by design (spec B-15) and
#: W-accept does not count those two cells.
INVOCATION_ONLY_ROWS = {"C081", "C082", "C083", "C084"}
COMMAND_LINE_CELLS = ("cli_given", "tui_given")


def typ(cell: str) -> str | None:
    m = re.match(r"(?:\d{3} )?ok:(\w+)=", cell)
    return m.group(1) if m else None


def val(cell: str) -> str | None:
    m = re.match(r"(?:\d{3} )?ok:\w+=(.*)$", cell)
    return m.group(1) if m else None


def help_flags(text: str) -> set[str]:
    sect = text.split("Options:", 1)[-1]
    found = set(re.findall(r"(?<![\w-])(--[a-z][\w-]*)", sect)) - {"--help"}
    return found


def main() -> None:
    res: dict[str, dict[str, list[str]]] = {}

    def add(pred: str, surface: str, rid: str) -> None:
        res.setdefault(pred, {}).setdefault(surface, []).append(rid)

    for r in table():
        rid = r["id"]
        if rid in INJECTED_ROWS:
            for k in WIRE:
                if typ(r[k]) == "str" and "'x'" in (val(r[k]) or ""):
                    add("W-inject", k, rid)
        ct = typ(r["cli_given"])
        if ct and rid not in INJECTED_ROWS:
            for k in WIRE:
                t = typ(r[k])
                if t and t != ct and not (ct == "PosixPath" and t == "PosixPath"):
                    add("W-type", k, rid)
        ca = r["cli_absent"]
        if typ(ca) and rid not in INJECTED_ROWS:
            for k in ("tui_absent", "mcp_absent", "http_absent", "lambda_absent"):
                if typ(r[k]) and val(r[k]) != val(ca):
                    add("W-default", k, rid)
                elif not typ(r[k]) and r[k] not in ("—",) and not r[k].startswith("server"):
                    add("W-default", k + "(not delivered)", rid)
        for k in ("tui_absent", "http_absent", "lambda_absent", "mcp_absent", "cli_absent"):
            c = r[k]
            if re.search(r"missing \d+ required (positional|keyword-only) argument", c):
                add("W-crash", k, rid)
        accepted = {k for k in ("cli_given", *WIRE) if typ(r[k])}
        refused = {k for k in ("cli_given", *WIRE) if r[k].startswith(("refused", "fail", "500", "400"))}
        if rid in INVOCATION_ONLY_ROWS:
            refused -= set(COMMAND_LINE_CELLS)
        if accepted and refused:
            add("W-accept", "+".join(sorted(accepted)) + " vs " + "+".join(sorted(refused)), rid)
        fat, absent, given = r["lambda_fat_kwargs"], r["lambda_absent"], r["lambda_given"]
        if fat != "—" and fat == absent and given != absent:
            add("W-fat", "lambda", rid)
        bar = set(w for w in r["smartbar"].split() if w.startswith("--"))
        if r["smartbar"] not in ("—",) and not r["smartbar"].startswith("fail"):
            hf = help_flags(HELP[rid])
            if not r["id"].startswith("G16") and bar != hf:
                add("W-bar", f"bar={' '.join(sorted(bar)) or '∅'} help={' '.join(sorted(hf)) or '∅'}", rid)
        tg = r["tui_given"]
        if re.search(r"(list|tuple)", PROBE_DECL.get(rid, r["label"])) and (typ(tg) == "str" or re.match(r"ok:list=\['\w+'\]$", tg)):
            add("W-collapse", "tui", rid)

    for pred in ("W-inject", "W-type", "W-default", "W-crash", "W-accept", "W-fat", "W-bar", "W-collapse"):
        by = res.get(pred, {})
        total = sorted({x for v in by.values() for x in v})
        print(f"{pred}: {len(total)} rows")
        for surf, ids in sorted(by.items(), key=lambda kv: -len(kv[1])):
            print(f"   {surf:60} {len(ids):3}  {' '.join(sorted(ids))}")


if __name__ == "__main__":
    main()
