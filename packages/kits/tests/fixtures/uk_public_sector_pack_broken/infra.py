"""A direct adapter import -- the domain-purity violation under test.

A real vertical pack that reaches straight into an adapter instead of
calling through the kernel/contract boundary is exactly the realistic
failure mode this broken variant stands in for.
"""

import cairn_adapters  # noqa: F401 - the violation itself
