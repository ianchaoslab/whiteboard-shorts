"""AI 응답의 형식(JSON 모양)과 검사 규칙.

- 아래 클래스는 "AI 답에 이런 칸이 있어야 한다"는 약속이다.
  OpenAI Structured Outputs가 이 형식에 맞춰 답하게 한다.
- validate_* 함수는 형식만으로 확인할 수 없는 규칙(장면 순서, 개수 등)을 코드로 한 번 더 검사한다.
  돌려주는 값: (errors, warnings)
    errors   → 다시 물어봐야 하는 문제
    warnings → 멈추지 않고 run_log.json에 기록만 하는 문제
"""
import re
from typing import Literal

from pydantic import BaseModel

# ---------- 형식 ----------


class Fact(BaseModel):
    label: str
    value: str
    source_quote: str


class SummaryOut(BaseModel):
    core_message: str
    key_points: list[str]
    facts: list[Fact]
    promo_items: list[str]
    removed: list[str]


class SceneOut(BaseModel):
    section: Literal["intro", "body", "outro"]
    narration: str
    visual_idea: str


class ScriptOut(BaseModel):
    scenes: list[SceneOut]


class SceneOutV2(BaseModel):
    """프롬프트 v2: 음성용 문장(narration)과 자막용 문장(subtitle)을 따로 받는다."""
    section: Literal["intro", "body", "outro"]
    narration: str
    subtitle: str
    visual_idea: str


class ScriptOutV2(BaseModel):
    scenes: list[SceneOutV2]


class SceneVisualOut(BaseModel):
    scene_id: int
    scene_description: str
    uses_character: bool


class ImagePromptsOut(BaseModel):
    scenes: list[SceneVisualOut]


class CheckOut(BaseModel):
    ok: bool
    message: str


# ---------- 도우미 ----------


def squash(text: str) -> str:
    """공백·줄바꿈을 모두 지운 글. 원문에 그대로 있는지 비교할 때 쓴다."""
    return re.sub(r"\s+", "", text)


def numbers_in(text: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)*", text)


# ---------- 검사 ----------


def validate_summary(s: SummaryOut, source: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if not s.core_message.strip():
        errors.append("core_message가 비어 있습니다")
    if not 3 <= len(s.key_points) <= 6:
        errors.append(f"key_points는 3~6개여야 합니다 (현재 {len(s.key_points)}개)")
    if any(not p.strip() for p in s.key_points):
        errors.append("비어 있는 key_points가 있습니다")

    body = squash(source["title"] + source["body"])
    for f in s.facts:
        if squash(f.source_quote) not in body:
            warnings.append(f"facts '{f.label}'의 source_quote가 원문에 그대로 있지 않음")
        if squash(f.value) not in body:
            warnings.append(f"facts '{f.label}'의 value '{f.value}'가 원문에 그대로 있지 않음")
    return errors, warnings


def validate_script(s: ScriptOut | ScriptOutV2, cfg: dict,
                    source: dict) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    sc = cfg["script"]
    n = len(s.scenes)
    if not sc["scene_count_min"] <= n <= sc["scene_count_max"]:
        errors.append(f"장면 수는 {sc['scene_count_min']}~{sc['scene_count_max']}개여야 합니다 (현재 {n}개)")
    if n:
        if s.scenes[0].section != "intro":
            errors.append("첫 장면의 section은 intro여야 합니다")
        if s.scenes[-1].section != "outro":
            errors.append("마지막 장면의 section은 outro여야 합니다")
        if any(x.section != "body" for x in s.scenes[1:-1]):
            errors.append("첫 장면과 마지막 장면 사이의 section은 모두 body여야 합니다")
    for i, x in enumerate(s.scenes, start=1):
        if not x.narration.strip():
            errors.append(f"{i}번 장면 narration이 비어 있습니다")
        if not x.visual_idea.strip():
            errors.append(f"{i}번 장면 visual_idea가 비어 있습니다")
        if hasattr(x, "subtitle") and not x.subtitle.strip():
            errors.append(f"{i}번 장면 subtitle(자막용 문장)이 비어 있습니다")

    # 아래는 경고만 (멈추지 않음)
    if n != sc["scene_count"]:
        warnings.append(f"장면 수가 기본값 {sc['scene_count']}개와 다름 ({n}개)")
    total = sum(len(x.narration) for x in s.scenes)
    target = sc["narration_chars_target"]
    tol = sc["narration_chars_tolerance"]
    if not target * (1 - tol) <= total <= target * (1 + tol):
        note = " (목표는 임시값)" if sc.get("narration_chars_is_provisional") else ""
        warnings.append(f"대본 총 글자 수 {total}자가 목표 {target}자 ±{int(tol * 100)}% 범위 밖{note}")
    body = squash(source["title"] + source["body"])
    for i, x in enumerate(s.scenes, start=1):
        texts = [x.narration] + ([x.subtitle] if hasattr(x, "subtitle") else [])
        for num in sorted({n for t in texts for n in numbers_in(t)}):
            if num not in body:
                warnings.append(f"{i}번 장면의 숫자 '{num}'가 원문에 없음 (사실 확인 필요)")
        if hasattr(x, "subtitle"):
            ratio = len(x.subtitle) / max(1, len(x.narration))
            if not 0.6 <= ratio <= 1.4:
                warnings.append(f"{i}번 장면 자막 길이가 내레이션과 많이 다름 ({len(x.subtitle)}자 / {len(x.narration)}자)")
    return errors, warnings


def validate_image_prompts(s: ImagePromptsOut, scene_ids: list[int]) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    got = [x.scene_id for x in s.scenes]
    if got != scene_ids:
        errors.append(f"scene_id는 {scene_ids} 순서로 모두 있어야 합니다 (현재 {got})")
    for x in s.scenes:
        if not x.scene_description.strip():
            errors.append(f"{x.scene_id}번 장면 scene_description이 비어 있습니다")
        if re.search(r"[가-힣]", x.scene_description):
            warnings.append(f"{x.scene_id}번 장면 묘사에 한글이 섞여 있음 (영어로 쓰도록 지시함)")
    return errors, warnings
