from __future__ import annotations

import argparse
import json
import os
import re
import time
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx


ROOT_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = ROOT_DIR / "_workspace"
OUTPUT_PATH = WORKSPACE_DIR / "landscape-ai-usecases.json"

DEFAULT_SEEDS: list[dict[str, str]] = [
    {
        "url": "https://www.autodesk.com/blogs/construction/spatial-ai/",
        "category": "construction_ai",
        "publisher": "Autodesk",
    },
    {
        "url": "https://www.autodesk.com/blogs/construction/autodesk-construction-artificial-intelligence/",
        "category": "construction_ai",
        "publisher": "Autodesk",
    },
    {
        "url": "https://www.procore.com/ai",
        "category": "construction_ai",
        "publisher": "Procore",
    },
    {
        "url": "https://buildots.com/",
        "category": "construction_ai",
        "publisher": "Buildots",
    },
    {
        "url": "https://www.asla.org/news-insights/the-field/putting-ai-to-work-practical-applications-of-ai-in-landscape-architecture",
        "category": "landscape_ai",
        "publisher": "ASLA",
    },
    {
        "url": "https://www.asla.org/news-insights/the-field/how-landscape-architects-are-incorporating-artificial-intelligence",
        "category": "landscape_ai",
        "publisher": "ASLA",
    },
    {
        "url": "https://www.asla.org/news-holding/field/2024/06/looking-over-the-horizon-digital-twins-and-the-future-of-landscape-architecture",
        "category": "landscape_ai",
        "publisher": "ASLA",
    },
    {
        "url": "https://landezine.com/artificial-intelligence-generative-design-and-landscape-architecture/",
        "category": "landscape_ai",
        "publisher": "Landezine",
    },
]

SEARCH_QUERIES: list[dict[str, Any]] = [
    {
        "query": "construction AI use case Autodesk Procore Buildots site:autodesk.com OR site:procore.com OR site:buildots.com",
        "category": "construction_ai",
        "allow_domains": ["autodesk.com", "procore.com", "buildots.com"],
    },
    {
        "query": "landscape architecture AI use case ASLA Landezine site:asla.org OR site:landezine.com",
        "category": "landscape_ai",
        "allow_domains": ["asla.org", "landezine.com"],
    },
]

CAPABILITY_RULES: list[tuple[str, list[str]]] = [
    ("progress tracking", ["progress tracking", "track progress", "project progress"]),
    ("delay forecasting", ["delay forecast", "forecast", "schedule certainty"]),
    ("risk prediction", ["risk", "construction iq", "predict", "priority"]),
    ("workflow assistance", ["draft", "summarize", "assist", "agent"]),
    ("field intelligence", ["spatial ai", "reality-based", "site data", "capture"]),
    ("site analysis", ["site analysis", "survey", "mapping"]),
    ("climate modeling", ["climate", "environmental", "resilience"]),
    ("documentation automation", ["documentation", "document", "report"]),
    ("concept ideation", ["generative", "ideation", "storytelling", "image"]),
    ("digital twin planning", ["digital twin", "digital twins"]),
]

OUTCOME_RULES: list[tuple[str, list[str]]] = [
    ("schedule certainty", ["delay", "schedule", "on course"]),
    ("risk reduction", ["risk", "issue", "unexpected", "visibility"]),
    ("productivity gain", ["efficiency", "productivity", "automate", "less friction"]),
    ("design exploration", ["ideation", "design process", "explore", "creative"]),
    ("documentation quality", ["documentation", "report", "summary"]),
    ("environmental insight", ["climate", "environmental", "sustainability"]),
]


def _progress_path() -> Path | None:
    raw = os.environ.get("SOEAK_PROGRESS_PATH")
    return Path(raw) if raw else None


def _error_log_path() -> Path | None:
    raw = os.environ.get("SOEAK_ERROR_LOG_PATH")
    return Path(raw) if raw else None


def _write_progress(payload: dict[str, Any]) -> None:
    path = _progress_path()
    if path is None:
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_error(payload: dict[str, Any]) -> None:
    path = _error_log_path()
    if path is None:
        return
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_seed_urls() -> list[dict[str, str]]:
    seed_env = os.environ.get("LANDSCAPE_SEED_URLS")
    if not seed_env:
        return DEFAULT_SEEDS
    try:
        parsed = json.loads(seed_env)
    except json.JSONDecodeError:
        return DEFAULT_SEEDS
    cleaned = []
    for item in parsed:
        if isinstance(item, dict) and item.get("url"):
            cleaned.append(
                {
                    "url": str(item["url"]),
                    "category": str(item.get("category", "construction_ai")),
                    "publisher": str(item.get("publisher", urlparse(str(item["url"])).netloc)),
                }
            )
    return cleaned or DEFAULT_SEEDS


def _decode_duckduckgo_href(href: str) -> str:
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/l/?"):
        query = parse_qs(urlparse(href).query)
        uddg = query.get("uddg")
        if uddg:
            return unquote(uddg[0])
    return href


def _search_duckduckgo(client: httpx.Client, query: str, allow_domains: list[str], limit: int) -> list[str]:
    try:
        response = client.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            timeout=20.0,
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        _append_error({"stage": "search", "query": query, "error": str(exc)})
        return []

    matches = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"', response.text, flags=re.I)
    results: list[str] = []
    for href in matches:
        url = _decode_duckduckgo_href(href)
        domain = urlparse(url).netloc.lower()
        if allow_domains and not any(domain.endswith(allowed) for allowed in allow_domains):
            continue
        if url not in results:
            results.append(url)
        if len(results) >= limit:
            break
    return results


def _strip_html(value: str) -> str:
    value = re.sub(r"(?is)<script.*?>.*?</script>", " ", value)
    value = re.sub(r"(?is)<style.*?>.*?</style>", " ", value)
    value = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", value)
    value = re.sub(r"(?is)<[^>]+>", " ", value)
    value = unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _extract_title(html: str, fallback_url: str) -> str:
    for pattern in [
        r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"',
        r'<meta[^>]+name="twitter:title"[^>]+content="([^"]+)"',
        r"<title[^>]*>(.*?)</title>",
    ]:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            return _strip_html(match.group(1))[:240]
    return fallback_url


def _extract_body(html: str) -> str:
    blocks = re.findall(r"(?is)<p[^>]*>(.*?)</p>", html)
    snippets = [_strip_html(block) for block in blocks]
    filtered = [snippet for snippet in snippets if len(snippet) >= 60]
    if not filtered:
        return _strip_html(html)[:4000]
    return "\n\n".join(filtered[:8])[:4000]


def _publisher_from_url(url: str, fallback: str | None = None) -> str:
    if fallback:
        return fallback
    domain = urlparse(url).netloc.lower()
    if "autodesk" in domain:
        return "Autodesk"
    if "procore" in domain:
        return "Procore"
    if "buildots" in domain:
        return "Buildots"
    if "asla" in domain:
        return "ASLA"
    if "landezine" in domain:
        return "Landezine"
    return domain


def _detect_capabilities(text: str) -> list[str]:
    text_l = text.lower()
    found: list[str] = []
    for name, needles in CAPABILITY_RULES:
        if any(needle in text_l for needle in needles):
            found.append(name)
    return found or ["workflow support"]


def _detect_outcomes(text: str) -> list[str]:
    text_l = text.lower()
    found: list[str] = []
    for name, needles in OUTCOME_RULES:
        if any(needle in text_l for needle in needles):
            found.append(name)
    return found or ["knowledge capture"]


def _make_statement(category: str, publisher: str, capabilities: list[str], outcomes: list[str]) -> str:
    sector = "landscape architecture" if category == "landscape_ai" else "construction"
    capability_text = ", ".join(capabilities[:2])
    outcome_text = ", ".join(outcomes[:2])
    return f"{publisher} describes {sector} AI use cases around {capability_text} to improve {outcome_text}."


def _fetch_page(client: httpx.Client, url: str, category: str, publisher: str | None = None) -> dict[str, Any] | None:
    try:
        response = client.get(url, timeout=30.0, follow_redirects=True, headers={"User-Agent": "OpenCrab-CrabHarness/0.2"})
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        _append_error({"stage": "fetch", "url": url, "error": str(exc)})
        return None

    title = _extract_title(response.text, url)
    body = _extract_body(response.text)
    page_publisher = _publisher_from_url(url, publisher)
    capabilities = _detect_capabilities(f"{title}\n{body}")
    outcomes = _detect_outcomes(f"{title}\n{body}")
    return {
        "url": str(response.url),
        "source_url": url,
        "title": title,
        "publisher": page_publisher,
        "category": category,
        "content": body,
        "capabilities": capabilities,
        "outcomes": outcomes,
        "statement": _make_statement(category, page_publisher, capabilities, outcomes),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic", default="landscape-construction-ai-usecases")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--delay-ms", type=int, default=250)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    _write_progress({"status": "started", "topic": args.topic, "done": 0, "total": 0})

    seeds = _load_seed_urls()
    urls: list[dict[str, str]] = list(seeds)

    if not args.dry_run:
        with httpx.Client() as client:
            for spec in SEARCH_QUERIES:
                discovered = _search_duckduckgo(
                    client=client,
                    query=str(spec["query"]),
                    allow_domains=list(spec["allow_domains"]),
                    limit=max(2, min(4, args.limit)),
                )
                for url in discovered:
                    if any(existing["url"] == url for existing in urls):
                        continue
                    urls.append(
                        {
                            "url": url,
                            "category": str(spec["category"]),
                            "publisher": _publisher_from_url(url),
                        }
                    )

    urls = urls[: args.limit]
    pages: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    if args.dry_run:
        pages = [
            {
                "url": spec["url"],
                "source_url": spec["url"],
                "title": f"Dry run seed: {spec['publisher']}",
                "publisher": spec["publisher"],
                "category": spec["category"],
                "content": "",
                "capabilities": [],
                "outcomes": [],
                "statement": f"Dry run placeholder for {spec['publisher']}.",
            }
            for spec in urls
        ]
    else:
        with httpx.Client() as client:
            total = len(urls)
            for index, spec in enumerate(urls, start=1):
                url = spec["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                page = _fetch_page(client, url, spec["category"], spec.get("publisher"))
                if page is not None:
                    pages.append(page)
                _write_progress(
                    {
                        "status": "running",
                        "topic": args.topic,
                        "done": index,
                        "total": total,
                        "last_url": url,
                        "pages_collected": len(pages),
                    }
                )
                time.sleep(max(args.delay_ms, 0) / 1000.0)

    dataset = {
        "topic": args.topic,
        "collected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed_count": len(seeds),
        "page_count": len(pages),
        "categories": sorted({page["category"] for page in pages}),
        "documents": pages,
        "use_cases": [
            {
                "publisher": page["publisher"],
                "category": page["category"],
                "title": page["title"],
                "url": page["url"],
                "statement": page["statement"],
                "capabilities": page["capabilities"],
                "outcomes": page["outcomes"],
            }
            for page in pages
        ],
    }
    OUTPUT_PATH.write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_progress(
        {
            "status": "completed",
            "topic": args.topic,
            "done": len(urls),
            "total": len(urls),
            "pages_collected": len(pages),
            "output_path": str(OUTPUT_PATH),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
