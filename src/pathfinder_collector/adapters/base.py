from typing import Any, Protocol

from pydantic import AnyHttpUrl, BaseModel, Field


class DiscoveryQuery(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    country_code: str = Field(min_length=2, max_length=2)
    limit: int = Field(gt=0)


class DiscoveredSource(BaseModel):
    url: AnyHttpUrl
    title: str | None = Field(default=None, max_length=500)


class FetchedDocument(BaseModel):
    url: AnyHttpUrl
    content_hash: str = Field(max_length=128)
    cached_file_path: str = Field(max_length=500)


class ExtractedData(BaseModel):
    values: dict[str, Any]


class NormalizedData(BaseModel):
    values: dict[str, Any]


class SourceAdapter(Protocol):
    def discover(self, query: DiscoveryQuery) -> list[DiscoveredSource]: ...

    def fetch(self, candidate: DiscoveredSource) -> FetchedDocument: ...

    def extract(self, document: FetchedDocument) -> ExtractedData: ...

    def normalize(self, extracted_data: ExtractedData) -> NormalizedData: ...
