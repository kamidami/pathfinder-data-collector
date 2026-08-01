import csv
import json

from pydantic import BaseModel, ConfigDict, Field, create_model

from pathfinder_collector.config import Settings
from pathfinder_collector.exceptions import ContractError


class ContractEntity(BaseModel):
    entity_type: str
    template: str
    source_pathfinder_template: str
    columns: list[str]
    required_columns: list[str] = Field(default_factory=list)


class ContractManifest(BaseModel):
    contract_version: str
    note: str
    entities: list[ContractEntity]

    def entity(self, name: str) -> ContractEntity:
        normalized = name.removesuffix("_template.csv")
        for entity in self.entities:
            if normalized in {entity.entity_type, entity.template.removesuffix("_template.csv")}:
                return entity
        raise ContractError(f"unknown contract entity: {name}")


def load_manifest(settings: Settings | None = None) -> ContractManifest:
    settings = settings or Settings()
    try:
        return ContractManifest.model_validate_json(settings.contract_manifest_path.read_text())
    except (OSError, ValueError) as exc:
        raise ContractError(f"cannot load contract manifest: {exc}") from exc


def read_template_header(entity: ContractEntity, settings: Settings | None = None) -> list[str]:
    settings = settings or Settings()
    path = settings.contract_manifest_path.parent / entity.template
    with path.open(newline="", encoding="utf-8") as handle:
        return next(csv.reader(handle))


def export_model(entity: ContractEntity) -> type[BaseModel]:
    fields = {column: (str, "") for column in entity.columns}
    model = create_model(
        f"{entity.entity_type.title().replace('_', '')}Export",
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )
    return model


MANIFEST_JSON_SCHEMA = json.dumps(ContractManifest.model_json_schema(), indent=2)

# Named Pydantic schemas provide stable import points while retaining exact manifest columns.
_manifest = load_manifest()
ProgramExport = export_model(_manifest.entity("programs"))
ScholarshipExport = export_model(_manifest.entity("scholarships"))
CountryRuleExport = export_model(_manifest.entity("country_rules"))
CostProfileExport = export_model(_manifest.entity("cost_profiles"))
SourceRecordExport = export_model(_manifest.entity("source_records"))
CountryExport = export_model(_manifest.entity("countries"))
