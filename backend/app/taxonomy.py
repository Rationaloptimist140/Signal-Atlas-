"""Technology taxonomy and transparent keyword classification.

Classification is *inferred* from public topics, names and descriptions. It is never
presented as a verified fact; every match carries the method and a confidence value.
"""

import re
from dataclasses import dataclass

CATEGORIES: dict[str, str] = {
    "ai-ml": "AI & Machine Learning",
    "fintech": "Fintech",
    "blockchain": "Blockchain",
    "developer-infrastructure": "Developer Infrastructure",
    "cybersecurity": "Cybersecurity & Privacy",
    "automation": "Automation",
    "cloud-computing": "Cloud Computing",
    "data-infrastructure": "Data Infrastructure",
    "enterprise-software": "Enterprise Software",
}

# slug -> (name, category, keywords). Keywords prefixed with "=" only match topics/name tokens
# (too generic to trust inside free-text descriptions).
TECHNOLOGIES: dict[str, tuple[str, str, list[str]]] = {
    "llm": ("Large Language Models", "ai-ml", ["llm", "llms", "large-language-models", "large language model", "gpt", "chatgpt", "language-model", "openai", "transformers", "generative-ai", "genai"]),
    "ai-agents": ("AI Agents", "ai-ml", ["ai-agents", "ai-agent", "agentic", "multi-agent", "autonomous-agents", "=agents", "=agent", "=mcp", "model context protocol", "agent framework"]),
    "rag": ("Retrieval-Augmented Generation", "ai-ml", ["=rag", "retrieval-augmented", "retrieval augmented", "graphrag"]),
    "vector-search": ("Vector Search", "ai-ml", ["vector-database", "vector database", "vector-search", "vector search", "embeddings", "similarity-search"]),
    "ml-frameworks": ("ML Frameworks", "ai-ml", ["machine-learning", "machine learning", "deep-learning", "deep learning", "pytorch", "tensorflow", "=jax", "neural-network", "neural network", "=ml", "=ai", "artificial-intelligence"]),
    "computer-vision": ("Computer Vision", "ai-ml", ["computer-vision", "computer vision", "object-detection", "image-segmentation", "=ocr"]),
    "speech-audio": ("Speech & Audio AI", "ai-ml", ["speech-recognition", "text-to-speech", "speech-to-text", "=tts", "=asr", "voice-ai", "speech synthesis"]),
    "generative-media": ("Generative Media", "ai-ml", ["stable-diffusion", "diffusion", "text-to-image", "image-generation", "video-generation", "text-to-video"]),
    "mlops": ("MLOps & Inference", "ai-ml", ["mlops", "llmops", "model-serving", "inference", "fine-tuning", "finetuning", "model serving"]),
    "payments": ("Payments & Billing", "fintech", ["payments", "=payment", "billing", "invoicing", "invoice", "subscriptions", "checkout", "=stripe"]),
    "trading-quant": ("Trading & Quant", "fintech", ["trading", "algorithmic-trading", "backtesting", "=quant", "quantitative-finance", "trading-bot"]),
    "accounting-finance": ("Accounting & Finance Ops", "fintech", ["accounting", "bookkeeping", "ledger", "double-entry", "=finance", "fintech", "personal-finance"]),
    "open-banking": ("Banking & Compliance", "fintech", ["open-banking", "banking", "=kyc", "=aml", "core-banking"]),
    "smart-contracts": ("Smart Contracts", "blockchain", ["smart-contracts", "smart contract", "solidity", "ethereum", "=evm"]),
    "blockchain-infra": ("Blockchain Infrastructure", "blockchain", ["blockchain", "web3", "consensus", "layer2", "rollup", "zero-knowledge", "=zk", "zkp", "bitcoin", "solana"]),
    "defi": ("DeFi & Wallets", "blockchain", ["defi", "=dex", "crypto-wallet", "cryptocurrency", "=crypto"]),
    "dev-tooling": ("Developer Tooling", "developer-infrastructure", ["developer-tools", "devtools", "developer tools", "=cli", "=ide", "code-editor", "linter", "formatter", "build-tool", "bundler", "compiler", "terminal", "package-manager", "coding-assistant", "code-generation"]),
    "ci-cd": ("CI/CD & Delivery", "developer-infrastructure", ["=ci", "=cd", "ci-cd", "cicd", "continuous-integration", "continuous-delivery", "github-actions", "gitops", "deployment"]),
    "testing": ("Testing & QA", "developer-infrastructure", ["testing", "test-automation", "=e2e", "unit-testing", "testing-tools", "fuzzing"]),
    "api-tooling": ("API Tooling", "developer-infrastructure", ["=api", "graphql", "grpc", "openapi", "=sdk", "api-gateway", "rest-api"]),
    "frameworks-web": ("Application Frameworks", "developer-infrastructure", ["web-framework", "=framework", "=react", "nextjs", "=frontend", "=backend", "fullstack", "ui-components", "component-library"]),
    "observability": ("Observability", "developer-infrastructure", ["observability", "monitoring", "tracing", "opentelemetry", "=metrics", "=logging", "apm"]),
    "appsec": ("Application Security", "cybersecurity", ["=security", "vulnerability", "vulnerability-scanner", "=sast", "pentest", "pentesting", "security-tools", "infosec", "cybersecurity", "threat-detection", "malware", "=siem"]),
    "identity-access": ("Identity & Access", "cybersecurity", ["authentication", "authorization", "=oauth", "=sso", "identity", "=iam", "passkeys", "=auth", "access-control"]),
    "privacy-crypto": ("Privacy & Encryption", "cybersecurity", ["privacy", "encryption", "cryptography", "e2ee", "end-to-end encryption", "=vpn", "secrets-management", "zero-trust", "password-manager"]),
    "workflow-automation": ("Workflow Automation", "automation", ["automation", "workflow", "workflow-automation", "no-code", "low-code", "=rpa", "orchestration", "workflow-engine", "job-scheduler"]),
    "browser-automation": ("Browser & Web Automation", "automation", ["browser-automation", "web-scraping", "scraping", "crawler", "playwright", "puppeteer", "=scraper", "computer-use"]),
    "kubernetes-containers": ("Kubernetes & Containers", "cloud-computing", ["kubernetes", "=k8s", "docker", "=containers", "=container", "=helm", "service-mesh"]),
    "infra-as-code": ("Infrastructure as Code", "cloud-computing", ["terraform", "infrastructure-as-code", "=iac", "pulumi", "ansible", "opentofu"]),
    "serverless-edge": ("Serverless, Edge & WASM", "cloud-computing", ["serverless", "=edge", "=faas", "=wasm", "webassembly", "edge-computing"]),
    "cloud-platform": ("Cloud Platforms", "cloud-computing", ["=cloud", "cloud-native", "=paas", "=aws", "=gcp", "=azure", "multi-cloud"]),
    "databases": ("Databases", "data-infrastructure", ["database", "=sql", "postgres", "postgresql", "mysql", "sqlite", "nosql", "key-value", "=db", "time-series", "graph-database", "=olap", "=oltp"]),
    "data-pipelines": ("Data Pipelines & Streaming", "data-infrastructure", ["=etl", "=elt", "data-pipeline", "data-engineering", "streaming", "=kafka", "data-integration", "cdc"]),
    "analytics-bi": ("Analytics & BI", "data-infrastructure", ["analytics", "business-intelligence", "=bi", "data-visualization", "product-analytics", "web-analytics"]),
    "storage": ("Storage Systems", "data-infrastructure", ["object-storage", "=storage", "filesystem", "=s3", "distributed-storage", "backup"]),
    "crm-erp": ("CRM, ERP & Operations", "enterprise-software", ["=crm", "=erp", "=hrms", "helpdesk", "customer-support", "inventory"]),
    "collaboration": ("Collaboration & Knowledge", "enterprise-software", ["collaboration", "project-management", "=wiki", "knowledge-base", "note-taking", "productivity", "kanban", "=notion"]),
    "cms-commerce": ("CMS & Commerce", "enterprise-software", ["=cms", "headless-cms", "ecommerce", "e-commerce", "=commerce"]),
    "communication": ("Communication", "enterprise-software", ["=chat", "messaging", "=email", "video-conferencing", "team-chat"]),
}

# Technologies currently treated as frontier areas by the innovation proxy (editable, documented).
EMERGING_TECHNOLOGIES = {"llm", "ai-agents", "rag", "vector-search", "generative-media", "mlops", "serverless-edge", "browser-automation", "speech-audio"}

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#.\-]*")


@dataclass(frozen=True)
class TechnologyMatch:
    slug: str
    name: str
    category: str
    confidence: float
    matched_on: str  # topic | name | description
    priority: float = 0.0  # 0..1, higher when matched on an earlier topic


def classify(name: str, description: str | None, topics: list[str] | None) -> list[TechnologyMatch]:
    """Return technology matches ordered by confidence (highest first)."""
    topic_list = [t.lower() for t in (topics or [])]
    topic_pos = {t: i for i, t in reversed(list(enumerate(topic_list)))}
    name_tokens = set(re.split(r"[^a-z0-9+#]+", name.lower())) - {""}
    desc = (description or "").lower()
    desc_words = set(_WORD_RE.findall(desc))

    matches: list[TechnologyMatch] = []
    for slug, (tech_name, category, keywords) in TECHNOLOGIES.items():
        best = 0.0
        matched_on = ""
        priority = 0.0
        for raw in keywords:
            strict = raw.startswith("=")
            kw = raw.lstrip("=")
            if kw in topic_pos:
                best, matched_on = 0.9, "topic"
                priority = max(priority, 1.0 - topic_pos[kw] / len(topic_list))
            elif kw in name_tokens and best < 0.7:
                best, matched_on = 0.7, "name"
            elif not strict and best < 0.55:
                hit = (kw in desc) if (" " in kw or "-" in kw) else (kw in desc_words)
                if not hit and "-" in kw:
                    hit = kw.replace("-", " ") in desc
                if hit:
                    best, matched_on = 0.55, "description"
        if best:
            matches.append(TechnologyMatch(slug, tech_name, category, best, matched_on, priority))
    matches.sort(key=lambda m: (-m.confidence, -m.priority, m.slug))
    return matches


def primary_category(matches: list[TechnologyMatch]) -> str | None:
    """Pick the dominant category; None when nothing matched.

    Each category is scored by its strongest match (confidence, plus a bonus for appearing early in
    the maintainers' topic list) with a small credit for further matches, so a deployment trait
    mentioned in passing cannot outvote what the project primarily is.
    """
    if not matches:
        return None
    by_category: dict[str, list[float]] = {}
    for m in matches:
        by_category.setdefault(m.category, []).append(m.confidence + 0.3 * m.priority)
    order = list(CATEGORIES)

    def score(category: str) -> tuple[float, int]:
        weights = sorted(by_category[category], reverse=True)
        return round(weights[0] + 0.1 * sum(weights[1:]), 4), -order.index(category)

    return max(by_category, key=score)
