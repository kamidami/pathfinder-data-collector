from pathlib import Path

from pathfinder_collector.extraction.programmes import (
    ProgrammeExtractor,
    normalize_degree,
    normalize_duration,
    normalize_language,
    normalize_program_name,
    normalize_study_mode,
)

FIXTURES = Path(__file__).parent / "fixtures"


def extracted(name: str):
    return ProgrammeExtractor().extract(
        (FIXTURES / name).read_bytes(), "https://example.test/programme"
    )


def values(output: object, field: str) -> list[str]:
    return [
        item.normalized_value or item.extracted_value
        for item in output.suggestions
        if item.field_name == field
    ]


def test_labelled_programme_fields_and_normalizers() -> None:
    output = extracted("programme_labelled.html")
    assert values(output, "program_name") == ["Data Science"]
    assert "Example University" in values(output, "university_name")
    assert "master" in values(output, "degree_level")
    assert values(output, "teaching_language") == ["English and German"]
    assert values(output, "duration_value") == ["4"]
    assert values(output, "duration_semesters") == ["4"]
    assert values(output, "study_mode") == ["full_time"]
    assert values(output, "city") == ["Berlin"]
    assert values(output, "country_code") == ["DE"]
    assert values(output, "application_url") == ["https://example.test/apply"]


def test_controlled_normalizers() -> None:
    assert normalize_degree("B.Sc.") == "bachelor"
    assert normalize_degree("Dr.-Ing.") == "phd"
    assert normalize_language("English / German") == "English and German"
    assert normalize_duration("2 years") == (2, "years", 4)
    assert normalize_duration("24 months") == (24, "months", None)
    assert normalize_duration("P24M") == (4, "semesters", 4)
    assert normalize_program_name("M.Sc. Computer Science") == "Computer Science"
    assert normalize_study_mode("blended learning").value == "hybrid"


def test_json_ld_and_metadata_fallback() -> None:
    output = extracted("programme_metadata.html")
    assert set(values(output, "program_name")) == {"Applied Physics"}
    assert "Meta University" in values(output, "university_name")
    assert values(output, "teaching_language") == ["English"]
    assert values(output, "duration_value") == ["2"]
    assert values(output, "duration_semesters") == ["4"]


def test_invalid_json_ld_is_safe_and_labelled_data_survives() -> None:
    output = extracted("invalid_jsonld.html")
    assert "Invalid JSON-LD was ignored" in output.warnings
    assert values(output, "degree_level") == ["bachelor", "bachelor"]
    assert values(output, "teaching_language") == ["English"]


def test_non_programme_page_is_rejected_and_page_language_not_inferred() -> None:
    output = extracted("non_programme.html")
    assert not output.programme_context
    assert not output.suggestions


def test_malformed_html_is_bounded_and_country_is_not_inferred_from_domain() -> None:
    content = (
        b"<html><body><h1>Broken M.Sc.<dl><dt>Degree</dt><dd>M.Sc."
        b"<dt>University</dt><dd>Safe University"
    )
    output = ProgrammeExtractor().extract(content, "https://university.de/programme")
    assert output.programme_context
    assert values(output, "degree_level")
    assert values(output, "country_code") == []


def test_generic_cards_inline_lines_adjacent_degree_and_institution_metadata() -> None:
    output = extracted("programme_generic_cards.html")
    assert values(output, "program_name") == ["Systems Engineering"]
    assert "master" in values(output, "degree_level")
    assert "Example University" in values(output, "university_name")
    assert values(output, "country_code") == ["DE"]
    assert "English" in values(output, "teaching_language")
    assert any(item.evidence_locator.startswith("labelled-inline") for item in output.suggestions)
    assert "full_time" in values(output, "study_mode")
    assert "Example City" in values(output, "city")
    assert "4" in values(output, "duration_semesters")
    assert values(output, "source_url") == ["https://example.test/programme"]
