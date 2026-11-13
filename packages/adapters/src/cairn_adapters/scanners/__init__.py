"""CAIRN cairn_adapters.scanners.

Normalization adapters (R1-09) that turn each scanner's native output
format into the common ``cairn_modules.posture.findings.Finding`` model.
"""

from cairn_adapters.scanners import opa_adapter, prowler_adapter, steampipe_adapter

__all__ = ["opa_adapter", "prowler_adapter", "steampipe_adapter"]
