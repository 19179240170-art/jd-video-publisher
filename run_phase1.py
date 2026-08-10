from __future__ import annotations

import argparse
import json
from pathlib import Path

from phase1.pipeline import run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(description="京东视频第一阶段：抽帧、AI标题、SKU匹配、飞书审核队列")
    parser.add_argument("--config", type=Path, default=Path("config.json"), help="配置文件路径")
    parser.add_argument(
        "--analysis-file",
        type=Path,
        default=None,
        help="本地 ChatGPT 抽帧分析 JSON；未提供时生成待分析任务包",
    )
    parser.add_argument("--sync-feishu", action="store_true", help="将结果写入飞书多维表格")
    parser.add_argument("--force", action="store_true", help="忽略本地状态并重新处理")
    args = parser.parse_args()
    summary = run_pipeline(
        args.config.resolve(),
        args.analysis_file,
        args.sync_feishu,
        args.force,
    )
    print(json.dumps({
        "mode": summary["mode"],
        "catalog_items": summary["catalog_items"],
        "ready_videos": summary["ready_videos"],
        "local_analyses": summary["local_analyses"],
        "success": len(summary["results"]),
        "failures": summary["failures"],
        "review_queue": str((args.config.resolve().parent / "output" / "phase1" / "review_queue.json").resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if not summary["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
