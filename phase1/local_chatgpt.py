from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


ANALYSIS_FIELDS = [
    "product_name",
    "product_code_hint",
    "brand",
    "series",
    "model_numbers",
    "product_type",
    "visible_text",
    "selling_points",
    "video_summary",
    "keywords",
    "title_candidates",
    "confidence",
    "manual_review_reason",
]


@dataclass(frozen=True)
class VideoAnalysis:
    product_name: str
    product_code_hint: str
    brand: str
    series: str
    model_numbers: tuple[str, ...]
    product_type: str
    visible_text: tuple[str, ...]
    selling_points: tuple[str, ...]
    video_summary: str
    keywords: tuple[str, ...]
    title_candidates: tuple[str, ...]
    confidence: float
    manual_review_reason: str
    source: str = "local_chatgpt"

    def to_dict(self) -> dict:
        return {
            "product_name": self.product_name,
            "product_code_hint": self.product_code_hint,
            "brand": self.brand,
            "series": self.series,
            "model_numbers": list(self.model_numbers),
            "product_type": self.product_type,
            "visible_text": list(self.visible_text),
            "selling_points": list(self.selling_points),
            "video_summary": self.video_summary,
            "keywords": list(self.keywords),
            "title_candidates": list(self.title_candidates),
            "confidence": round(self.confidence, 4),
            "manual_review_reason": self.manual_review_reason,
            "source": self.source,
        }


def title_length(title: str) -> int:
    return len(title.strip())


def normalize_title(title: str, fallback_hint: str = "海钓装备") -> str:
    title = re.sub(r"[#\r\n\t]+", "", title).strip(" \"'“”‘’。！!?？；;")
    title = re.sub(r"\s+", "", title)
    if len(title) > 27:
        title = title[:27]
    if len(title) < 5:
        title = f"{title or fallback_hint}实战测评"
    return title[:27]


def analysis_from_payload(payload: dict, source: str = "local_chatgpt") -> VideoAnalysis:
    hint = str(payload.get("product_name") or "海钓装备")
    titles = tuple(
        normalize_title(str(title), hint)
        for title in payload.get("title_candidates", [])
    )
    titles = tuple(dict.fromkeys(title for title in titles if 5 <= title_length(title) <= 27))
    if not titles:
        titles = (normalize_title(f"{hint}真实使用体验", hint),)
    return VideoAnalysis(
        product_name=str(payload.get("product_name", "")),
        product_code_hint=str(payload.get("product_code_hint", "")),
        brand=str(payload.get("brand", "")),
        series=str(payload.get("series", "")),
        model_numbers=tuple(str(value) for value in payload.get("model_numbers", [])),
        product_type=str(payload.get("product_type", "")),
        visible_text=tuple(str(value) for value in payload.get("visible_text", [])),
        selling_points=tuple(str(value) for value in payload.get("selling_points", [])),
        video_summary=str(payload.get("video_summary", "")),
        keywords=tuple(str(value) for value in payload.get("keywords", [])),
        title_candidates=titles[:5],
        confidence=max(0.0, min(float(payload.get("confidence", 0)), 1.0)),
        manual_review_reason=str(payload.get("manual_review_reason", "")),
        source=source,
    )


def load_analysis_file(path: Path | None) -> dict[str, VideoAnalysis]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("analyses"), dict):
        entries = payload["analyses"]
    elif isinstance(payload, dict):
        entries = payload
    else:
        raise ValueError("本地 ChatGPT 分析文件必须是 JSON 对象")
    analyses: dict[str, VideoAnalysis] = {}
    for task_id, value in entries.items():
        if isinstance(value, dict):
            analyses[str(task_id)] = analysis_from_payload(value)
    return analyses


def draft_analysis(video_path: Path) -> VideoAnalysis:
    hint = re.sub(r"\d{1,2}[.月]\d{1,2}(?:日)?|封面|成片", "", video_path.stem).strip(" -_.")
    if not hint:
        hint = re.sub(r"\d{1,2}[.月]\d{1,2}(?:日)?", "", video_path.parent.name).strip(" -_.")
    type_rules = (
        (("纺车",), "纺车轮"),
        (("水滴",), "水滴轮"),
        (("鼓轮", "数显"), "鼓轮"),
        (("铁板轮",), "铁板轮"),
        (("拖钓饵", "米诺", "弯弓鱼", "霜降"), "路亚饵"),
        (("慢摇", "轻铁", "铁板竿", "小船", "海鲋", "根钓"), "铁板竿"),
    )
    product_type = "海钓装备"
    for markers, inferred_type in type_rules:
        if any(marker in hint for marker in markers):
            product_type = inferred_type
            break
    titles = (
        normalize_title(f"{hint}真实使用体验", hint),
        normalize_title(f"实测{hint}手感到底怎么样", hint),
        normalize_title(f"{hint}海钓表现值得看看", hint),
    )
    return VideoAnalysis(
        product_name=hint,
        product_code_hint="",
        brand="",
        series=hint,
        model_numbers=(),
        product_type=product_type,
        visible_text=(),
        selling_points=(),
        video_summary=f"本地 ChatGPT 尚未复核抽帧，当前仅按文件名生成待分析草稿：{hint}。",
        keywords=(hint, product_type),
        title_candidates=tuple(dict.fromkeys(titles)),
        confidence=0.35,
        manual_review_reason="等待本地 ChatGPT 查看抽帧后补全产品识别和标题。",
        source="local_draft",
    )
