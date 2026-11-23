"""Which click-command factory serves `func <job>` cold and warm, and does _EnumChoice convert?

Run inside a project whose `.functualize/jobs/jobs.py` declares `paint(c: Color = Color.BLUE)`:
    uv run --project <worktree> --frozen python <worktree>/.spec/features/parameter-contract/matrix/enum_trace.py paint --c red
"""
import sys
import functualize.app.adapters.click_params as cp
import functualize.app.adapters.lazy_command as lc

def wrap(mod, name):
    orig = getattr(mod, name)
    def w(*a, **k):
        print(f"TRACE {mod.__name__.rsplit('.',1)[1]}.{name}", file=sys.stderr)
        return orig(*a, **k)
    setattr(mod, name, w)

wrap(cp, "create_job_click_command")
wrap(lc, "make_lazy_command")
orig_conv = cp._EnumChoice.convert
def conv(self, value, param, ctx):
    r = orig_conv(self, value, param, ctx)
    print(f"TRACE _EnumChoice.convert {value!r} -> {r!r}", file=sys.stderr)
    return r
cp._EnumChoice.convert = conv
from functualize._cli.main import main
sys.argv = ["func", *sys.argv[1:]]
main()
