# Refused lazy app command contract

## Invocation

`python my_app.py refused [arguments]` returns the admitted discovery refusal for every non-help argument set, exit 2. The refusal is one `Error:` line naming the job, parameter, and remedy. `--help` remains Click documentation, exit 0. A refused workflow job's `--wf-status` and a flag after a grouped refused job follow the refusal rule.

The stored refusal is rendered by `app/adapters/click_params.py::_refused_job_command`; this feature adds no second renderer, no new command-line input, and no wire or file format.

## Reference

Approved Shape Intent SD/30310404 v4, `Authority: Approved`, read live 2026-11-27; the existing `func` refusal is the reference.
