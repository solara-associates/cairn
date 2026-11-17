from cairn_kernel.hex.primitives import MutationClass
from cairn_kits.vertical_packs.manifest import PackManifest

MANIFEST = PackManifest(
    pack_id="good-pack",
    version="0.1.0",
    declared_ports=("cairn_kernel.execution_gate.ports.ExecutionGatePort",),
    declared_mutation_classes=(MutationClass.READ_ONLY,),
)
