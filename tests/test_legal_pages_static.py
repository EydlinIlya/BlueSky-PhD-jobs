"""Regression checks for the restored About and Terms content."""

from pathlib import Path


DOCS = Path(__file__).resolve().parents[1] / "docs"


def page(name: str) -> str:
    return (DOCS / name).read_text(encoding="utf-8")


def test_about_restores_service_identity_and_methodology():
    about = page("about.html")

    assert "Eli Eydlin in Israel" in about
    assert "free, independent, non-commercial service" in about
    assert "ScholarshipDB" in about
    assert "Automation can be wrong" in about
    assert "/_vercel/insights/script.js" not in about


def test_terms_restore_operator_disclaimers_and_governing_law():
    terms = page("terms.html")

    assert "Eli Eydlin, an individual in Israel" in terms
    assert "Listings and automated classification" in terms
    assert "Saving a search enables weekly email delivery" in terms
    assert "State of Israel" in terms
    assert "[your country" not in terms
    assert "/_vercel/insights/script.js" not in terms
