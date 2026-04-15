from __future__ import annotations

from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

_analyzer: AnalyzerEngine | None = None


def _analyzer_engine() -> AnalyzerEngine:
    global _analyzer
    if _analyzer is None:
        provider = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
        )
        nlp_engine = provider.create_engine()
        _analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
    return _analyzer


@dataclass(frozen=True)
class CleansingResult:
    sanitized_text: str
    mask_map: dict[str, str]
    mask_summary: dict[str, int]


def cleanse_text_presidio(text: str) -> CleansingResult:
    analyzer = _analyzer_engine()
    results = analyzer.analyze(text=text, language="en")

    counters: dict[str, int] = {}
    mask_map: dict[str, str] = {}
    mask_summary: dict[str, int] = {}

    sorted_results = sorted(results, key=lambda r: (r.start, r.end))

    token_assignments: list[tuple[int, int, str, str]] = []
    for r in sorted_results:
        entity = str(r.entity_type)
        counters[entity] = counters.get(entity, 0) + 1
        token = f"<{entity}_{counters[entity]}>"
        original = text[r.start : r.end]
        token_assignments.append((r.start, r.end, token, original))

        mask_map[token] = original
        mask_summary[entity] = mask_summary.get(entity, 0) + 1

    out = text
    for start, end, token, _original in reversed(token_assignments):
        out = out[:start] + token + out[end:]

    return CleansingResult(sanitized_text=out, mask_map=mask_map, mask_summary=mask_summary)

