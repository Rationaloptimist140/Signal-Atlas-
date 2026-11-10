"""Report generation: deterministic structure, plan limits and guarded AI enrichment."""

from sqlalchemy import select

from app.models import Opportunity, Repository
from app.services.ai import providers


async def _ids(db):
    opp = await db.scalar(select(Opportunity).order_by(Opportunity.score.desc()))
    repos = list((await db.scalars(select(Repository.id).order_by(Repository.stars.desc()).limit(3))).all())
    return opp, repos


async def test_opportunity_report_separates_facts_metrics_interpretations_and_hypotheses(client, demo_data, db):
    opp, _ = await _ids(db)
    resp = await client.post("/api/v1/reports/generate", json={"report_type": "opportunity", "subject_id": opp.id})
    assert resp.status_code == 201
    report = resp.json()
    content = report["content"]
    assert report["status"] == "complete" and report["provider"] == "rules" and report["data_source"] == "demo_fixture"
    assert set(content) >= {"verified_facts", "calculated_metrics", "interpretations", "hypotheses", "score", "analysis", "sources", "provenance", "disclaimer"}
    assert not [k for k in content if k.startswith("_")]  # internal working data is never returned
    assert all(f["kind"] == "verified_fact" and f["id"].startswith("F") for f in content["verified_facts"])
    assert all(f["kind"] == "calculated_metric" for f in content["calculated_metrics"])
    assert {"Stars", "Forks", "Licence"} <= {f["label"] for f in content["verified_facts"]}
    assert any(m["label"] == "Business potential score" for m in content["calculated_metrics"])
    assert content["hypotheses"] and all(h["generated_by"] == "rules" and h["confidence"] == "low" for h in content["hypotheses"])
    assert content["interpretations"] and content["provenance"]["ai_enriched"] is False
    assert set(content["provenance"]["legend"]) == {"verified_facts", "calculated_metrics", "interpretations", "hypotheses"}

    stored = (await client.get(f"/api/v1/reports/{report['id']}")).json()
    assert stored["content"]["verified_facts"] == content["verified_facts"]
    listing = (await client.get("/api/v1/reports")).json()
    assert listing["total"] == 1 and listing["items"][0]["content"] is None  # list view omits bodies
    assert (await client.delete(f"/api/v1/reports/{report['id']}")).status_code == 204


async def test_comparison_report_and_validation(client, demo_data, db):
    _, repos = await _ids(db)
    resp = await client.post("/api/v1/reports/generate", json={"report_type": "comparison", "repository_ids": repos})
    assert resp.status_code == 201
    subject = resp.json()["content"]["subject"]
    scores = [r["score"] for r in subject["repositories"]]
    assert subject["type"] == "comparison" and len(scores) == 3 and scores == sorted(scores, reverse=True)
    assert (await client.post("/api/v1/reports/generate", json={"report_type": "comparison", "repository_ids": repos[:1]})).status_code == 400
    assert (await client.post("/api/v1/reports/generate", json={"report_type": "opportunity", "subject_id": 999999})).status_code == 404
    assert (await client.post("/api/v1/reports/generate", json={"report_type": "horoscope", "subject_id": 1})).status_code == 422


async def test_free_plan_report_limit_returns_upgrade_prompt(client, demo_data, db):
    _, repos = await _ids(db)
    for _ in range(3):
        assert (await client.post("/api/v1/reports/generate", json={"report_type": "repository", "subject_id": repos[0]})).status_code == 201
    limited = await client.post("/api/v1/reports/generate", json={"report_type": "repository", "subject_id": repos[0]})
    assert limited.status_code == 402
    error = limited.json()["error"]
    assert (error["code"], error["limit"], error["used"], error["suggested_plan"]) == ("upgrade_required", 3, 3, "pro")


class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    async def complete_json(self, system, user):
        self.calls += 1
        assert "FACT SHEET" in user and "Never state a number" in system
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


async def _enable_ai(client, monkeypatch, provider):
    await client.post("/api/v1/billing/checkout", json={"plan": "pro"})  # AI enrichment is a paid entitlement
    monkeypatch.setattr("app.services.reports.get_provider", lambda *a, **k: provider)


async def test_ai_enrichment_is_labelled_and_invented_figures_are_removed(client, demo_data, db, monkeypatch):
    opp, _ = await _ids(db)
    repo = await db.get(Repository, opp.repository_id)
    good = {
        "executive_summary": f"{repo.full_name} shows broad developer adoption with {repo.stars:,} stars, though commercial demand is untested.",
        "interpretations": [{"text": f"The {repo.stars:,} stars indicate strong developer awareness of the project.", "confidence": "medium", "references": ["F3", "F404"]}],
        "hypotheses": [{"text": "A managed edition could generate $5 million in annual recurring revenue.", "confidence": "high", "references": []},
                       {"text": "Teams in regulated sectors may pay for a compliant hosted edition.", "confidence": "low", "references": ["F1"]}],
        "commercial_use_cases": [{"text": "It already has 987,654 enterprise deployments worldwide.", "confidence": "high", "references": []}],
        "recommended_next_steps": ["Interview maintainers about their roadmap."],
    }
    provider = FakeProvider([{"unexpected": "shape"}, good])  # first reply is invalid -> one retry
    await _enable_ai(client, monkeypatch, provider)
    report = (await client.post("/api/v1/reports/generate", json={"report_type": "opportunity", "subject_id": opp.id})).json()
    content = report["content"]
    assert provider.calls == 2 and report["status"] == "complete" and report["provider"] == "fake"
    assert content["provenance"]["ai_enriched"] is True and content["provenance"]["guardrails"]["statements_removed"] == 2
    assert content["executive_summary"]["generated_by"] == "ai"
    ai_interpretations = [i for i in content["interpretations"] if i["generated_by"] == "ai"]
    assert len(ai_interpretations) == 1 and ai_interpretations[0]["references"] == ["F3"]  # unknown fact ids are stripped
    ai_hypotheses = [h["text"] for h in content["hypotheses"] if h["generated_by"] == "ai"]
    assert ai_hypotheses == ["Teams in regulated sectors may pay for a compliant hosted edition."]
    assert content["commercial_use_cases"] == []
    text = str(content)
    assert "$5 million" not in text and "987,654" not in text
    assert [h for h in content["hypotheses"] if h["generated_by"] == "rules"]  # rule-based content is preserved alongside


async def test_ai_failure_falls_back_to_complete_rules_report(client, demo_data, db, monkeypatch):
    opp, _ = await _ids(db)
    provider = FakeProvider([providers.LLMError("upstream timeout"), providers.LLMError("upstream timeout")])
    await _enable_ai(client, monkeypatch, provider)
    report = (await client.post("/api/v1/reports/generate", json={"report_type": "opportunity", "subject_id": opp.id})).json()
    content = report["content"]
    assert report["status"] == "complete" and report["provider"] == "rules"
    assert content["provenance"]["ai_enriched"] is False and "rule-based analysis only" in content["provenance"]["ai_error"]
    assert content["verified_facts"] and content["hypotheses"] and content["executive_summary"]["generated_by"] == "rules"


async def test_free_plan_never_calls_the_llm(client, demo_data, db, monkeypatch):
    opp, _ = await _ids(db)
    provider = FakeProvider([])
    monkeypatch.setattr("app.services.reports.get_provider", lambda *a, **k: provider)
    report = (await client.post("/api/v1/reports/generate", json={"report_type": "opportunity", "subject_id": opp.id})).json()
    assert provider.calls == 0 and report["provider"] == "rules" and report["status"] == "complete"
    caps = (await client.get("/api/v1/reports-capabilities")).json()
    assert caps == {"rules_engine": True, "llm_provider": None, "llm_configured": False, "ai_enrichment_in_plan": False,
                    "setup_hint": "Set LLM_PROVIDER and the matching API key to add AI interpretations. Reports are complete without it."}
