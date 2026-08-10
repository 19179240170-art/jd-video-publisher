from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .catalog import load_catalog
from .feishu_api import FeishuClient, FeishuConfig
from .local_chatgpt import (
    ANALYSIS_FIELDS,
    VideoAnalysis,
    draft_analysis,
    load_analysis_file,
)
from .matching import MatchResult, match_catalog
from .media import discover_videos, extract_frames, file_sha256


DEFAULT_FIELD_MAP = {
    "task_id": "任务编号",
    "video_path": "视频文件",
    "preview_paths": "预览图路径",
    "summary": "AI视频摘要",
    "title": "发布标题",
    "alternative_titles": "备选标题",
    "skus": "商品SKU",
    "sku_reason": "SKU匹配说明",
    "sku_confidence": "SKU置信度",
    "topic": "参与话题",
    "label_type": "标签类型",
    "scheduled_publish_time": "定时发布时间",
    "review_status": "审核状态",
    "publish_status": "发布状态",
    "error": "失败原因",
}


@dataclass(frozen=True)
class PipelineConfig:
    video_root: Path
    catalog_path: Path
    output_root: Path
    topic: str = "#你的话题"
    label_type: str = "你的标签"
    scheduled_publish_time: str = ""
    frame_count: int = 10
    max_skus: int = 10
    local_analysis_path: Path | None = None
    ffmpeg_path: str | None = None
    field_map: dict[str, str] | None = None


def load_config(path: Path) -> tuple[PipelineConfig, dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent.resolve()

    def resolve(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else (base / candidate).resolve()

    pipeline = PipelineConfig(
        video_root=resolve(raw["video_root"]),
        catalog_path=resolve(raw["catalog_path"]),
        output_root=resolve(raw.get("output_root", "output/phase1")),
        topic=raw.get("topic", "#你的话题"),
        label_type=raw.get("label_type", "你的标签"),
        scheduled_publish_time=raw.get("scheduled_publish_time", ""),
        frame_count=int(raw.get("frame_count", 10)),
        max_skus=min(10, int(raw.get("max_skus", 10))),
        local_analysis_path=resolve(raw["local_analysis_path"]) if raw.get("local_analysis_path") else None,
        ffmpeg_path=raw.get("ffmpeg_path"),
        field_map={**DEFAULT_FIELD_MAP, **raw.get("feishu", {}).get("field_map", {})},
    )
    return pipeline, raw


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temporary = Path(handle.name)
    temporary.replace(path)


def _query_text(video_path: Path, analysis: VideoAnalysis) -> str:
    values = [
        video_path.parent.name,
        video_path.stem,
        analysis.product_name,
        analysis.series,
        analysis.product_type,
        *analysis.model_numbers,
        *analysis.visible_text,
        *analysis.keywords,
    ]
    return " ".join(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _feishu_fields(
    task_id: str,
    video_path: Path,
    frames: list[Path],
    analysis: VideoAnalysis,
    match: MatchResult,
    config: PipelineConfig,
    error: str = "",
) -> dict:
    mapping = config.field_map or DEFAULT_FIELD_MAP
    sku_ids = [sku.sku_id for sku in match.skus]
    sku_reason = (
        f"商品家族：{match.family_product_code or '未确定'}；"
        f"匹配置信度：{match.confidence:.0%}；"
        f"共选择{len(sku_ids)}个SKU。{match.review_reason}"
    )
    fields = {
        mapping["task_id"]: task_id,
        mapping["video_path"]: str(video_path),
        mapping["preview_paths"]: "\n".join(str(path) for path in frames[:5]),
        mapping["summary"]: analysis.video_summary,
        mapping["title"]: analysis.title_candidates[0],
        mapping["alternative_titles"]: "\n".join(analysis.title_candidates[1:]),
        mapping["skus"]: "\n".join(sku_ids),
        mapping["sku_reason"]: sku_reason,
        mapping["sku_confidence"]: round(match.confidence * 100, 2),
        mapping["topic"]: config.topic,
        mapping["label_type"]: config.label_type,
        mapping["scheduled_publish_time"]: config.scheduled_publish_time,
        mapping["review_status"]: "待人工审核",
        mapping["publish_status"]: "待审核",
        mapping["error"]: error,
    }
    if not config.scheduled_publish_time:
        fields.pop(mapping["scheduled_publish_time"], None)
    return {key: value for key, value in fields.items() if key}


def _feishu_client(raw: dict) -> FeishuClient | None:
    feishu = raw.get("feishu", {})
    secret_path = Path(raw.get("_config_dir", ".")) / ".secrets" / "feishu.json"
    secret = json.loads(secret_path.read_text(encoding="utf-8")) if secret_path.exists() else {}
    app_id = os.environ.get("FEISHU_APP_ID", secret.get("app_id", feishu.get("app_id", "")))
    app_secret = os.environ.get("FEISHU_APP_SECRET", secret.get("app_secret", feishu.get("app_secret", "")))
    app_token = os.environ.get("FEISHU_APP_TOKEN", secret.get("app_token", feishu.get("app_token", "")))
    table_id = os.environ.get("FEISHU_TABLE_ID", secret.get("table_id", feishu.get("table_id", "")))
    if not all((app_id, app_secret, app_token, table_id)):
        return None
    return FeishuClient(FeishuConfig(app_id, app_secret, app_token, table_id, feishu.get("base_url", "https://open.feishu.cn/open-apis")))


def run_pipeline(
    config_path: Path,
    analysis_file: Path | None = None,
    sync_feishu: bool = False,
    force: bool = False,
) -> dict:
    config, raw = load_config(config_path)
    raw["_config_dir"] = str(config_path.parent.resolve())
    config.output_root.mkdir(parents=True, exist_ok=True)
    items = load_catalog(config.catalog_path)
    videos, skipped = discover_videos(config.video_root)
    state_path = config.output_root / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"tasks": {}}
    selected_analysis_file = analysis_file.resolve() if analysis_file else config.local_analysis_path
    local_analyses = load_analysis_file(selected_analysis_file)
    feishu = _feishu_client(raw) if sync_feishu else None
    if sync_feishu and feishu is None:
        raise RuntimeError("已要求同步飞书，但飞书四项凭证尚未配置")
    existing_records: dict[str, str] = {}
    if feishu:
        task_field = (config.field_map or DEFAULT_FIELD_MAP)["task_id"]
        for record in feishu.list_records():
            task_id = str(record.get("fields", {}).get(task_field, ""))
            if task_id and record.get("record_id"):
                existing_records[task_id] = str(record["record_id"])

    results: list[dict] = []
    failures: list[dict] = []
    analysis_tasks: list[dict] = []
    for video_path in videos:
        try:
            digest = file_sha256(video_path)
            task_id = f"JD-{digest[:16]}"

            task_dir = config.output_root / "tasks" / task_id
            result_path = task_dir / "result.json"
            cached = (
                json.loads(result_path.read_text(encoding="utf-8"))
                if result_path.exists()
                else {}
            )
            cached_frames = [
                Path(value)
                for value in cached.get("frames", [])
                if Path(value).exists()
            ]
            if len(cached_frames) >= 3 and not force:
                frames = cached_frames
                metadata = cached.get("video_metadata", {})
            else:
                frames, metadata = extract_frames(
                    video_path,
                    task_dir / "frames",
                    config.frame_count,
                    config.ffmpeg_path,
                )
            analysis_tasks.append(
                {
                    "task_id": task_id,
                    "video_path": str(video_path),
                    "video_name": video_path.name,
                    "parent_folder": video_path.parent.name,
                    "frames": [str(path) for path in frames],
                    "analysis_present": task_id in local_analyses,
                    "required_output_fields": ANALYSIS_FIELDS,
                    "rules": {
                        "title_length": "5-27个字",
                        "max_skus": config.max_skus,
                        "topic": config.topic,
                        "label_type": config.label_type,
                    },
                }
            )
            analysis = local_analyses.get(task_id) or draft_analysis(video_path)
            query = _query_text(video_path, analysis)
            match = match_catalog(
                query,
                items,
                config.max_skus,
                preferred_product_code=analysis.product_code_hint,
            )
            fields = _feishu_fields(task_id, video_path, frames, analysis, match, config)
            record_id = str(cached.get("feishu_record_id") or existing_records.get(task_id) or "")
            status = "待人工审核" if task_id in local_analyses else "待本地ChatGPT分析"
            result = {
                "task_id": task_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "video_path": str(video_path),
                "video_sha256": digest,
                "video_metadata": metadata,
                "frames": [str(path) for path in frames],
                "analysis": analysis.to_dict(),
                "sku_match": match.to_dict(),
                "defaults": {
                    "topic": config.topic,
                    "label_type": config.label_type,
                    "scheduled_publish_time": config.scheduled_publish_time,
                },
                "feishu_fields": fields,
                "feishu_record_id": record_id or None,
                "status": status,
            }
            if feishu:
                # 已存在的飞书记录由审核人员维护，重复运行不能覆盖人工修改或审批状态。
                if not record_id:
                    result["feishu_record_id"] = feishu.create_record(fields, task_id)
            _atomic_json(result_path, result)
            state.setdefault("tasks", {})[task_id] = {"result_path": str(result_path), "video_path": str(video_path), "status": result["status"]}
            _atomic_json(state_path, state)
            results.append(result)
        except Exception as error:  # 单条失败不能阻塞整批视频
            failures.append({"video_path": str(video_path), "error": str(error)})

    queue = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": (
            "local_chatgpt"
            if local_analyses and len(local_analyses) >= len(videos)
            else "local_chatgpt_partial"
            if local_analyses
            else "local_chatgpt_pending"
        ),
        "local_analysis_file": str(selected_analysis_file) if selected_analysis_file else "",
        "local_analyses": len(local_analyses),
        "catalog_items": len(items),
        "ready_videos": len(videos),
        "skipped_incomplete": [str(path) for path in skipped],
        "results": results,
        "failures": failures,
    }
    _atomic_json(config.output_root / "local_chatgpt_tasks.json", {
        "generated_at": queue["generated_at"],
        "tasks": analysis_tasks,
    })
    _atomic_json(config.output_root / "review_queue.json", queue)
    _atomic_json(config.output_root / "feishu_payloads.json", [result["feishu_fields"] for result in results])
    return queue
