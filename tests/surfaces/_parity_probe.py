"""The probe plugin the parity test installs into its generated project.

Loaded by the real ``func`` as ``.functualize/plugins/parity_probe.py``, so
every surface below sees the application exactly as ``func`` booted it — cold
on the first run, warm from the cache on the second. ``func parity dump``
writes, per job, what each of the ten surfaces publishes and what it delivers:

- ``help``: the parameters of the command ``func <job>`` builds
  (``_materialize_for_dispatch`` then ``create_job_click_command``);
- ``bash`` / ``zsh``: the words the real completion scripts offer;
- ``smartbar``: the SmartBar's candidates after ``<job> --``;
- ``tui``: the inline TUI's door (tokenize → resolve → parse → run);
- ``info``: ``job_detail``'s ``inputSchema``;
- ``mcp``: the translator's schema and a ``JobTool.run`` call;
- ``http``: ``HttpServerCore.handle_request``;
- ``lambda``: the thin handler ``LambdaAdapter.make_handler`` returns.

This module is the plugin's source; the test writes it into the project.
"""

SOURCE = r"""
import asyncio
import json
import re
import traceback


def _guard(fn):
    try:
        return fn()
    except BaseException as exc:  # noqa: BLE001 - every outcome is a cell
        return {"raised": f"{type(exc).__name__}: {exc}",
                "tb": traceback.format_exc().strip().splitlines()[-3:]}


def _observed(text):
    match = re.search(r"type=(\w+)", text or "")
    return match.group(1) if match else None


def _result(res):
    status = getattr(res, "status", None)
    rv = getattr(res, "return_value", None)
    exc = getattr(res, "exception", None)
    return {"status": str(getattr(status, "value", status)).lower(),
            "reason": "" if exc is None else str(exc),
            "type": _observed(rv if isinstance(rv, str) else None)}


class _State:
    def __init__(self, text):
        self.text = text
        self.cursor_position = len(text)


class ParityProbe:
    name = "parity-probe"
    version = "1.0.0"
    description = "parameter parity probe (test only)"

    def __call__(self, app):
        self._app = app
        from provlib import ProvWidget

        app.di.provide(ProvWidget, ProvWidget("by-type"))
        app.di.provide(ProvWidget, ProvWidget("by-w"), qualifier="w")
        app.extensions.register_plugin_command("dump", self._dump, namespace="parity")

    def _dump(self, spec: str = "", out: str = "") -> None:
        import click

        from functualize._cli.completions.data import extract_completion_data
        from functualize._cli.completions.provenance import CompletionProvenanceClassifier
        from functualize._cli.completions.shell_init import render_completion_script
        from functualize._cli.info import job_detail
        from functualize._cli.main import _materialize_for_dispatch
        from functualize._cli.tui.cli_arg_parser import (
            build_group_option_trie, parse_job_args, resolve_tui_command, tokenize_bar_text,
        )
        from functualize._cli.tui.descriptor_fields import get_descriptor_fields
        from functualize._cli.tui.smart_bar_autocomplete import SmartBarAutoComplete
        from functualize.app.adapters.click_params import create_job_click_command
        from functualize.types import RunRequest
        from functualize_http import HttpServerCore
        from functualize_lambda import LambdaAdapter
        from functualize_mcp._server import JobTool
        from functualize_mcp._translator import JobToolTranslator, read_cached_group_options

        app = self._app
        rows = json.loads(open(spec).read())
        data = extract_completion_data(app)
        scripts = {shell: render_completion_script(data, shell) for shell in ("bash", "zsh")}
        words = {}
        for shell, script in scripts.items():
            words[shell] = {
                key: value.split()
                for key, value in re.findall(r"_func_tree\['[^']*?:([^']*)'\]='([^']*)'", script)
            }
        trie = build_group_option_trie(app)
        bar = SmartBarAutoComplete(app=app, provenance=CompletionProvenanceClassifier(app))
        translator = JobToolTranslator(read_cached_group_options(app))
        http = HttpServerCore(app)
        lam = LambdaAdapter()
        lam(app)

        def tui(text):
            tokens = tokenize_bar_text(text)
            res = resolve_tui_command(trie, tokens)
            desc = app.get_job(res.job_name) if res.job_name else None
            if desc is None:
                return {"resolved": None}
            kwargs = parse_job_args(res.args, get_descriptor_fields(desc) or [])
            req = RunRequest(job_name=res.job_name, surface="tui.inline", kwargs=dict(kwargs),
                             group_option_values=res.group_values or None)
            return _result(app.execute(req))

        def help_params(desc):
            function, config_class, error = _materialize_for_dispatch(app, desc)
            if function is None:
                return {"raised": f"materialize: {error}"}
            cmd = create_job_click_command(name=desc.name, function=function,
                                           job_config_class=config_class, app=app,
                                           surface="func.job")
            text = cmd.get_help(click.Context(cmd, info_name=desc.name))
            return {"text": text, "params": [
                {"kind": type(p).__name__, "name": p.name,
                 "opts": [*p.opts, *getattr(p, "secondary_opts", [])],
                 "required": bool(p.required), "hidden": bool(getattr(p, "hidden", False))}
                for p in cmd.params]}

        results = {}
        for row in rows:
            rid, job, path = row["id"], row["job"], row["path"]
            desc = app.get_job(job)
            if desc is None:
                results[rid] = {"registered": False}
                continue
            key = " ".join(path)
            tool = translator.translate(desc)
            r = {"registered": True,
                 "help": _guard(lambda: help_params(desc)),
                 "bash": words["bash"].get(key, []),
                 "zsh": words["zsh"].get(key, []),
                 "smartbar": _guard(lambda: [
                     word
                     for c in bar.get_candidates(_State(row["bar"]))
                     for word in (getattr(getattr(c, "main", c), "plain", None)
                                  or str(c)).split()[0].split("/")]),
                 "info": _guard(lambda: job_detail(app, job)["inputSchema"]),
                 "mcp_schema": tool.input_schema}
            jt = JobTool.for_job(tool, app)
            group = row["group"]
            for case in ("given", "absent"):
                args = row["args"][case]
                envelope = {"arguments": args}
                if group and case == "given":
                    envelope["group_option_values"] = group
                r[f"tui_{case}"] = _guard(lambda t=row["tui"][case]: tui(t))

                def mcp(case=case):
                    res = asyncio.run(jt.run(dict(row["mcp"][case])))
                    body = res.structured_content or {}
                    return {"status": str(body.get("status", "error")).lower(),
                            "is_error": bool(res.is_error),
                            "reason": str(body.get("error") or ""),
                            "type": _observed(str(body.get("return_value")))}
                r[f"mcp_{case}"] = _guard(mcp)

                def post(envelope=envelope):
                    code, payload = asyncio.run(http.handle_request(
                        "POST", f"/jobs/{job}/execute", json.dumps(envelope).encode()))
                    payload = payload if isinstance(payload, dict) else {}
                    return {"code": code, "status": str(payload.get("status", "")).lower(),
                            "reason": str(payload.get("error") or payload.get("message") or ""),
                            "type": _observed(str(payload.get("return_value")))}
                r[f"http_{case}"] = _guard(post)

                def thin(envelope=envelope):
                    res = lam.make_handler(job)(dict(envelope), None)
                    return {"code": res.get("statusCode"),
                            "status": str(res.get("status", "")).lower(),
                            "reason": str(res.get("error") or ""),
                            "type": _observed(str(res.get("body")))}
                r[f"lambda_{case}"] = _guard(thin)
            results[rid] = r
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(results, handle, default=repr)


plugin = ParityProbe()
"""
