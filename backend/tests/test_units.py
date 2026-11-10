"""Pure-function tests: taxonomy, manifests, trend maths, AI guardrails, security helpers."""

import datetime as dt

import pytest

from app.logging_config import redact
from app.security import (
    decrypt_secret,
    encrypt_secret,
    generate_api_key,
    hash_password,
    hash_token,
    sign,
    unsign,
    verify_password,
)
from app.services.ai.guardrails import allowed_numbers, apply_guardrails, check_statement
from app.services.ai.providers import LLMError, extract_json
from app.services.ai.schemas import AIEnrichment
from app.services.manifests import parse_manifest
from app.services.trends import period_key, robust_z, window_delta
from app.taxonomy import CATEGORIES, TECHNOLOGIES, classify, primary_category


def test_taxonomy_is_consistent():
    assert all(category in CATEGORIES for _, category, _ in TECHNOLOGIES.values())
    assert set(CATEGORIES) == {"ai-ml", "fintech", "blockchain", "developer-infrastructure", "cybersecurity", "automation", "cloud-computing", "data-infrastructure", "enterprise-software"}


def test_classify_prefers_topics_over_description():
    matches = classify("lumen", "A framework for multi-agent LLM workflows", ["ai-agents", "llm"])
    slugs = {m.slug: m for m in matches}
    assert slugs["llm"].confidence == 0.9 and slugs["llm"].matched_on == "topic"
    assert primary_category(matches) == "ai-ml"


def test_generic_keywords_do_not_match_free_text():
    # "api" and "security" are topic-only keywords: a passing mention must not classify the repository
    matches = classify("notes", "A small app with an api and good security", [])
    assert not {m.slug for m in matches} & {"api-tooling", "appsec"}
    assert primary_category(classify("x", None, [])) is None


def test_classify_database_and_kubernetes():
    assert primary_category(classify("tidepool", "Serverless Postgres database", ["database", "postgres"])) == "data-infrastructure"
    assert primary_category(classify("kubelantern", "", ["kubernetes"])) == "cloud-computing"


def test_parse_package_json():
    deps = parse_manifest("package.json", '{"dependencies": {"react": "^19.0.0"}, "devDependencies": {"vitest": "2.0.0"}}')
    assert {(d.ecosystem, d.name, d.dep_type) for d in deps} == {("npm", "react", "runtime"), ("npm", "vitest", "dev")}
    assert parse_manifest("package.json", "{not json") == []


def test_parse_python_manifests():
    reqs = parse_manifest("requirements.txt", "FastAPI>=0.115  # web\n-r other.txt\nhttpx[http2]==0.27 ; python_version > '3.8'\n\ngit+https://x/y.git\n")
    assert [(d.name, d.version_spec) for d in reqs] == [("fastapi", ">=0.115"), ("httpx", "==0.27")]
    pyproject = parse_manifest("pyproject.toml", '[project]\ndependencies = ["pydantic>=2", "SQLAlchemy"]\n[project.optional-dependencies]\ndev = ["pytest"]\n')
    assert {(d.name, d.dep_type) for d in pyproject} == {("pydantic", "runtime"), ("sqlalchemy", "runtime"), ("pytest", "dev")}


def test_parse_go_and_cargo():
    go = parse_manifest("go.mod", "module x\n\nrequire (\n\tgithub.com/spf13/cobra v1.8.0\n\tgolang.org/x/sys v0.1.0 // indirect\n)\nrequire github.com/a/b v1.0.0\n")
    assert {(d.name, d.dep_type) for d in go} == {("github.com/spf13/cobra", "runtime"), ("golang.org/x/sys", "dev"), ("github.com/a/b", "runtime")}
    cargo = parse_manifest("Cargo.toml", '[dependencies]\ntokio = { version = "1", features = ["full"] }\nserde = "1.0"\n[dev-dependencies]\ncriterion = "0.5"\n')
    assert {(d.name, d.version_spec, d.dep_type) for d in cargo} == {("tokio", "1", "runtime"), ("serde", "1.0", "runtime"), ("criterion", "0.5", "dev")}
    assert parse_manifest("unknown.lock", "x") == []


def test_window_delta_picks_matching_snapshots():
    today = dt.date(2026, 11, 10)
    history = [(today - dt.timedelta(days=d), 1000 - d * 10) for d in range(0, 31)]
    assert window_delta(history, today, 1) == (990, 1000, 1)
    assert window_delta(history, today, 7) == (930, 1000, 7)
    assert window_delta(history, today, 30) == (700, 1000, 30)
    assert window_delta([(today, 5)], today, 7) is None
    assert window_delta([(today - dt.timedelta(days=20), 1), (today - dt.timedelta(days=19), 2)], today, 1) is None  # stale


def test_robust_z_and_period_keys():
    assert robust_z(5.0, [1.0] * 4) is None  # too few peers
    assert robust_z(50.0, [1, 2, 3, 2, 1, 2, 3, 2, 1]) > 3
    day = dt.date(2026, 11, 10)
    assert period_key("daily", day) == "2026-11-10"
    assert period_key("weekly", day) == "2026-W46"
    assert period_key("monthly", day) == "2026-11"


FACTS = [{"id": "F1", "label": "Stars", "value": "12,345", "kind": "verified_fact"}, {"id": "F2", "label": "Growth over 30 days", "value": "+4.5%", "kind": "calculated_metric"}]


def test_guardrails_allow_only_figures_from_fact_sheet():
    allowed = allowed_numbers(FACTS)
    assert check_statement("With 12,345 stars and 4.5% growth this is notable.", allowed) is None
    assert check_statement("It serves 3 customer segments.", allowed) is None
    assert check_statement("The project has 99,000 stars.", allowed) == "unverified_figure:99000"
    assert check_statement("The market is worth $4 billion.", allowed) == "monetary_or_market_size_claim"
    assert check_statement("Estimated ARR of about 20 for early adopters.", allowed) == "monetary_or_market_size_claim"


def test_apply_guardrails_drops_invented_statistics_and_bad_references():
    enrichment = AIEnrichment.model_validate({
        "executive_summary": "A project with 12,345 stars showing steady adoption among developers.",
        "interpretations": [{"text": "Adoption is broad, with 12,345 stars.", "confidence": "medium", "references": ["F1", "F99"]},
                            {"text": "Downloads exceed 500,000 per week according to registries.", "confidence": "high", "references": []}],
        "hypotheses": [{"text": "A hosted edition could reach £2m revenue quickly.", "confidence": "low", "references": []},
                       {"text": "Regulated industries may pay for a compliant hosted edition.", "confidence": "low", "references": ["F2"]}],
        "recommended_next_steps": ["Interview users of the project.", "Target the 40,000 companies using it."],
    })
    cleaned, report = apply_guardrails(enrichment, FACTS)
    assert [i.text for i in cleaned.interpretations] == ["Adoption is broad, with 12,345 stars."]
    assert cleaned.interpretations[0].references == ["F1"]
    assert len(cleaned.hypotheses) == 1 and "Regulated" in cleaned.hypotheses[0].text
    assert cleaned.recommended_next_steps == ["Interview users of the project."]
    assert report["statements_removed"] == 3 and report["summary_rejected"] is False


def test_extract_json_handles_fences_and_rejects_garbage():
    assert extract_json('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('prefix {"a": {"b": 2}} suffix') == {"a": {"b": 2}}
    for bad in ("no json here", "[1, 2]", "{broken"):
        with pytest.raises(LLMError):
            extract_json(bad)


def test_password_hashing_and_tokens():
    hashed = hash_password("Str0ngPassw0rd!")
    assert hashed.startswith("$argon2") and "Str0ng" not in hashed
    assert verify_password("Str0ngPassw0rd!", hashed) and not verify_password("wrong", hashed) and not verify_password("x", None)
    full, prefix, key_hash = generate_api_key()
    assert full.startswith("sa_live_") and full.startswith(prefix) and key_hash == hash_token(full) and len(key_hash) == 64


def test_encryption_roundtrip_and_signing():
    secret = "gho_exampletoken1234567890"
    cipher = encrypt_secret(secret)
    assert secret not in cipher and decrypt_secret(cipher) == secret
    assert decrypt_secret("not-a-valid-token") is None
    signed = sign("state:connect")
    assert unsign(signed) == "state:connect" and unsign(signed + "x") is None and unsign("nodot") is None


def test_log_redaction_masks_tokens():
    fake_github = "ghp_" + "a1B2" * 9
    fake_llm = "sk-" + "x9Y8" * 8
    fake_atlas = "sa_live_1234abcd_" + "q" * 24
    line = redact(f"token {fake_github} and {fake_llm} and {fake_atlas}")
    assert fake_github not in line and fake_llm not in line and fake_atlas not in line
    assert line.count("[REDACTED]") == 3
