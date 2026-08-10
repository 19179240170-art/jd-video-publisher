from __future__ import annotations

import argparse
import json
from pathlib import Path

from phase2.queue import (
    build_publish_queue,
    claim_next_task,
    claim_task,
    complete_task,
    fail_task,
    release_task,
    reschedule_pending_tasks,
)


ROOT = Path(__file__).resolve().parent
CLAIMED_JOB_PATH = ROOT / "output" / "phase2" / "claimed_job.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="京东视频第二阶段：飞书审核队列")
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--claim", metavar="TASK_ID", help="校验并认领一个待发布任务")
    actions.add_argument("--claim-next", action="store_true", help="认领队列中第一条可发布任务")
    actions.add_argument("--complete-claimed", action="store_true", help="将当前认领任务标记为已定时")
    actions.add_argument("--fail-claimed", action="store_true", help="将当前认领任务标记为失败")
    actions.add_argument("--release-claimed", action="store_true", help="将当前认领任务退回待发布")
    actions.add_argument("--reschedule-latest", action="store_true", help="最新视频优先，从17:00起每20分钟重排待发布任务")
    actions.add_argument("--complete", metavar="TASK_ID", help="把发布中的任务标记为已定时")
    actions.add_argument("--fail", metavar="TASK_ID", help="把任务标记为失败")
    parser.add_argument("--message", default="", help="失败原因，与 --fail 配合")
    parser.add_argument("--start-hour", type=int, default=17, help="定时发布起始小时")
    parser.add_argument("--start-minute", type=int, default=0, help="定时发布起始分钟")
    parser.add_argument("--interval-minutes", type=int, default=20, help="定时发布间隔分钟")
    parser.add_argument("--limit", type=int, default=30, help="本次重排条数上限")
    args = parser.parse_args()

    if args.claim_next:
        job = claim_next_task(ROOT)
        if job:
            CLAIMED_JOB_PATH.parent.mkdir(parents=True, exist_ok=True)
            CLAIMED_JOB_PATH.write_text(
                json.dumps(job.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        elif CLAIMED_JOB_PATH.exists():
            CLAIMED_JOB_PATH.unlink()
        result = {
            "action": "claim_next",
            "job": job.to_dict() if job else None,
            "message": "当前没有满足条件的任务" if job is None else "",
        }
    elif args.complete_claimed:
        job = json.loads(CLAIMED_JOB_PATH.read_text(encoding="utf-8"))
        complete_task(ROOT, str(job["task_id"]))
        result = {
            "action": "complete_claimed",
            "task_id": job["task_id"],
            "status": "已定时",
        }
    elif args.fail_claimed:
        job = json.loads(CLAIMED_JOB_PATH.read_text(encoding="utf-8"))
        fail_task(ROOT, str(job["task_id"]), args.message)
        result = {
            "action": "fail_claimed",
            "task_id": job["task_id"],
            "status": "失败",
        }
    elif args.release_claimed:
        job = json.loads(CLAIMED_JOB_PATH.read_text(encoding="utf-8"))
        release_task(ROOT, str(job["task_id"]))
        CLAIMED_JOB_PATH.unlink(missing_ok=True)
        result = {
            "action": "release_claimed",
            "task_id": job["task_id"],
            "status": "待发布",
        }
    elif args.reschedule_latest:
        scheduled = reschedule_pending_tasks(
            ROOT,
            start_hour=args.start_hour,
            start_minute=args.start_minute,
            interval_minutes=args.interval_minutes,
            limit=args.limit,
        )
        result = {
            "action": "reschedule_latest",
            "count": len(scheduled),
            "scheduled": scheduled,
        }
    elif args.claim:
        result = {"action": "claim", "job": claim_task(ROOT, args.claim).to_dict()}
    elif args.complete:
        complete_task(ROOT, args.complete)
        result = {"action": "complete", "task_id": args.complete, "status": "已定时"}
    elif args.fail:
        fail_task(ROOT, args.fail, args.message)
        result = {"action": "fail", "task_id": args.fail, "status": "失败"}
    else:
        queue = build_publish_queue(ROOT)
        result = {
            "action": "preflight",
            "source_records": queue["source_records"],
            "eligible_count": queue["eligible_count"],
            "blocked_count": queue["blocked_count"],
            "queue_file": str(ROOT / "output" / "phase2" / "publish_queue.json"),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
