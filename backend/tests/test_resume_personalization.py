"""Resume-personalized warmup.

WHY: Only whitelisted professional fields (skills, current_company) may shape the
warmup. PII (phone/email/linkedin/location/country_code) must NEVER appear. Missing
resume details must fall back to a generic, still-personalized-by-name warmup.
"""
from src.services.interview.warmup import personalize_warmup

PII = {
    "555", "1234567890", "@", "linkedin.com", "Berlin", "+1", "+91",
}


def test_uses_company_and_skill_when_present():
    line = personalize_warmup(
        candidate_name="Alice", job_role="backend engineer",
        details={"skills": ["Kubernetes", "Go"], "current_company": "Acme"},
    )
    assert "Acme" in line
    assert "Kubernetes" in line
    assert "Alice" in line


def test_never_leaks_pii():
    line = personalize_warmup(
        candidate_name="Alice", job_role="backend engineer",
        details={
            "skills": ["Kubernetes"], "current_company": "Acme",
            "email": "alice@x.com", "phone": "5551234567",
            "linkedin_url": "https://linkedin.com/in/alice",
            "current_location": "Berlin", "country_code": "+1",
        },
    )
    for token in PII:
        assert token not in line


def test_falls_back_to_generic_when_no_details():
    line = personalize_warmup(candidate_name="Alice", job_role="backend engineer", details=None)
    assert "Alice" in line
    assert isinstance(line, str) and len(line) > 0


def test_falls_back_when_company_missing():
    line = personalize_warmup(
        candidate_name="Alice", job_role="backend engineer",
        details={"skills": ["Rust"]},  # no current_company
    )
    assert "Alice" in line
