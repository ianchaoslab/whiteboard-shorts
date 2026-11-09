"""S8 장면 영상: 장면별 드로잉 영상을 만든다 (FFmpeg·Pillow, API 비용 없음).

config.toml [video] draw_effect로 방식을 고른다.
- "wipe" (이전 방식): 흰 화면 → 그림이 위에서 아래로 드러남 (xfade wipedown)
  결과: clips/scene_XX.mp4
- "whiteboard": 선화가 손으로 그리듯 나타나고 펜이 따라감 (pipeline/draw_whiteboard.py)
  결과: clips_whiteboard/scene_XX.mp4
화면 배치는 config.toml [layout]: 원본 그림을 800x1200으로 줄여 위쪽에 두고, 아래는 자막 공간.
"""
import subprocess
from pathlib import Path

from PIL import Image

from .config import read_json, write_json

OUTPUT_DIR = "clips"
WHITE_LEVEL = 248  # 이 값 이상은 완전한 흰색(255)으로 맞춘다 (그림 배경이 254라 미세한 회색 상자가 보였음)
EFFECTS = ("wipe", "whiteboard")


def clips_dir(cfg: dict) -> str:
    """효과마다 장면 영상 폴더를 따로 쓴다. 기존(wipe) 결과를 덮어쓰지 않기 위해서다."""
    effect = cfg["video"]["draw_effect"]
    if effect not in EFFECTS:
        raise SystemExit(f"❌ 알 수 없는 draw_effect: {effect} (가능: {', '.join(EFFECTS)})")
    return OUTPUT_DIR if effect == "wipe" else f"{OUTPUT_DIR}_{effect}"


def has_output(run_dir: Path) -> bool:
    return False  # 비용이 없는 단계라 실행할 때마다 다시 만든다


def small_image(cfg: dict, image: Path) -> Image.Image:
    """원본 그림을 [layout] 크기(800x1200)로 줄이고, 거의 흰색은 완전한 흰색으로 정리한다."""
    L = cfg["layout"]
    img = Image.open(image).convert("RGB").resize((L["image_width"], L["image_height"]),
                                                  Image.LANCZOS)
    return img.point(lambda x: min(255, round(x * 255 / WHITE_LEVEL)))


def compose_frame(cfg: dict, image: Path, out: Path) -> None:
    """흰 1080x1920 화면 위에 그림을 줄여서 [layout] 위치에 놓은 한 장의 화면 그림을 만든다."""
    v, L = cfg["video"], cfg["layout"]
    img = small_image(cfg, image)
    frame = Image.new("RGB", (v["width"], v["height"]), (255, 255, 255))
    frame.paste(img, (L["image_x"], L["image_y"]))
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.save(out)


def build_clip(cfg: dict, frame: Path, white: Path, duration: float, out: Path) -> float:
    """흰 화면 → 화면 그림으로 위에서 아래로 드러나는 장면 영상."""
    v = cfg["video"]
    reveal = round(min(v["reveal_sec"], duration * v["reveal_max_ratio"]), 3)
    fps = v["fps"]
    # 두 입력 모두 PNG라 색 변환 경로가 같다 → 흰색이 똑같이 나온다
    fc = (f"[0:v]format=yuv420p,setsar=1[w];[1:v]format=yuv420p,setsar=1[f];"
          f"[w][f]xfade=transition={v['reveal_transition']}:duration={reveal}:offset=0[v]")
    subprocess.run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-loop", "1", "-framerate", str(fps), "-t", str(duration), "-i", str(white),
        "-loop", "1", "-framerate", str(fps), "-t", str(duration), "-i", str(frame),
        "-filter_complex", fc, "-map", "[v]", "-t", str(duration), "-r", str(fps),
        "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
        str(out)], check=True)
    return reveal


def run(ctx, force: bool = False, scene_ids: list[int] | None = None, **_) -> tuple[str, list[str]]:
    data = read_json(ctx.run_dir / "scenes.json")
    v = ctx.cfg["video"]
    effect = v["draw_effect"]
    out_dir = ctx.run_dir / clips_dir(ctx.cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    white = out_dir / "white.png"
    if effect == "wipe":
        Image.new("RGB", (v["width"], v["height"]), (255, 255, 255)).save(white)
    warnings = []
    for s in data["scenes"]:
        if scene_ids is not None and s["id"] not in scene_ids:
            continue
        if s.get("start_sec") is None or not s.get("image_raw"):
            raise SystemExit(f"❌ {s['id']}번 장면의 시간표나 이미지가 없습니다. S5, S7을 먼저 실행하세요.")
        duration = round(s["end_sec"] - s["start_sec"], 3)
        out = out_dir / f"scene_{s['id']:02d}.mp4"
        if effect == "whiteboard":
            from .draw_whiteboard import build_whiteboard_clip
            stats = build_whiteboard_clip(
                ctx.cfg, small_image(ctx.cfg, ctx.run_dir / s["image_raw"]), duration, out)
            min_hold = ctx.cfg["whiteboard"]["min_hold_sec"]
            if stats["hold_sec"] < min_hold - 0.01:
                warnings.append(f"{s['id']}번 장면 완성 후 유지 {stats['hold_sec']}초 < {min_hold}초 "
                                "(장면이 너무 짧음)")
        else:
            frame = out_dir / f"frame_{s['id']:02d}.png"
            compose_frame(ctx.cfg, ctx.run_dir / s["image_raw"], frame)
            reveal = build_clip(ctx.cfg, frame, white, duration, out)
            stats = {"draw_end_sec": reveal, "hold_sec": round(duration - reveal, 3)}
        # 장면별 그리기 기록 (효과별로 따로)
        s.setdefault("draw", {})[effect] = {"duration_sec": duration, **stats}
    write_json(ctx.run_dir / "scenes.json", data)
    return "ok", warnings
