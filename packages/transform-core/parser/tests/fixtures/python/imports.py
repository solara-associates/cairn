import os
import sys as system
from collections import OrderedDict

from mypkg.sub import (
    first,
)
from mypkg.sub import (
    second as alias_second,
)

from . import helpers

used_os = os
used_system = system
used_ordered_dict = OrderedDict
used_helpers = helpers
used_first = first
used_alias_second = alias_second
