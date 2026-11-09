"""S5 이미지 생성: 장면별 화이트보드 일러스트를 만든다 (장면당 API 1회).

- 원본: images/scene_XX_raw.png (모델이 준 크기 그대로, 예: 1024×1536)
- 영상용: images/scene_XX.png (1080×1920에 맞춤)
- 기록: images/scene_XX.meta.json (프롬프트 지문, 사용 토큰, 비용)
같은 프롬프트·설정으로 이미 만든 이미지가 있으면 API를 다시 부르지 않는다.

공식 문서: https://developers.openai.com/api/reference/resources/images/methods/generate
"""
import base64
import time

import openai

from .config import STALE_NOTE, cache_action, read_json, sha, write_json
from .media import fit_image, image_size
from .run_log import now

OUTPUT_DIR = "images"


def image_cost(cfg: dict, model: str, usage: dict) -> float | None:
    p = cfg["prices"].get(model)
    if p is None:
        return None
    total = (usage["text_input_tokens"] * p["text_input"]
             + usage["image_input_tokens"] * p["image_input"]
             + usage["output_tokens"] * p["image_output"]) / 1_000_000
    return round(total, 6)


def read_image_usage(resp) -> dict:
    u = resp.usage
    if u is None:
        return {}
    ind = u.input_tokens_details
    outd = u.output_tokens_details
    return {
        "input_tokens": u.input_tokens,
        "text_input_tokens": (ind.text_tokens or 0) if ind else u.input_tokens,
        "image_input_tokens": (ind.image_tokens or 0) if ind else 0,
        "output_tokens": u.output_tokens,
        "output_image_tokens": (outd.image_tokens or 0) if outd else None,
        "output_text_tokens": (outd.text_tokens or 0) if outd else None,
    }


def settings(cfg: dict) -> dict:
    m = cfg["models"]
    return {"model": m["image"], "size": m["image_size"], "quality": m["image_quality"],
            "background": m["image_background"]}


def select(data: dict, scene_ids: list[int] | None) -> list[dict]:
    scenes = data["scenes"]
    return [s for s in scenes if scene_ids is None or s["id"] in scene_ids]


def keys(cfg: dict, scene: dict) -> tuple[str, str]:
    """(데이터 지문, 설정 지문). 데이터 = 이미지 프롬프트, 설정 = 모델·크기·품질·배경."""
    return sha({"prompt": scene["image_prompt"]}), sha(settings(cfg))


def action_for(ctx, scene: dict, force: bool) -> str:
    n = scene["id"]
    raw = ctx.run_dir / OUTPUT_DIR / f"scene_{n:02d}_raw.png"
    meta_path = ctx.run_dir / OUTPUT_DIR / f"scene_{n:02d}.meta.json"
    meta = read_json(meta_path) if raw.exists() and meta_path.exists() else None
    return cache_action(meta, *keys(ctx.cfg, scene), force)


def pending(ctx, scene_ids: list[int] | None, force: bool) -> list[int]:
    """API로 새로 만들어야 하는 장면 번호 (비용 확인용)."""
    path = ctx.run_dir / "scenes.json"
    if not path.exists():
        return []
    return [s["id"] for s in select(read_json(path), scene_ids)
            if action_for(ctx, s, force) == "run"]


def has_output(run_dir) -> bool:
    return False  # dry-run에서는 pending()으로 장면별로 확인한다


def run(ctx, force: bool = False, scene_ids: list[int] | None = None, **_) -> tuple[str, list[str]]:
    path = ctx.run_dir / "scenes.json"
    if not path.exists():
        raise SystemExit("❌ scenes.json이 없습니다. S1~S4를 먼저 실행하세요.")
    data = read_json(path)
    targets = select(data, scene_ids)
    if any(not s.get("image_prompt") for s in targets):
        raise SystemExit("❌ image_prompt가 없는 장면이 있습니다. S4를 먼저 실행하세요.")

    cfg, st = ctx.cfg, settings(ctx.cfg)
    v = cfg["video"]
    warnings, made = [], 0
    out_dir = ctx.run_dir / OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    for s in targets:
        n = s["id"]
        raw = out_dir / f"scene_{n:02d}_raw.png"
        fitted = out_dir / f"scene_{n:02d}.png"
        meta_path = out_dir / f"scene_{n:02d}.meta.json"
        data_sha, settings_sha = keys(cfg, s)
        action = action_for(ctx, s, force)
        if action == "upgrade":
            meta = read_json(meta_path)
            meta.update(data_sha=data_sha, settings_sha=settings_sha)
            write_json(meta_path, meta)
        elif action == "stale":
            warnings.append(f"{n}번 장면: {STALE_NOTE}")

        if action == "run":
            started = time.time()
            try:
                resp = ctx.llm().client.images.generate(
                    prompt=s["image_prompt"], output_format="png", n=1, **st)
            except openai.OpenAIError as e:
                ctx.run_log.add_call({"step": "s5", "scene": n, "model": st["model"], "ok": False,
                                      "error": f"{type(e).__name__}: {str(e)[:300]}",
                                      "duration_sec": round(time.time() - started, 2)})
                raise
            raw.write_bytes(base64.b64decode(resp.data[0].b64_json))
            usage = read_image_usage(resp)
            cost = image_cost(cfg, st["model"], usage) if usage else None
            if not usage:
                warnings.append(f"{n}번 장면: 응답에 사용량(usage)이 없어 비용을 계산하지 못함")
            ctx.run_log.add_call({"step": "s5", "scene": n, **st, **usage, "cost_usd": cost,
                                  "duration_sec": round(time.time() - started, 2), "ok": True,
                                  "error": None})
            write_json(meta_path, {"scene": n, "data_sha": data_sha, "settings_sha": settings_sha,
                                   **st,
                                   "usage": usage, "cost_usd": cost, "created_at": now(),
                                   "raw_size": "x".join(map(str, image_size(raw)))})
            made += 1

        # 영상용 1080×1920 맞춤본 (API 비용 없음)
        if action == "run" or not fitted.exists():
            fit_image(raw, fitted, v["width"], v["height"], v["pad_color"])
        if image_size(fitted) != (v["width"], v["height"]):
            warnings.append(f"{n}번 장면 영상용 이미지 크기가 {v['width']}x{v['height']}가 아님")
        s["image"] = f"{OUTPUT_DIR}/{fitted.name}"
        s["image_raw"] = f"{OUTPUT_DIR}/{raw.name}"

    data.setdefault("warnings", {})["s5"] = warnings
    write_json(path, data)
    return ("ok" if made else "skipped"), warnings
