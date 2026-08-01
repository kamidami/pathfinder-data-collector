from pathfinder_collector.domain.jobs import CollectionJob
from pathfinder_collector.enums import EntityType
from pathfinder_collector.persistence.repositories import JobRepositoryProtocol


def create_job(
    repository: JobRepositoryProtocol,
    *,
    name: str,
    country_code: str,
    entity_type: EntityType,
    requested_limit: int,
) -> CollectionJob:
    job = CollectionJob(
        name=name,
        country_code=country_code,
        entity_type=entity_type,
        requested_limit=requested_limit,
    )
    return repository.add(job)
