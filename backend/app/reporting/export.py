"""レポート出力（CSV / JSON, 基本設計書 §3 reporting）。"""

from __future__ import annotations

import csv
import io
from typing import Any


def candidates_to_csv(rows: list[dict[str, Any]]) -> str:
    """候補行を CSV 文字列へ。rows は list_candidates_* を dict 化したもの。"""
    fields = ["track_content_id", "type", "time_ms", "beat", "confidence", "rank"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k) for k in fields})
    return buf.getvalue()


def job_report(job: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """ジョブ結果の JSON レポート構造を組み立てる。"""
    by_type: dict[str, int] = {}
    for c in candidates:
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    return {
        "job_id": job.get("id"),
        "status": job.get("status"),
        "total": job.get("total"),
        "completed": job.get("completed"),
        "failed": job.get("failed"),
        "candidate_count": len(candidates),
        "candidates_by_type": by_type,
        "candidates": candidates,
    }
