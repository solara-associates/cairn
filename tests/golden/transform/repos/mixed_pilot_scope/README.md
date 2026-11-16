# Mixed pilot-scope golden fixture

A small synthetic repository combining Terraform/HCL infrastructure
and Python application code, representing a realistic pilot-scope
transformation target (ADR-015's R3 language scope). This file itself
is deliberately outside that scope (`SourceLanguage.UNSUPPORTED`) --
it exercises the "readable but out of scope, never dropped by fetch,
never sent to the transform engine" path 721's `detect_language`
already established.
