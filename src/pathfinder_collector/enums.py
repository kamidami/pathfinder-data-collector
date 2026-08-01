from enum import StrEnum


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CandidateStatus(StrEnum):
    DISCOVERED = "discovered"
    COLLECTED = "collected"
    NEEDS_REVIEW = "needs_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPORTED = "exported"


class EntityType(StrEnum):
    PROGRAM = "program"
    SCHOLARSHIP = "scholarship"
    COUNTRY_RULE = "country_rule"
    COST_PROFILE = "cost_profile"
    SOURCE_RECORD = "source_record"


class SourceType(StrEnum):
    DISCOVERY = "discovery"
    OFFICIAL_PROGRAM = "official_program"
    OFFICIAL_ADMISSIONS = "official_admissions"
    OFFICIAL_FEES = "official_fees"
    OFFICIAL_DEADLINES = "official_deadlines"
    OFFICIAL_SCHOLARSHIP = "official_scholarship"
    OFFICIAL_GOVERNMENT = "official_government"
    OTHER_OFFICIAL = "other_official"


class ConfidenceLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FetchStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ResolutionStatus(StrEnum):
    UNRESOLVED = "unresolved"
    RESOLVED = "resolved"


class ExportStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
