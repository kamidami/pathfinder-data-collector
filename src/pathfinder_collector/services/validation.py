from pathfinder_collector.contracts.pathfinder_v1 import ContractManifest


def unknown_columns(record: dict[str, object], manifest: ContractManifest, entity: str) -> set[str]:
    expected = set(manifest.entity(entity).columns)
    return set(record) - expected
