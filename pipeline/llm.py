"""OpenAI 호출을 한 곳에서 담당한다.

사용법은 OpenAI 공식 문서를 따른다 (2026-11-09 확인).
- Responses API + Structured Outputs(pydantic):
  https://developers.openai.com/api/docs/guides/structured-outputs
- 사용량(usage) 항목과 생각 토큰(reasoning tokens) 과금:
  https://developers.openai.com/api/docs/guides/reasoning

API 키는 환경 변수 OPENAI_API_KEY에서 읽는다. 키를 화면이나 파일에 쓰지 않는다.
"""
import os
import time
from typing import Callable

import openai
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from .config import ROOT
from .run_log import RunLog


class ValidationFailed(Exception):
    """다시 시도해도 AI 응답 형식이 맞지 않을 때."""


def cost_usd(cfg: dict, model: str, usage: dict) -> float | None:
    """사용 토큰 × 공식 단가. 단가표에 없는 모델이면 None."""
    price = cfg["prices"].get(model)
    if price is None:
        return None
    cached = usage["cached_tokens"]
    fresh_input = usage["input_tokens"] - cached
    total = (fresh_input * price["input"]
             + cached * price["cached_input"]
             + usage["output_tokens"] * price["output"]) / 1_000_000
    return round(total, 6)


def read_usage(resp) -> dict:
    u = resp.usage
    cached = getattr(u.input_tokens_details, "cached_tokens", 0) if u.input_tokens_details else 0
    reasoning = getattr(u.output_tokens_details, "reasoning_tokens", 0) if u.output_tokens_details else 0
    return {
        "input_tokens": u.input_tokens,
        "cached_tokens": cached or 0,
        "output_tokens": u.output_tokens,  # 생각 토큰 포함 (출력 가격으로 청구됨)
        "reasoning_tokens": reasoning or 0,
    }


class LLM:
    def __init__(self, cfg: dict, run_log: RunLog | None):
        # .env 파일의 값을 환경 변수로 불러온다 (이미 설정된 환경 변수는 덮어쓰지 않음)
        load_dotenv(ROOT / ".env", override=False)
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit(
                "❌ 환경 변수 OPENAI_API_KEY를 찾지 못했습니다.\n"
                "   .env 파일에 OPENAI_API_KEY=키값 형식으로 들어 있는지 확인하세요."
            )
        self.cfg = cfg
        self.run_log = run_log
        self.client = OpenAI(max_retries=cfg["api"]["sdk_max_retries"])

    def parse(self, step: str, prompt: str, schema: type[BaseModel],
              validate: Callable[[BaseModel], list[str]] | None = None,
              effort: str | None = None) -> tuple[BaseModel, dict]:
        """AI에게 JSON 형식으로 답을 받고 검사한다.

        형식 검사에 실패하면 문제점을 알려주며 최대 max_validation_retries번 다시 묻는다.
        돌려주는 값: (검사를 통과한 응답, 이 단계의 사용량 합계)
        """
        model = self.cfg["models"]["text"]
        effort = effort or self.cfg["models"]["text_reasoning_effort"]
        attempts = 1 + self.cfg["api"]["max_validation_retries"]
        feedback = ""
        step_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                      "reasoning_tokens": 0, "cost_usd": 0.0}

        for attempt in range(1, attempts + 1):
            started = time.time()
            try:
                resp = self.client.responses.parse(
                    model=model,
                    input=prompt + feedback,
                    text_format=schema,
                    reasoning={"effort": effort},
                    max_output_tokens=self.cfg["models"]["max_output_tokens"],
                    store=False,
                )
            except openai.OpenAIError as e:
                self._log(step, attempt, model, effort, None, started, ok=False,
                          error=f"{type(e).__name__}: {str(e)[:300]}")
                raise

            usage = read_usage(resp)
            parsed = resp.output_parsed
            if parsed is None:
                problems = ["응답을 정해진 JSON 형식으로 읽지 못했습니다"]
            else:
                problems = validate(parsed) if validate else []

            cost = self._log(step, attempt, model, effort, usage, started,
                             ok=not problems, error="; ".join(problems) or None)
            step_usage["calls"] += 1
            for k in ("input_tokens", "output_tokens", "reasoning_tokens"):
                step_usage[k] += usage[k]
            step_usage["cost_usd"] = round(step_usage["cost_usd"] + (cost or 0), 6)

            if not problems:
                return parsed, step_usage

            print(f"   ⚠️ {step} 응답 형식 문제 (시도 {attempt}/{attempts}): {'; '.join(problems)}")
            feedback = ("\n\n## 이전 응답의 문제 (반드시 고쳐서 다시 답할 것)\n"
                        + "\n".join(f"- {p}" for p in problems))

        raise ValidationFailed(f"{step}: {attempts}번 시도했지만 형식 검사를 통과하지 못했습니다")

    def _log(self, step, attempt, model, effort, usage, started, ok, error) -> float | None:
        cost = cost_usd(self.cfg, model, usage) if usage else None
        if self.run_log:
            self.run_log.add_call({
                "step": step,
                "attempt": attempt,
                "model": model,
                "reasoning_effort": effort,
                **(usage or {}),
                "cost_usd": cost,
                "duration_sec": round(time.time() - started, 2),
                "ok": ok,
                "error": error,
            })
        return cost
