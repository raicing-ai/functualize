"""parameter-contract probe plugin — installed as .functualize/plugins/pc_probe.py.

Runs inside the real `func` boot, so every surface below sees the app exactly
as `func` built it. It adds:

- the real `functualize_http.HttpServerPlugin` (`func serve --host --port`);
- DI providers for the H-rows (`provlib.ProvWidget` by type and by qualifier
  "w", and `str` by qualifier "s2");
- `func probe surfaces --spec <json> --out <json>`: per row, the Lambda
  handler (thin and fat), the inline TUI's own door (tokenize → resolve →
  parse → RunRequest(surface="tui.inline") → execute) and the SmartBar's own
  candidate source.
"""

from __future__ import annotations

import json
import traceback
from typing import Any


def _result(res: Any) -> dict[str, Any]:
    status = getattr(res, "status", None)
    exc = getattr(res, "exception", None)
    rv = getattr(res, "return_value", None)
    return {
        "status": getattr(status, "value", str(status)),
        "return_value": rv if isinstance(rv, (str, int, float, bool, type(None))) else repr(rv),
        "exception": None if exc is None else f"{type(exc).__name__}: {exc}",
    }


def _guard(fn):
    try:
        return fn()
    except BaseException as e:  # noqa: BLE001 - a probe records every outcome
        tb = traceback.format_exc().strip().splitlines()
        return {"raised": f"{type(e).__name__}: {e}", "traceback_tail": tb[-4:]}


class _State:
    def __init__(self, text: str) -> None:
        self.text = text
        self.cursor_position = len(text)


class Mch242Probe:
    name = "pc-probe"
    version = "1.0.0"
    description = "parameter-contract surface probe (measurement only)."

    def __call__(self, app: Any) -> None:
        self._app = app
        from functualize_http import HttpServerPlugin

        HttpServerPlugin()(app)
        try:
            from provlib import ProvWidget

            app.di.provide(ProvWidget, ProvWidget("prov-by-type"))
            app.di.provide(ProvWidget, ProvWidget("prov-by-qualifier-w"), qualifier="w")
            import os

            if os.environ.get("PC_STR_PROVIDER") == "1":
                app.di.provide(str, "prov-str-s2", qualifier="s2")
        except Exception as e:  # noqa: BLE001
            print(f"pc-probe: provider registration failed: {type(e).__name__}: {e}")
        app.extensions.register_plugin_command(
            "surfaces", self._surfaces, namespace="probe",
            help_text="parameter-contract: drive Lambda, the TUI door and the SmartBar per row",
        )

    def _surfaces(self, spec: str = "", out: str = "") -> None:
        from functualize._cli.completions.provenance import CompletionProvenanceClassifier
        from functualize._cli.tui.cli_arg_parser import (
            build_group_option_trie,
            parse_job_args,
            resolve_tui_command,
            tokenize_bar_text,
        )
        from functualize._cli.tui.descriptor_fields import get_descriptor_fields
        from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete
        from functualize.app.utils import RunRequest
        from functualize_lambda import LambdaAdapter

        app = self._app
        rows = json.loads(open(spec).read())
        trie = build_group_option_trie(app)
        bar = SmartBarAutoComplete(app=app, provenance=CompletionProvenanceClassifier(app))
        lam = LambdaAdapter()
        lam(app)
        results: dict[str, Any] = {}

        def items(text: str) -> Any:
            def go():
                return [getattr(c, "main", str(c)) for c in bar.get_candidates(_State(text))]
            return {"text": text, "candidates": _guard(go)}

        def tui(text: str) -> Any:
            def go():
                tokens = tokenize_bar_text(text)
                res = resolve_tui_command(trie, tokens)
                if res.job_name is None:
                    return {"resolved": None}
                desc = app.get_job(res.job_name)
                fields = get_descriptor_fields(desc) or []
                # The TUI door's own parse (D8): the bar tokens go through the click
                # parameters `func <job>` renders from the contracts, as
                # `_cli/tui/app.py` does for a run. A `GroupOptions` injection point is
                # not in `parameters` (task 3.2), so nothing is filtered here; a call
                # the CLI refuses raises click.UsageError, recorded as a refusal cell.
                kwargs = parse_job_args(res.args, fields)
                req = RunRequest(job_name=res.job_name, surface="tui.inline", kwargs=dict(kwargs),
                                 group_option_values=res.group_values or None)
                return {"kwargs": kwargs, "group_values": res.group_values,
                        **_result(app.execute(req))}
            return {"text": text, **_guard(go)}

        for row in rows:
            rid, job = row["id"], row["job"]
            r: dict[str, Any] = {}
            # One row may not abort the probe: a handler that cannot even be built
            # (a refused job, a describe-time error) is recorded as each thin cell.
            made = _guard(lambda job=job: {"handler": lam.make_handler(job)})
            handler = made.get("handler") if "raised" not in made else None
            for k, ev in row["lambda"].items():
                if handler is None:
                    r[f"lambda_thin_{k}"] = {"event": ev, **made}
                else:
                    r[f"lambda_thin_{k}"] = {"event": ev,
                                             **_guard(lambda ev=ev: handler(ev, None))}
            r["lambda_fat_kwargs"] = {
                "event": row["lambda_fat"],
                **_guard(lambda: lam.run(row["lambda_fat"], None)),
            }
            for k, text in row["tui"].items():
                r[f"tui_{k}"] = tui(text)
            r["smartbar_flags"] = items(row["smartbar_flag_text"])
            r["smartbar_after_job"] = items(row["smartbar_job_text"])
            results[rid] = r
        open(out, "w").write(json.dumps(results, indent=1, default=repr))
        print(f"pc-probe: {len(results)} rows -> {out}")


plugin = Mch242Probe()
