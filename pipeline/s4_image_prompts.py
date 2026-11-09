"""S4 이미지 프롬프트: 장면별 그림 묘사를 만들고 스타일 프리셋을 붙여 scenes.json을 갱신한다 (API 1회).

AI는 "무엇을 그릴지"만 영어로 쓰고, 그림체 문장은 코드가 프리셋 파일에서
모든 장면에 똑같이 붙인다. 그래서 장면마다 그림체 지시가 달라지지 않는다.
"""
import json
from pathlib import Path

from .config import (STALE_NOTE, cache_action, fill, load_preset, load_prompt, read_json, sha,
                     write_json)
from .schemas import ImagePromptsOut, validate_image_prompts

OUTPUT = "scenes.json"
PROMPT_FILE = "s4_image_prompt.md"


def has_output(run_dir: Path) -> bool:
    path = run_dir / OUTPUT
    return path.exists() and all(s.get("image_prompt") for s in read_json(path)["scenes"])


def build_image_prompt(description: str, uses_character: bool, preset: dict) -> str:
    parts = [description.strip()]
    if uses_character:
        parts.append(preset["character"].strip())
    parts += [preset["style"].strip(), preset["no_text"].strip()]
    return " ".join(parts)


def run(ctx, force: bool = False) -> tuple[str, list[str]]:
    path = ctx.run_dir / OUTPUT
    if not path.exists():
        raise SystemExit("❌ scenes.json이 없습니다. S3를 먼저 실행하세요.")
    data = read_json(path)
    preset = load_preset(ctx.cfg)
    template = load_prompt(ctx.cfg, PROMPT_FILE)
    models = ctx.cfg["models"]

    scene_list = [{"id": s["id"], "section": s["section"], "narration": s["narration"],
                   "visual_idea": s["visual_idea"]} for s in data["scenes"]]
    # 데이터 = S3 대본 / 설정 = 프롬프트, 스타일 프리셋, 모델
    data_sha = sha({"scenes": scene_list})
    settings_sha = sha({"prompt": template, "preset": preset,
                        "model": models["text"], "effort": models["text_reasoning_effort"]})
    done = all(s.get("image_prompt") for s in data["scenes"])
    action = cache_action(data.get("meta") if done else None, data_sha, settings_sha, force,
                          prefix="s4_")
    if action == "upgrade":
        data["meta"].update(s4_data_sha=data_sha, s4_settings_sha=settings_sha)
        write_json(path, data)
    if action in ("skip", "upgrade"):
        return "skipped", []
    if action == "stale":
        return "skipped", [STALE_NOTE]

    scene_ids = [s["id"] for s in data["scenes"]]
    # v2 프롬프트는 도입 장면에 주제 요소를 넣기 위해 제목·핵심 메시지도 쓴다 (v1에는 그 자리가 없어 영향 없음)
    summary_path = ctx.run_dir / "summary.json"
    core = read_json(summary_path).get("core_message", "") if summary_path.exists() else ""
    prompt = fill(template, {"scenes_json": json.dumps(scene_list, ensure_ascii=False, indent=2),
                             "title": data.get("title", ""), "core_message": core})
    parsed, usage = ctx.llm().parse(
        "s4", prompt, ImagePromptsOut,
        validate=lambda s: validate_image_prompts(s, scene_ids)[0])
    _, warnings = validate_image_prompts(parsed, scene_ids)

    by_id = {x.scene_id: x for x in parsed.scenes}
    for s in data["scenes"]:
        v = by_id[s["id"]]
        s["scene_description"] = v.scene_description
        s["uses_character"] = v.uses_character
        s["image_prompt"] = build_image_prompt(v.scene_description, v.uses_character, preset)

    data.setdefault("warnings", {})["s4"] = warnings
    data.setdefault("meta", {}).update({"s4_data_sha": data_sha, "s4_settings_sha": settings_sha,
                                        "s4_usage": usage})
    write_json(path, data)
    return "ok", warnings
