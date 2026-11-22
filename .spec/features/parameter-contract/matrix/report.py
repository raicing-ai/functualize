"""Render out.json as the parameter-contract matrix document (markdown)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from analyze import clean, facts, load, verdict

FL = "ACCEPTED_FLAG"
PO = "ACCEPTED_POSITIONAL"
IJ = "INJECTED"
CF = "CONFIG_FIELD"
RU = "REJECTED_USAGE"
RD = "REJECTED_DISCOVERY"
IO = "INVOCATION_ONLY"

#: The DI registry the matrix project boots with: `plugin_probe.py` registers `ProvWidget` by
#: type and under qualifier "w", and nothing else (its `str`/"s2" provider exists only with
#: PC_STR_PROVIDER=1, the separate `str-provider.txt` experiment). Every proposed verdict below
#: that depends on provider availability is decided against exactly this set (spec B-2).
MATRIX_PROVIDERS = frozenset({("provlib.ProvWidget", None), ("provlib.ProvWidget", "w")})

# Observed-verdict corrections the mechanical classifier cannot see.
OBS_OVERRIDE = {
    "B078": "ACCEPTED_FLAG (hidden; spelled --tags/-t)",
    "D097": "ACCEPTED_FLAG (hidden; spelled --tags/-t)",
    "G160": "ACCEPTED_FLAG (group level: func g160g --p … run)",
    "G161": "ACCEPTED_FLAG (group level: func g161g --p … run)",
}


def proposed(rid: str, decl: str) -> str:
    """The intended verdict for a row: spec B-1 to B-9 and page SD/28901379 v5 §5.1, never today's.

    Every value here is **intent**. None is copied from a measurement; the measured verdict is
    `analyze.verdict()`, and `OBS_OVERRIDE` corrects only that *observed* column, for four rows the
    mechanical classifier cannot see (B078, D097, G160, G161). No proposed verdict carries an
    override.

    Corrected 2026-11-22 after Execute found that rows had been encoding the measurement:
    - C081 to C084 (`tuple[str, int]`, `dict[str, str]`, `= {}`, `set[str]`) are
      `INVOCATION_ONLY`, per B-5 (D5 = B'). They had been returning today's `REJECTED_DISCOVERY`.
    - D105 (`Annotated[Widget, Option()]`) is `REJECTED_DISCOVERY`: "a CLI marker on a type
      nothing converts" (B-8); `Widget` is not a B-3 scalar.
    - F150 and F151 (config `dict` / nested model fields) are `REJECTED_DISCOVERY` (B-8, AC-4,
      page "refused at discovery"). They had been `CONFIG_FIELD`, which is today.
    - E138, E139 and H165 are decided by B-2's availability rule against `MATRIX_PROVIDERS`.
      Declared `INJECTED`, they have no provider for their own (type, qualifier), so they are
      `REJECTED_DISCOVERY`. H165 had been `INJECTED`, as if the `str`/"s2" provider were
      registered.

    Availability-dependent rows (declared `INJECTED`, verdict decided by `MATRIX_PROVIDERS`):
    C085, C086, C087, E138, E139, H162 to H166.
    """
    n = int(rid[1:])
    if rid[0] == "A":
        if 49 <= n <= 52:
            return RD
        if rid == "A013":
            return FL + " (schema: not required)"
        return PO if (n - 1) % 4 == 0 else FL
    if rid[0] == "B":
        if rid in ("B065", "B071"):
            return RD
        if rid == "B077":
            return PO
        return FL + " (repeatable)"
    if rid[0] == "C":
        if rid in ("C079", "C080"):
            return FL + " (repeatable, tuple)"
        if rid in ("C081", "C082", "C083", "C084"):
            return IO
        if rid == "C090":
            return PO
        if rid == "C091":
            return FL
        return RD
    if rid[0] == "D":
        return {
            "D092": PO, "D093": PO, "D101": PO,
            "D102": RD, "D103": RD, "D104": RD, "D105": RD,
            "D106": FL + " (repeatable, tuple)",
            "D099": FL + "; absent+no pipe → " + RU,
            "D094": FL + "; absent → " + RU,
        }.get(rid, FL)
    if rid[0] == "E":
        if rid in ("E138", "E139", "E142"):
            return RD
        return IJ
    if rid[0] == "F":
        if rid in ("F150", "F151"):
            return RD
        return CF
    if rid[0] == "H":
        return RD if rid in ("H165", "H166") else IJ
    return {
        "G153": PO, "G154": FL + " (repeatable)", "G155": RD,
        "G156": PO, "G157": PO + " (q: " + FL + ")",
        "G158": FL + " (repeatable)", "G159": FL,
        "G160": FL + " (group level, repeatable)",
        "G161": FL + " (group level)",
    }[rid]


# Finding id -> rows it covers (the findings text lives in the page).
FINDINGS = {
    "F-01": "B053-B064 B066-B070 G154 G157 G158",
    "F-02": "A007 A008 A011 A012 A015 A016 A031 A032 B057-B068 B073 B074 B076 C079-C084 D104 D106 F150 F151",
    "F-03": "A049 B053-B065 B071 C079 C081 C082 C084 C088 C089 G154 G157 G158",
    "F-04": "A022 A038",
    "F-05": "A037 A038 A039 A040",
    "F-06": "A050 A051 A052 B053-B071 B078 C080 C083 C086 D094 D097 D103 F152 G154 G158",
    "F-07": "D094",
    "F-08": "A013",
    "F-09": "D099",
    "F-10": "D106 G160",
    "F-11": "G155",
    "F-12": "G156",
    "F-13": "G160 G161",
    "F-14": "C085 C087 E138 E139 H162-H166",
    "F-15": "D104 F150 F151",
    "F-16": "D102 D103",
    "F-17": "A049 A050 A051 A052",
    "F-18": "G160",
    "F-19": "B073 B074 B072 B075 B076 B077 B078",
}


def expand(spec: str) -> set[str]:
    out = set()
    for tok in spec.split():
        if "-" in tok:
            a, b = tok.split("-")
            for i in range(int(a[1:]), int(b[1:]) + 1):
                out.add(f"{a[0]}{i:03d}")
        else:
            out.add(tok)
    return out


ROW_FINDINGS: dict[str, list[str]] = {}
for fid, spec in FINDINGS.items():
    for r in expand(spec):
        ROW_FINDINGS.setdefault(r, []).append(fid)


def short(kind: str) -> str:
    kind = kind.replace("|", "\\|")
    return kind if len(kind) <= 70 else kind[:67] + "…"


def trim_tb(text: str) -> str:
    lines = text.splitlines()
    if "Traceback" in text and len(lines) > 14:
        keep = lines[-12:]
        return f"[… {len(lines) - 12} earlier traceback lines elided; verbatim in out.json …]\n" + "\n".join(keep)
    return text


def block(run: dict, rid: str) -> str:
    out = clean(run["stdout"], rid.lower())
    err = trim_tb(clean(run["stderr"], rid.lower()))
    body = "\n".join(x for x in (out, err) if x.strip())
    return f"$ {' '.join(run['argv'])}    # exit {run['rc']}\n{body}".rstrip()


def main() -> None:
    d, info, mcp, bash, zsh = load()
    commit = sys.argv[1]
    lines: list[str] = []
    w = lines.append
    w("# parameter-contract matrix — declaration × surface, measured on the real `func`\n")
    w(f"Measured on `raicing-ai/functualize` `master` @ `{commit}` (`git archive`, "
      "`uv sync --frozen --all-extras --all-packages`, `func --version` → `functualize 0.4.0`, "
      "CPython 3.13.15; the same matrix on 3.11.16 and 3.12.14 is compared in `pycompare.txt`), 2026-11-20/21. One job module per row in one directory-mode project; every "
      "row driven through the real `func` binary in a subprocess. Generator, analyzer and this "
      "renderer are attached (`pc-matrix-kit.tar.gz`); `out.json` is the unabridged record "
      "of every command's stdout, stderr and exit code.\n")
    w("**Output filter (disclosed).** Three lines that every command in the project prints are "
      "removed from the transcripts below and kept in `out.json`: the `e142.py not loaded` "
      "warning (row E142's own verdict), plugin-load timing notices (`Plugin '…' took Nms to "
      "load`), and the `registered but cannot run` warnings of rows C085/C087/E138 (kept in "
      "those rows' own blocks). Tracebacks longer than 14 lines keep their last 12 lines.\n")
    w("**Columns.** `help` = the parameter appears in `func <job> --help` (`flag`/`pos`/—); "
      "`bash`/`zsh` = the completion tree entry for the job offers the probed spelling "
      "(— = the job has no entry); `info`/`mcp` = the property published by "
      "`func builtin info schema --kind job` / `func mcp schema` (`req` = listed in "
      "`required`); `absent`/`flag`/`pos` = the job called with nothing, with the flag form, "
      "and with the positional form. `observed` is mechanical from those cells; "
      "`proposed` is this shape's verdict; `findings` cross-reference the page's §3 list.\n")
    w("| id | declaration | observed | proposed | help | bash | zsh | info | mcp | absent | flag | pos | findings |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for row in d["rows"]:
        f = facts(row, info, mcp, bash, zsh)
        rid = row["id"]
        obs = OBS_OVERRIDE.get(rid, verdict(row, f))
        help_cell = "flag" if f["help_flag"] else ("pos" if f["help_pos"] else "—")
        if rid in OBS_OVERRIDE and "hidden" in OBS_OVERRIDE[rid]:
            help_cell = "hidden"

        def sb(v):
            return "—" if v is None else ("yes" if v else "no")

        def sch(p, req):
            if p is None:
                return "—"
            s = json.dumps(p, separators=(",", ":")).replace("|", "\\|")
            return f"`{s}`" + (" req" if req else "")

        label = row["label"].replace("{rid}", rid.lower()).replace("|", "\\|")
        w(f"| {rid} | `{label}` | {obs} | {proposed(rid, row['decl'])} | {help_cell} | "
          f"{sb(f['bash'])} | {sb(f['zsh'])} | {sch(f['info'], f['info_req'])} | "
          f"{sch(f['mcp'], f['mcp_req'])} | {short(f['k_absent'])} | {short(f['k_flag'])} | "
          f"{short(f['k_pos'])} | {' '.join(sorted(ROW_FINDINGS.get(rid, []))) or '—'} |")

    w("\n## Transcripts — every command, every row\n")
    w("Completion lines are the job's entry in the full `func builtin shell-init bash|zsh` "
      "output; schema lines are the job's entry in the full `func builtin info schema --kind "
      "job` / `func mcp schema` output (both full outputs are in `out.json` → `global`).\n")
    g = d["global"]
    for row in d["rows"]:
        rid = row["id"]
        key = ":" + " ".join(row["path"])
        label = row["label"].replace("{rid}", rid.lower())
        w(f"### {rid} — `{label}`\n")
        w("```python\n" + row["module"].strip() + "\n```\n")
        w("```console")
        for k in ("help", "absent", "flag", "pos", "stdin", "envvar"):
            if k in row["runs"]:
                w(block(row["runs"][k], rid))
                w("")
        bl = bash.get(key)
        zl = zsh.get(key)
        w(f"$ func builtin shell-init bash | grep \"_func_tree\\['{key}'\\]\"")
        w(f"_func_tree['{key}']='{' '.join(bl)}'" if bl is not None else "(no entry)")
        w(f"$ func builtin shell-init zsh | grep \"_func_tree\\['{key}'\\]\"")
        w(f"_func_tree['{key}']='{' '.join(zl)}'" if zl is not None else "(no entry)")
        ie = info.get(tuple(row["path"]))
        me = mcp.get(".".join(row["path"]))
        w(f"$ func builtin info schema --kind job   # entry path={row['path']}")
        w(json.dumps(ie["inputSchema"], separators=(",", ":")) if ie else "(no entry)")
        w(f"$ func mcp schema   # entry name={'.'.join(row['path'])}")
        w(json.dumps(me["inputSchema"], separators=(",", ":")) if me else "(no entry)")
        w("```\n")
    Path("pc-matrix.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
