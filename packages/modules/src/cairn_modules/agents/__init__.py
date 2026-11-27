"""CAIRN ``cairn_modules.agents``: the launch agents, as application
services (ADR-019 §2).

Each agent in here constructs an ``AgentSpec``, invokes
``AgentLoopPort``, validates the resulting proposal against its own
domain contract, persists it as a candidate, and stops. None of them
approves or executes anything: ``cairn_modules`` cannot import
``cairn_adapters`` (``domain-purity``), the loop they drive cannot reach
approval or execution authority (``loop-cannot-execute``), and every
toolset they declare is ``READ``/``PROPOSE`` only, checked at
``AgentSpec.build`` and again before each invocation (R-AGENT-03).

Wave 4: ``assessment_explainer`` (R6-12), ``design_proposer`` (R6-13),
``modernize_proposer`` (R6-14).
"""
