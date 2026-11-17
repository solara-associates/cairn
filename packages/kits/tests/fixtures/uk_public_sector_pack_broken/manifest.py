from cairn_kernel.hex.primitives import MutationClass
from cairn_kits.vertical_packs.manifest import PackManifest

MANIFEST = PackManifest(
    pack_id="uk-public-sector-broken",
    version="2026.11.0",
    declared_ports=("cairn_modules.sovereignty.residency_sweep.sweep_estate_residency",),
    declared_mutation_classes=(MutationClass.READ_ONLY,),
)
