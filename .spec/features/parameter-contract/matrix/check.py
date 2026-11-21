"""parameter-contract falsifiable check: does every row meet the proposed shape?

Reads out.json (from gen.py). A row fails when any predicate below fails:

  verdict   observed verdict (first token) != proposed verdict (first token)
  uncaught  any call ended in a traceback or `Error: <Name>Error: ...`
  complete  completion offers the probed spelling iff --help shows it (hidden → neither)
  identity  info schema property/required == MCP property/required
  array     a list/tuple parameter that is accepted publishes "type": "array"
  type      an accepted scalar publishes its JSON type (int→integer, float→number,
            bool→boolean, datetime→string/date-time) in every optional form
  required  schema `required` == the CLI refusing the call when it is absent

Exit 0 when no row fails.
"""

from __future__ import annotations

import re
import sys

from analyze import facts, load, verdict
from report import OBS_OVERRIDE, proposed


def main() -> int:
    d, info, mcp, bash, zsh = load()
    fails: dict[str, list[str]] = {}
    for row in d["rows"]:
        rid = row["id"]
        f = facts(row, info, mcp, bash, zsh)
        obs = OBS_OVERRIDE.get(rid, verdict(row, f))
        prop = proposed(rid, row["decl"])
        bad = []
        def base(v: str) -> str:
            return re.match(r"[A-Z_]+", v).group(0)

        if base(obs) != base(prop):
            bad.append("verdict")
        if "UNCAUGHT" in obs or any(
            f[k].startswith("UNCAUGHT") for k in ("k_absent", "k_flag", "k_pos", "k_stdin")
        ):
            bad.append("uncaught")
        hidden = "hidden" in prop or "hidden=True" in row["decl"]
        offered = bool(f["bash"]) or bool(f["zsh"])
        shown = f["help_flag"] and not hidden
        if prop.startswith(("ACCEPTED_FLAG", "CONFIG_FIELD")) and "group level" not in prop:
            if offered != shown:
                bad.append("complete")
        elif offered and "group level" not in prop:
            bad.append("complete")
        if not f["info_eq_mcp"]:
            bad.append("identity")
        accepted = prop.startswith(("ACCEPTED", "CONFIG_FIELD")) and "no flag" not in prop
        coll = bool(re.search(r"\b[pf]: (Annotated\[)?(Optional\[)?(list|tuple)\[", row["label"]))
        if accepted and coll and f["info"] is not None and f["info"].get("type") != "array":
            bad.append("array")
        m = re.match(r"p: (Optional\[)?(int|float|bool|datetime)\b", row["label"])
        if rid.startswith("A") and m and f["info"] is not None:
            want = {"int": {"type": "integer"}, "float": {"type": "number"},
                    "bool": {"type": "boolean"},
                    "datetime": {"type": "string", "format": "date-time"}}[m.group(2)]
            if any(f["info"].get(k) != v for k, v in want.items()):
                bad.append("type")
        if prop.startswith(("ACCEPTED", "CONFIG_FIELD")) and f["info"] is not None:
            a = row["runs"]["absent"]
            cli_req = a["rc"] == 2 and "Missing" in (a["stderr"] + a["stdout"])
            if cli_req != f["info_req"]:
                bad.append("required")
        if bad:
            fails[rid] = bad
    by: dict[str, list[str]] = {}
    for rid, bad in fails.items():
        for b in bad:
            by.setdefault(b, []).append(rid)
    print(f"{len(d['rows'])} rows; {len(fails)} fail the proposed shape")
    for k in ("verdict", "uncaught", "complete", "identity", "array", "type", "required"):
        ids = by.get(k, [])
        print(f"  {k:9} {len(ids):3}  {' '.join(ids)}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
