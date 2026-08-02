from pathlib import Path

from pathfinder_collector.services.pilots import (
    PilotProgrammeOutcome,
    calculate_pilot_metrics,
    render_pilot_metrics,
)


def test_pilot_metrics_and_report_rendering() -> None:
    outcomes = [
        PilotProgrammeOutcome(
            name="one",
            fetch_success=True,
            extraction_success=True,
            automatic_core_complete=True,
            evidence_count=8,
            overrides_count=0,
            conflicts_count=0,
            approved=True,
            exported=True,
            review_minutes=3,
        ),
        PilotProgrammeOutcome(
            name="two",
            fetch_success=False,
            extraction_success=False,
            automatic_core_complete=False,
            evidence_count=0,
            overrides_count=0,
            conflicts_count=0,
            approved=False,
            exported=False,
            review_minutes=1,
            failure_category="http_403",
        ),
    ]
    metrics = calculate_pilot_metrics(outcomes)
    assert metrics.fetch_success_rate == 0.5
    assert metrics.average_evidence_count == 4
    assert metrics.failures_by_category == {"http_403": 1}
    assert "50.0%" in render_pilot_metrics(metrics)


def test_no_full_downloaded_pages_are_committed_as_fixtures() -> None:
    fixtures = Path(__file__).parent / "fixtures"
    assert all(path.stat().st_size < 20_000 for path in fixtures.glob("*.html"))
