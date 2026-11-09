"""run_log.json 기록.

- steps: 단계별 마지막 실행 결과 (성공/건너뜀/실패, 소요 시간, 경고, 오류)
- calls: API 호출 하나하나의 모델, 사용 토큰, 비용
- totals: 지금까지의 총 호출 수와 총 비용
"""
import time
from datetime import datetime
from pathlib import Path

from .config import read_json, write_json


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class RunLog:
    def __init__(self, run_dir: Path, sample_id: str, cfg_snapshot: dict):
        self.path = run_dir / "run_log.json"
        if self.path.exists():
            self.data = read_json(self.path)
        else:
            self.data = {
                "sample_id": sample_id,
                "created_at": now(),
                "config_snapshot": cfg_snapshot,
                "steps": {},
                "calls": [],
                "totals": {},
            }

    def save(self) -> None:
        calls = self.data["calls"]
        self.data["totals"] = {
            "api_calls": len(calls),
            "input_tokens": sum(c.get("input_tokens") or 0 for c in calls),
            "output_tokens": sum(c.get("output_tokens") or 0 for c in calls),
            "reasoning_tokens": sum(c.get("reasoning_tokens") or 0 for c in calls),
            "cost_usd": round(sum(c.get("cost_usd") or 0 for c in calls), 6),
        }
        write_json(self.path, self.data)

    def step_done(self, step: str, status: str, started: float,
                  warnings: list[str] | None = None, error: str | None = None) -> None:
        self.data["steps"][step] = {
            "status": status,  # ok / skipped / failed
            "finished_at": now(),
            "duration_sec": round(time.time() - started, 2),
            "warnings": warnings or [],
            "error": error,
        }
        self.save()

    def add_call(self, record: dict) -> None:
        self.data["calls"].append({"at": now(), **record})
        self.save()
