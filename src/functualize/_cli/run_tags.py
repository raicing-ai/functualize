"""Temporary forwarding path for the moved run-tag grammar."""

# TRANSITIONAL(run-tags-from-settings-files/5.2): remove after CLI callers
# move to the public app.config seam.
from functualize.app.config import (
    RunTagError as RunTagError,
)
from functualize.app.config import (
    merge_layers as merge_layers,
)
from functualize.app.config import (
    parse_config_list as parse_config_list,
)
from functualize.app.config import (
    parse_env as parse_env,
)
from functualize.app.config import (
    parse_flag_list as parse_flag_list,
)
from functualize.app.config import (
    parse_tag as parse_tag,
)
