from collections.abc import Callable

from pydantic import BaseModel, Field


class PilotProgrammeOutcome(BaseModel):
    name: str
    fetch_success: bool
    extraction_success: bool
    automatic_core_complete: bool
    evidence_count: int = Field(ge=0)
    overrides_count: int = Field(ge=0)
    conflicts_count: int = Field(ge=0)
    approved: bool
    exported: bool
    review_minutes: float = Field(ge=0)
    failure_category: str | None = None


class PilotMetrics(BaseModel):
    programme_count: int
    fetch_success_rate: float
    extraction_success_rate: float
    automatic_core_completion_rate: float
    average_evidence_count: float
    override_rate: float
    conflict_rate: float
    approval_rate: float
    export_rate: float
    average_review_minutes: float
    failures_by_category: dict[str, int]


def calculate_pilot_metrics(outcomes: list[PilotProgrammeOutcome]) -> PilotMetrics:
    if not outcomes:
        raise ValueError("pilot metrics require at least one outcome")
    count = len(outcomes)

    def rate(predicate: Callable[[PilotProgrammeOutcome], bool]) -> float:
        return sum(1 for item in outcomes if predicate(item)) / count

    failures: dict[str, int] = {}
    for item in outcomes:
        if item.failure_category:
            failures[item.failure_category] = failures.get(item.failure_category, 0) + 1
    return PilotMetrics(
        programme_count=count,
        fetch_success_rate=rate(lambda item: item.fetch_success),
        extraction_success_rate=rate(lambda item: item.extraction_success),
        automatic_core_completion_rate=rate(lambda item: item.automatic_core_complete),
        average_evidence_count=sum(item.evidence_count for item in outcomes) / count,
        override_rate=rate(lambda item: item.overrides_count > 0),
        conflict_rate=rate(lambda item: item.conflicts_count > 0),
        approval_rate=rate(lambda item: item.approved),
        export_rate=rate(lambda item: item.exported),
        average_review_minutes=sum(item.review_minutes for item in outcomes) / count,
        failures_by_category=failures,
    )


def render_pilot_metrics(metrics: PilotMetrics) -> str:
    def percentage(value: float) -> str:
        return f"{value * 100:.1f}%"

    return "\n".join(
        (
            f"- Fetch success rate: {percentage(metrics.fetch_success_rate)}",
            f"- Extraction success rate: {percentage(metrics.extraction_success_rate)}",
            "- Automatic core-field completion rate: "
            f"{percentage(metrics.automatic_core_completion_rate)}",
            f"- Average evidence count: {metrics.average_evidence_count:.1f}",
            f"- Override rate: {percentage(metrics.override_rate)}",
            f"- Conflict rate: {percentage(metrics.conflict_rate)}",
            f"- Approval rate: {percentage(metrics.approval_rate)}",
            f"- Export rate: {percentage(metrics.export_rate)}",
            f"- Average review time: {metrics.average_review_minutes:.1f} minutes",
        )
    )
