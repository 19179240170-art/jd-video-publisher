from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Iterable

from .catalog import CatalogItem


GENERIC_TERMS = {
    "示例品牌", "examplebrand", "商品", "视频", "实拍", "测评", "海钓", "钓鱼", "渔具",
    "新款", "专用", "使用", "展示", "快抽", "慢摇", "路亚", "船钓", "近海",
}
PRODUCT_TYPE_TERMS = (
    "纺车轮", "水滴轮", "铁板轮", "电绞轮", "鼓轮", "鱼线轮", "数显轮",
    "铁板竿", "路亚竿", "船钓竿", "海钓竿", "鱼竿", "前导线", "鱼线",
)
SPLIT_TERMS = PRODUCT_TYPE_TERMS + (
    "慢摇", "快抽", "轻铁", "轻型", "二代", "三代", "数显", "鼓轮", "纺车",
    "水滴", "拖钓饵", "米诺", "半实心", "全实心", "海水", "大物", "小船",
)


@lru_cache(maxsize=200_000)
def normalize_text(value: str) -> str:
    value = value.lower().replace("（", "(").replace("）", ")")
    value = re.sub(r"(?<!\d)\d{1,2}[./月-]\d{1,2}(?:日)?", " ", value)
    value = re.sub(r"(?<!\d)2代", "二代", value)
    value = re.sub(r"(?<!\d)3代", "三代", value)
    value = re.sub(r"封面|副本|成片|最终版|final|主播出境|主播真人|真人出镜|怎么选|升级", " ", value, flags=re.I)
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)


@lru_cache(maxsize=200_000)
def _ngrams(value: str, size: int = 2) -> frozenset[str]:
    return frozenset(value[index : index + size] for index in range(max(0, len(value) - size + 1)))


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


@lru_cache(maxsize=20_000)
def _terms(value: str) -> tuple[str, ...]:
    normalized = normalize_text(value)
    terms = re.findall(r"[a-z]+\d*[a-z0-9-]*|\d+[a-z]+[a-z0-9-]*|\d{2,}", normalized)
    residual = normalized
    for split_term in sorted(SPLIT_TERMS, key=len, reverse=True):
        if split_term in normalized:
            terms.append(split_term)
            residual = residual.replace(split_term, " ")
    chinese = re.sub(r"[a-z0-9]", " ", residual)
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", chinese):
        if chunk not in GENERIC_TERMS:
            terms.append(chunk)
    return tuple(dict.fromkeys(term for term in terms if len(term) >= 2 and term not in GENERIC_TERMS))


@lru_cache(maxsize=20_000)
def _query_candidates(query: str) -> tuple[str, ...]:
    candidates = [part for part in re.split(r"\s+", query) if len(normalize_text(part)) >= 2]
    candidates.extend(_terms(query))
    return tuple(dict.fromkeys(candidates)) or (query,)


def _field_similarity(query: str, field: str) -> float:
    left = normalize_text(query)
    right = normalize_text(field)
    if not left or not right:
        return 0.0
    if left in right:
        return 1.0
    ratio = SequenceMatcher(None, left, right).ratio()
    gram_score = _jaccard(_ngrams(left), _ngrams(right))
    return max(ratio, 0.35 * ratio + 0.65 * gram_score)


def score_item(query: str, item: CatalogItem) -> float:
    # 商品名和短标题是主证据；销售属性里的颜色词容易与系列名重名，权重必须更低。
    fields = (
        (item.short_title, 1.00),
        (item.product_name, 1.00),
        (item.sales_attribute, 0.72),
        (item.merchant_sku, 0.86),
        (item.store_category, 0.78),
        (item.category, 0.74),
    )
    candidates = _query_candidates(query)
    field_score = max(
        _field_similarity(candidate, field) * weight
        for candidate in candidates
        for field, weight in fields
        if field
    )
    query_terms = _terms(query)
    normalized_item = normalize_text(item.searchable_text)
    if query_terms:
        coverage = sum(1 for term in query_terms if normalize_text(term) in normalized_item) / len(query_terms)
    else:
        coverage = 0.0
    item_grams = _ngrams(normalized_item)
    gram_coverage = max((_jaccard(_ngrams(normalize_text(candidate)), item_grams) for candidate in candidates), default=0.0)
    model_terms = re.findall(r"[a-z]+\d+[a-z0-9-]*|\d+[a-z]+[a-z0-9-]*", normalize_text(query))
    model_bonus = 0.12 if model_terms and any(term in normalized_item for term in model_terms) else 0.0
    stock_bonus = 0.02 if item.available_stock > 0 else 0.0
    return min(1.0, 0.62 * field_score + 0.20 * coverage + 0.13 * gram_coverage + model_bonus + stock_bonus)


@dataclass(frozen=True)
class MatchedSku:
    sku_id: str
    product_code: str
    product_name: str
    merchant_sku: str
    sales_attribute: str
    available_stock: int
    product_url: str
    score: float

    def to_dict(self) -> dict:
        result = asdict(self)
        result["score"] = round(self.score, 4)
        return result


@dataclass(frozen=True)
class MatchResult:
    query: str
    confidence: float
    family_product_code: str | None
    family_name: str | None
    skus: tuple[MatchedSku, ...]
    alternatives: tuple[dict, ...]
    review_reason: str

    def to_dict(self) -> dict:
        return {
            "query": self.query,
            "confidence": round(self.confidence, 4),
            "family_product_code": self.family_product_code,
            "family_name": self.family_name,
            "skus": [sku.to_dict() for sku in self.skus],
            "alternatives": list(self.alternatives),
            "review_reason": self.review_reason,
        }


def match_catalog(
    query: str,
    items: Iterable[CatalogItem],
    limit: int = 10,
    minimum_score: float = 0.52,
    preferred_product_code: str = "",
) -> MatchResult:
    all_items = list(items)
    scored: list[tuple[CatalogItem, float]] = []
    for item in all_items:
        if item.status and item.status != "上架":
            continue
        score = score_item(query, item)
        if score >= 0.20:
            scored.append((item, score))

    groups: dict[str, list[tuple[CatalogItem, float]]] = defaultdict(list)
    for item, score in scored:
        groups[item.product_code or item.sku_id].append((item, score))

    ranked_groups: list[tuple[str, float, list[tuple[CatalogItem, float]]]] = []
    for product_code, entries in groups.items():
        entry_scores = sorted((score for _, score in entries), reverse=True)
        # 变体数量只作为很小的并列决胜项，避免“大量颜色/钩号”压过真正的产品名。
        family_score = entry_scores[0] + min(0.015, math.log2(len(entries) + 1) * 0.003)
        ranked_groups.append((product_code, min(1.0, family_score), entries))
    ranked_groups.sort(key=lambda value: value[1], reverse=True)

    alternatives = tuple(
        {
            "product_code": product_code,
            "score": round(score, 4),
            "name": max(entries, key=lambda pair: pair[1])[0].short_title
            or max(entries, key=lambda pair: pair[1])[0].product_name,
        }
        for product_code, score, entries in ranked_groups[:5]
    )

    if preferred_product_code:
        preferred_entries = [
            (item, score_item(query, item))
            for item in all_items
            if item.product_code == preferred_product_code
            and (not item.status or item.status == "上架")
        ]
        if preferred_entries:
            preferred_entries.sort(
                key=lambda pair: (
                    pair[0].available_stock > 0,
                    pair[1],
                    pair[0].available_stock,
                ),
                reverse=True,
            )
            selected = tuple(
                MatchedSku(
                    sku_id=item.sku_id,
                    product_code=item.product_code,
                    product_name=item.product_name,
                    merchant_sku=item.merchant_sku,
                    sales_attribute=item.sales_attribute,
                    available_stock=item.available_stock,
                    product_url=item.product_url,
                    score=score,
                )
                for item, score in preferred_entries[: max(1, min(limit, 10))]
            )
            family_name = selected[0].product_name if selected else None
            confidence = max(0.90, max(score for _, score in preferred_entries))
            preferred_alternative = {
                "product_code": preferred_product_code,
                "score": round(confidence, 4),
                "name": selected[0].product_name if selected else "",
            }
            other_alternatives = tuple(
                value
                for value in alternatives
                if value["product_code"] != preferred_product_code
            )
            return MatchResult(
                query,
                min(confidence, 1.0),
                preferred_product_code,
                family_name,
                selected,
                (preferred_alternative, *other_alternatives[:4]),
                "本地ChatGPT已按抽帧与商品库锁定商品家族，发布前仍需人工确认",
            )

    if not ranked_groups or ranked_groups[0][1] < minimum_score:
        return MatchResult(query, ranked_groups[0][1] if ranked_groups else 0.0, None, None, (), alternatives, "未找到足够可信的商品家族")

    lead = 1.0
    if len(ranked_groups) > 1:
        lead = ranked_groups[0][1] - ranked_groups[1][1]
        if lead < 0.003:
            return MatchResult(
                query,
                ranked_groups[0][1],
                None,
                None,
                (),
                alternatives,
                "前两名商品家族过于接近，暂不自动填写SKU，请人工确认",
            )

    product_code, confidence, entries = ranked_groups[0]
    entries.sort(key=lambda pair: (pair[0].available_stock > 0, pair[1], pair[0].available_stock), reverse=True)
    selected = tuple(
        MatchedSku(
            sku_id=item.sku_id,
            product_code=item.product_code,
            product_name=item.product_name,
            merchant_sku=item.merchant_sku,
            sales_attribute=item.sales_attribute,
            available_stock=item.available_stock,
            product_url=item.product_url,
            score=score,
        )
        for item, score in entries[: max(1, min(limit, 10))]
    )
    family_name = selected[0].product_name if selected else None
    reasons: list[str] = []
    if confidence < 0.85:
        reasons.append("SKU匹配置信度不足85%")
    if lead < 0.03:
        reasons.append("候选商品家族分差较小")
    review_reason = "，".join(reasons) + ("，需要人工确认" if reasons else "")
    return MatchResult(query, confidence, product_code, family_name, selected, alternatives, review_reason)
