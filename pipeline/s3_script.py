"""S3 대본: 도입·설명·결론 구조의 장면별 대본을 scenes.json으로 저장한다 (API 1회).

대본 규칙(도입·설명·결론, 원문에 없는 사실 금지, 결론 CTA)은 prompts/{버전}/s3_script.md에 있다.
글자 수는 AI가 아니라 코드가 직접 센다.
"""
import json
from pathlib import Path

from .config import (STALE_NOTE, cache_action, fill, load_prompt, load_prompt_toml,
                     prompt_features, read_json, sha, write_json)
from .schemas import ScriptOut, ScriptOutV2, validate_script

OUTPUT = "scenes.json"
PROMPT_FILE = "s3_script.md"
CTA_FILE = "cta_rules.toml"


def has_output(run_dir: Path) -> bool:
    return (run_dir / OUTPUT).exists()


def summary_for_prompt(summary: dict) -> str:
    keep = {k: summary[k] for k in ("core_message", "key_points", "facts", "promo_items")}
    return json.dumps(keep, ensure_ascii=False, indent=2)


def run(ctx, force: bool = False) -> tuple[str, list[str]]:
    cfg = ctx.cfg
    for name in ("source.json", "summary.json"):
        if not (ctx.run_dir / name).exists():
            raise SystemExit(f"❌ {name}이 없습니다. 앞 단계를 먼저 실행하세요.")
    source = read_json(ctx.run_dir / "source.json")
    summary = read_json(ctx.run_dir / "summary.json")

    sc, proj, models = cfg["script"], cfg["project"], cfg["models"]
    template = load_prompt(cfg, PROMPT_FILE)
    cta = load_prompt_toml(cfg, CTA_FILE)[proj["cta_mode"]]
    values = {
        "target_duration_sec": sc["target_duration_sec"],
        "min_duration_sec": sc["min_duration_sec"],
        "max_duration_sec": sc["max_duration_sec"],
        "scene_count": sc["scene_count"],
        "narration_chars_target": sc["narration_chars_target"],
        "chars_per_scene": round(sc["narration_chars_target"] / sc["scene_count"]),
        "body_promo_rule": cta["body_promo_rule"],
        "outro_rule": cta["outro_rule"],
        "summary_json": summary_for_prompt(summary),
        "title": source["title"],
        "body": source["body"],
    }

    # 데이터 = 원문 + 요약 / 설정 = 프롬프트, CTA 규칙, 길이·장면 수 설정, 모델
    data_sha = sha({"title": source["title"], "body": source["body"],
                    "summary": values["summary_json"]})
    settings_sha = sha({"prompt": template, "cta": cta, "script_cfg": sc,
                        "model": models["text"], "effort": models["text_reasoning_effort"]})
    out = ctx.run_dir / OUTPUT
    existing = read_json(out) if out.exists() else None
    action = cache_action(existing and existing.get("meta"), data_sha, settings_sha, force,
                          prefix="s3_")
    if action == "upgrade":
        existing["meta"].update(s3_data_sha=data_sha, s3_settings_sha=settings_sha)
        write_json(out, existing)
    if action in ("skip", "upgrade"):
        return "skipped", []
    if action == "stale":
        return "skipped", [STALE_NOTE]

    # 프롬프트 버전에 자막 분리 기능이 있으면(v2) narration + subtitle 형식으로 받는다
    separate_subtitle = prompt_features(cfg).get("separate_subtitle", False)
    schema = ScriptOutV2 if separate_subtitle else ScriptOut
    parsed, usage = ctx.llm().parse(
        "s3", fill(template, values), schema,
        validate=lambda s: validate_script(s, cfg, source)[0])
    _, warnings = validate_script(parsed, cfg, source)

    scenes = []
    for i, x in enumerate(parsed.scenes, start=1):
        scenes.append({
            "id": i,
            "section": x.section,
            "narration": x.narration,                       # 음성(TTS)용
            "narration_chars": len(x.narration),
            **({"subtitle": x.subtitle} if separate_subtitle else {}),  # 자막용 (v2)
            "visual_idea": x.visual_idea,
            "scene_description": None,   # S4에서 채움
            "uses_character": None,      # S4에서 채움
            "image_prompt": None,        # S4에서 채움
            "image": f"images/scene_{i:02d}.png",
            "audio": f"audio/scene_{i:02d}.mp3",
            "audio_duration_sec": None,
            "start_sec": None,
            "end_sec": None,
        })

    write_json(out, {
        "sample_id": ctx.sample_id,
        "title": source["title"],
        "target_duration_sec": sc["target_duration_sec"],
        "style_preset": proj["style_preset"],
        "prompt_version": proj["prompt_version"],
        "cta_mode": proj["cta_mode"],
        "models": {k: models[k] for k in
                   ("text", "image", "image_size", "image_quality", "tts", "tts_voice")},
        "narration_chars_target": sc["narration_chars_target"],
        "narration_chars_target_is_provisional": sc.get("narration_chars_is_provisional", False),
        "narration_chars_total": sum(s["narration_chars"] for s in scenes),
        "scenes": scenes,
        "warnings": {"s3": warnings},
        "meta": {"s3_data_sha": data_sha, "s3_settings_sha": settings_sha, "s3_usage": usage},
    })
    return "ok", warnings
