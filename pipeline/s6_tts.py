"""S6 음성: 장면별 한국어 TTS를 만들고 실제 길이를 잰다 (장면당 API 1회).

- 목소리별로 따로 저장: audio/{목소리}/scene_XX.mp3 (+ scene_XX.meta.json)
  그래서 목소리를 바꿔도 이미 만든 파일은 다시 만들지 않는다.
- scenes.json의 audio / audio_duration_sec는 config.toml의 tts_voice 목소리 기준으로 채운다.
  (--voice로 다른 목소리를 만들어도 비교용으로만 저장하고 영상용 지정은 바꾸지 않는다)
- Speech API 응답에는 사용량이 없어 비용은 추정값으로 기록한다 (cost_is_estimate: true).
"""
import time

import openai

from .config import STALE_NOTE, cache_action, read_json, sha, write_json
from .media import audio_duration
from .run_log import now
from .tts_engines import synthesize

OUTPUT_DIR = "audio"


def keys(cfg: dict, text: str) -> tuple[str, str]:
    """(데이터 지문, 설정 지문). 데이터 = 대본 글, 설정 = 엔진·모델·말투 지시·형식.
    목소리는 저장 폴더가 다르므로(audio/{목소리}/) 지문에 넣지 않는다."""
    m = cfg["models"]
    return (sha({"text": text}),
            sha({"provider": m["tts_provider"], "model": m["tts"],
                 "instructions": m["tts_instructions"], "format": m["tts_format"]}))


def action_for(ctx, scene: dict, voice: str, force: bool) -> str:
    audio, meta_path = paths(ctx, voice, scene["id"])
    meta = read_json(meta_path) if audio.exists() and meta_path.exists() else None
    return cache_action(meta, *keys(ctx.cfg, scene["narration"]), force)


def estimate_cost(cfg: dict, chars: int, seconds: float) -> float | None:
    """추정: 글자 1개 = 텍스트 1토큰(넉넉하게), 음성 1초 = s6_audio_tokens_per_sec 토큰(가정)."""
    p = cfg["prices"].get(cfg["models"]["tts"])
    if p is None:
        return None
    audio_tokens = seconds * cfg["estimate"]["s6_audio_tokens_per_sec"]
    return round((chars * p["text_input"] + audio_tokens * p["audio_output"]) / 1_000_000, 6)


def paths(ctx, voice: str, n: int):
    d = ctx.run_dir / OUTPUT_DIR / voice
    ext = ctx.cfg["models"]["tts_format"]
    return d / f"scene_{n:02d}.{ext}", d / f"scene_{n:02d}.meta.json"


def pending(ctx, scene_ids: list[int] | None, force: bool, voice: str) -> list[int]:
    path = ctx.run_dir / "scenes.json"
    if not path.exists():
        return []
    return [s["id"] for s in read_json(path)["scenes"]
            if (scene_ids is None or s["id"] in scene_ids)
            and action_for(ctx, s, voice, force) == "run"]


def has_output(run_dir) -> bool:
    return False  # dry-run에서는 pending()으로 장면별로 확인한다


def run(ctx, force: bool = False, scene_ids: list[int] | None = None,
        voice: str | None = None, **_) -> tuple[str, list[str]]:
    path = ctx.run_dir / "scenes.json"
    if not path.exists():
        raise SystemExit("❌ scenes.json이 없습니다. S1~S4를 먼저 실행하세요.")
    cfg = ctx.cfg
    voice = voice or cfg["models"]["tts_voice"]
    is_main_voice = voice == cfg["models"]["tts_voice"]
    data = read_json(path)
    made, warnings = 0, []

    for s in data["scenes"]:
        n = s["id"]
        if scene_ids is not None and n not in scene_ids:
            continue
        audio, meta_path = paths(ctx, voice, n)
        data_sha, settings_sha = keys(cfg, s["narration"])
        action = action_for(ctx, s, voice, force)
        if action == "upgrade":
            meta = read_json(meta_path)
            meta.update(data_sha=data_sha, settings_sha=settings_sha)
            write_json(meta_path, meta)
        elif action == "stale":
            warnings.append(f"{n}번 장면 ({voice}): {STALE_NOTE}")

        if action == "run":
            started = time.time()
            try:
                info = synthesize(ctx, s["narration"], voice, audio)
            except openai.OpenAIError as e:
                ctx.run_log.add_call({"step": "s6", "scene": n, "voice": voice,
                                      "model": cfg["models"]["tts"], "ok": False,
                                      "error": f"{type(e).__name__}: {str(e)[:300]}",
                                      "duration_sec": round(time.time() - started, 2)})
                raise
            seconds = audio_duration(audio)
            cost = estimate_cost(cfg, len(s["narration"]), seconds)
            ctx.run_log.add_call({"step": "s6", "scene": n, **info,
                                  "input_chars": len(s["narration"]), "audio_sec": seconds,
                                  "cost_usd": cost, "cost_is_estimate": True,
                                  "duration_sec": round(time.time() - started, 2),
                                  "ok": True, "error": None})
            write_json(meta_path, {"scene": n, "data_sha": data_sha, "settings_sha": settings_sha,
                                   **info, "input_chars": len(s["narration"]),
                                   "audio_sec": seconds, "cost_usd": cost,
                                   "cost_is_estimate": True, "created_at": now()})
            made += 1

        seconds = read_json(meta_path)["audio_sec"]
        rel = f"{OUTPUT_DIR}/{voice}/{audio.name}"
        s.setdefault("audio_by_voice", {})[voice] = {"path": rel, "duration_sec": seconds}
        if is_main_voice:
            s["audio"] = rel
            s["audio_duration_sec"] = seconds

    if is_main_voice:
        done = [s["audio_duration_sec"] for s in data["scenes"]
                if s.get("audio_by_voice", {}).get(voice)]
        data["audio_voice"] = voice
        data["models"]["tts_voice"] = voice
        data["audio_total_sec"] = round(sum(done), 3) if len(done) == len(data["scenes"]) else None
    else:
        warnings.append(f"--voice {voice}는 config의 tts_voice({cfg['models']['tts_voice']})와 달라 "
                        "비교용으로만 저장했습니다 (영상용 지정은 그대로)")
    data.setdefault("warnings", {})["s6"] = warnings
    write_json(path, data)
    return ("ok" if made else "skipped"), warnings
