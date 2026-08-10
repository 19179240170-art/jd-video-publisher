from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from phase1.feishu_api import FeishuClient, FeishuConfig


SHANGHAI = ZoneInfo("Asia/Shanghai")
DEFAULT_TOPIC = "#你的话题"
DEFAULT_LABEL_TYPE = "你的标签"
ALLOWED_PUBLISH_STATUSES = {"待审核", "待发布"}


@dataclass(frozen=True)
class PublishJob:
    record_id: str
    task_id: str
    video_path: str
    cover_path: str
    title: str
    skus: tuple[str, ...]
    topic: str
    label_type: str
    scheduled_publish_time: str
    scheduled_publish_timestamp_ms: int
    review_status: str
    publish_status: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["skus"] = list(self.skus)
        return payload


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        pieces = []
        for item in value:
            if isinstance(item, dict):
                pieces.append(str(item.get("text") or item.get("name") or item.get("value") or ""))
            else:
                pieces.append(str(item))
        return "".join(pieces).strip()
    if isinstance(value, dict):
        return str(value.get("text") or value.get("name") or value.get("value") or "").strip()
    return str(value).strip()


def _video_recency_key(video_path: str) -> tuple[int, float]:
    path = Path(video_path)
    modified = path.stat().st_mtime if path.is_file() else 0
    match = re.search(
        r"[\\/](\d{1,2})月[\\/](\d{1,2})\.(\d{1,2})(?:[\\/]|$)",
        video_path,
    )
    if match:
        month = int(match.group(2))
        day = int(match.group(3))
        return month * 100 + day, modified
    return 0, modified


def parse_skus(value: Any) -> tuple[str, ...]:
    text = _as_text(value)
    values = re.findall(r"\d{6,}", text)
    return tuple(dict.fromkeys(values))


def parse_schedule(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number, tz=SHANGHAI)

    text = _as_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return parse_schedule(float(text))

    normalized = text.replace("年", "-").replace("月", "-").replace("日", " ")
    normalized = normalized.replace("/", "-").strip()
    if normalized.endswith("Z"):
        parsed = datetime.fromisoformat(normalized[:-1] + "+00:00")
    else:
        parsed = None
        for pattern in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ):
            try:
                parsed = datetime.strptime(normalized, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SHANGHAI)
    return parsed.astimezone(SHANGHAI)


def validate_record(
    record: dict[str, Any],
    *,
    now: datetime | None = None,
    minimum_lead_time: timedelta = timedelta(hours=2),
    cover_path: str | None = None,
) -> tuple[PublishJob | None, list[str]]:
    fields = record.get("fields", {})
    task_id = _as_text(fields.get("任务编号"))
    video_path = _as_text(fields.get("视频文件"))
    title = _as_text(fields.get("发布标题"))
    skus = parse_skus(fields.get("商品SKU"))
    topic = _as_text(fields.get("参与话题"))
    label_type = _as_text(fields.get("标签类型"))
    review_status = _as_text(fields.get("审核状态"))
    publish_status = _as_text(fields.get("发布状态"))
    schedule = parse_schedule(fields.get("定时发布时间"))
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)

    reasons: list[str] = []
    if not task_id:
        reasons.append("缺少任务编号")
    if not video_path:
        reasons.append("缺少视频文件")
    elif not Path(video_path).is_file():
        reasons.append("本地视频文件不存在")
    if cover_path is not None and not Path(cover_path).is_file():
        reasons.append("缺少符合京东要求的本地封面图")
    if not 5 <= len(title) <= 27:
        reasons.append("标题必须为5-27个字")
    if not 1 <= len(skus) <= 10:
        reasons.append("商品SKU必须为1-10个")
    if topic != DEFAULT_TOPIC:
        reasons.append(f"参与话题必须为{DEFAULT_TOPIC}")
    if label_type != DEFAULT_LABEL_TYPE:
        reasons.append(f"标签类型必须为{DEFAULT_LABEL_TYPE}")
    if review_status != "已批准":
        reasons.append("审核状态尚未批准")
    if publish_status not in ALLOWED_PUBLISH_STATUSES:
        reasons.append("发布状态不是待审核或待发布")
    if schedule is None:
        reasons.append("缺少或无法识别定时发布时间")
    elif schedule < current + minimum_lead_time:
        reasons.append("定时发布时间必须至少晚于当前时间2小时")

    if reasons or schedule is None:
        return None, reasons
    job = PublishJob(
        record_id=str(record.get("record_id") or ""),
        task_id=task_id,
        video_path=video_path,
        cover_path=cover_path or "",
        title=title,
        skus=skus,
        topic=topic,
        label_type=label_type,
        scheduled_publish_time=schedule.strftime("%Y-%m-%d %H:%M"),
        scheduled_publish_timestamp_ms=int(schedule.timestamp() * 1000),
        review_status=review_status,
        publish_status=publish_status,
    )
    return job, []


def load_feishu_client(root: Path) -> FeishuClient:
    secret_path = root / ".secrets" / "feishu.json"
    if not secret_path.exists():
        raise RuntimeError("缺少本机飞书凭证文件：.secrets/feishu.json")
    secret = json.loads(secret_path.read_text(encoding="utf-8"))
    required = ("app_id", "app_secret", "app_token", "table_id")
    missing = [key for key in required if not secret.get(key)]
    if missing:
        raise RuntimeError(f"飞书凭证缺少：{', '.join(missing)}")
    return FeishuClient(
        FeishuConfig(
            app_id=secret["app_id"],
            app_secret=secret["app_secret"],
            app_token=secret["app_token"],
            table_id=secret["table_id"],
        )
    )


def resolve_cover_path(root: Path, task_id: str) -> str:
    manifest_path = root / "output" / "phase2" / "cover_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        candidate = Path(str(manifest.get("covers", {}).get(task_id, "")))
        if candidate.is_file() and 204_800 <= candidate.stat().st_size <= 5 * 1024 * 1024:
            return str(candidate)
    frames_dir = root / "output" / "phase1" / "tasks" / task_id / "frames"
    if frames_dir.is_dir():
        candidates = sorted(
            frames_dir.glob("*.jpg"),
            key=lambda path: (path.name != "cover.jpg", path.name),
        )
        for candidate in candidates:
            if 204_800 <= candidate.stat().st_size <= 5 * 1024 * 1024:
                return str(candidate)
    return ""


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=path.parent,
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        temporary = Path(handle.name)
    temporary.replace(path)


def build_publish_queue(
    root: Path,
    *,
    output_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    client = load_feishu_client(root)
    records = client.list_records()
    eligible: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for record in records:
        fields = record.get("fields", {})
        task_id = _as_text(fields.get("任务编号"))
        job, reasons = validate_record(
            record,
            now=now,
            cover_path=resolve_cover_path(root, task_id),
        )
        if job:
            eligible.append(job.to_dict())
        else:
            fields = record.get("fields", {})
            blocked.append(
                {
                    "record_id": str(record.get("record_id") or ""),
                    "task_id": _as_text(fields.get("任务编号")),
                    "title": _as_text(fields.get("发布标题")),
                    "reasons": reasons,
                }
            )
    eligible.sort(
        key=lambda job: _video_recency_key(
            str(job.get("video_path") or "")
        ),
        reverse=True,
    )
    payload = {
        "generated_at": datetime.now(SHANGHAI).isoformat(),
        "source_records": len(records),
        "eligible_count": len(eligible),
        "blocked_count": len(blocked),
        "eligible": eligible,
        "blocked": blocked,
    }
    _atomic_json(output_path or root / "output" / "phase2" / "publish_queue.json", payload)
    return payload


def _find_record(client: FeishuClient, task_id: str) -> dict[str, Any]:
    for record in client.list_records():
        if _as_text(record.get("fields", {}).get("任务编号")) == task_id:
            return record
    raise KeyError(f"飞书中未找到任务：{task_id}")


def claim_task(root: Path, task_id: str) -> PublishJob:
    client = load_feishu_client(root)
    record = _find_record(client, task_id)
    job, reasons = validate_record(
        record,
        cover_path=resolve_cover_path(root, task_id),
    )
    if job is None:
        raise RuntimeError(f"任务不满足发布条件：{'；'.join(reasons)}")
    client.update_record(job.record_id, {"发布状态": "发布中", "失败原因": ""})
    return job


def claim_next_task(root: Path) -> PublishJob | None:
    queue = build_publish_queue(root)
    if not queue["eligible"]:
        return None
    return claim_task(root, str(queue["eligible"][0]["task_id"]))


def release_task(root: Path, task_id: str) -> None:
    client = load_feishu_client(root)
    record = _find_record(client, task_id)
    current = _as_text(
        record.get("fields", {}).get("\u53d1\u5e03\u72b6\u6001")
    )
    if current != "\u53d1\u5e03\u4e2d":
        raise RuntimeError(
            f"\u4efb\u52a1\u5f53\u524d\u72b6\u6001\u4e3a\u201c{current}\u201d\uff0c"
            "\u53ea\u6709\u201c\u53d1\u5e03\u4e2d\u201d\u53ef\u9000\u56de\u5f85\u53d1\u5e03"
        )
    client.update_record(
        str(record["record_id"]),
        {
            "\u53d1\u5e03\u72b6\u6001": "\u5f85\u53d1\u5e03",
            "\u5931\u8d25\u539f\u56e0": "",
        },
    )


def reschedule_pending_tasks(
    root: Path,
    *,
    start_hour: int = 17,
    start_minute: int = 0,
    interval_minutes: int = 20,
    limit: int = 30,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    client = load_feishu_client(root)
    current = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    start = current.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )
    if start < current + timedelta(hours=2):
        start += timedelta(days=1)

    candidates: list[
        tuple[tuple[int, float], dict[str, Any], str, str]
    ] = []
    for record in client.list_records():
        fields = record.get("fields", {})
        if _as_text(fields.get("\u5ba1\u6838\u72b6\u6001")) != "\u5df2\u6279\u51c6":
            continue
        if _as_text(fields.get("\u53d1\u5e03\u72b6\u6001")) != "\u5f85\u53d1\u5e03":
            continue
        task_id = _as_text(fields.get("\u4efb\u52a1\u7f16\u53f7"))
        video_path = _as_text(fields.get("\u89c6\u9891\u6587\u4ef6"))
        path = Path(video_path)
        if not task_id or not path.is_file():
            continue
        candidates.append(
            (_video_recency_key(video_path), record, task_id, video_path)
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    scheduled: list[dict[str, Any]] = []
    for index, (_, record, task_id, video_path) in enumerate(candidates[:limit]):
        publish_time = start + timedelta(minutes=interval_minutes * index)
        client.update_record(
            str(record["record_id"]),
            {
                "\u5b9a\u65f6\u53d1\u5e03\u65f6\u95f4": int(
                    publish_time.timestamp() * 1000
                ),
                "\u5931\u8d25\u539f\u56e0": "",
            },
        )
        scheduled.append(
            {
                "task_id": task_id,
                "video_path": video_path,
                "scheduled_publish_time": publish_time.strftime("%Y-%m-%d %H:%M"),
            }
        )
    return scheduled


def complete_task(root: Path, task_id: str, status: str = "已定时") -> None:
    if status not in {"已定时", "已发布"}:
        raise ValueError("完成状态只能是已定时或已发布")
    client = load_feishu_client(root)
    record = _find_record(client, task_id)
    current = _as_text(record.get("fields", {}).get("发布状态"))
    if current != "发布中":
        raise RuntimeError(f"任务当前状态为“{current}”，只有“发布中”可标记完成")
    client.update_record(str(record["record_id"]), {"发布状态": status, "失败原因": ""})


def fail_task(root: Path, task_id: str, message: str) -> None:
    client = load_feishu_client(root)
    record = _find_record(client, task_id)
    client.update_record(
        str(record["record_id"]),
        {"发布状态": "失败", "失败原因": message[:1000] or "京东发布失败"},
    )
