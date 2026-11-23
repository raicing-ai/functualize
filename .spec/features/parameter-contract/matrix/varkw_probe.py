"""A **kwargs job: the old launch rule (validation.unexpected_keyword_error) versus the binder.

Run from the repository root, before task 5.1 deletes validation.py:
    uv run --frozen python .spec/features/parameter-contract/matrix/varkw_probe.py
"""
from functualize._primitives.parameter_contract import build_contracts
from functualize._primitives.argument_binding import ArgumentBinder, BindRefusal
from functualize._engine.validation import unexpected_keyword_error

def job(version: str = "1", **kwargs):
    return kwargs

print("unexpected_keyword_error(job, {'zzz': 1}) ->", unexpected_keyword_error(job, {"zzz": 1}))
try:
    print("ArgumentBinder().bind(job, ..., {'zzz': 1}) ->", ArgumentBinder().bind(job, build_contracts(job), {"zzz": 1}, surface="func"))
except BindRefusal as e:
    print("ArgumentBinder().bind(job, ..., {'zzz': 1}) -> BindRefusal:", e)
