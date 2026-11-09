"""S9 합성: 장면 영상 + 음성 + 자막 그림 + AI 음성 고지 → final.mp4 (FFmpeg, API 비용 없음).

- 장면 영상 6개를 순서대로 이어 붙인다.
- 장면별 음성 뒤에 무음을 붙여 장면 길이와 똑같이 맞춘 뒤 이어 붙인다 (음성·장면 싱크).
- 자막 PNG는 subtitles.json의 시간에만 보이게 겹친다.
- 마지막 장면 동안 위 여백에 "AI 생성 음성"을 표시한다 (OpenAI 이용 정책: AI 음성 고지).
결과: final.mp4 (1080x1920, H.264 + AAC). run.py --effect로 다른 효과를 시험하면 final_{효과}.mp4
"""
import subprocess
from pathlib import Path

from .config import read_json

OUTPUT = "final.mp4"


def output_name(cfg: dict) -> str:
    """config.toml의 기본 효과로 만들면 final.mp4.
    run.py --effect로 이번 실행만 다른 효과를 쓰면 final_{효과}.mp4 (기본 결과를 덮어쓰지 않게)."""
    v = cfg["video"]
    return f"final_{v['draw_effect']}.mp4" if v.get("effect_overridden") else OUTPUT


def has_output(run_dir: Path) -> bool:
    return False  # 비용이 없는 단계라 실행할 때마다 다시 만든다


def run(ctx, force: bool = False, **_) -> tuple[str, list[str]]:
    rd, cfg = ctx.run_dir, ctx.cfg
    data = read_json(rd / "scenes.json")
    subs = read_json(rd / "subtitles.json")
    L, fps = cfg["layout"], cfg["video"]["fps"]
    scenes = data["scenes"]

    from .s8_clips import clips_dir
    cdir = rd / clips_dir(cfg)  # config의 draw_effect에 맞는 장면 영상 폴더
    clips = [cdir / f"scene_{s['id']:02d}.mp4" for s in scenes]
    missing = [str(c.relative_to(rd)) for c in clips if not c.exists()]
    if missing:
        raise SystemExit(f"❌ 장면 영상이 없습니다: {missing}. S8을 먼저 실행하세요.")
    concat_list = cdir / "concat.txt"
    concat_list.write_text("".join(f"file '{c.name}'\n" for c in clips), encoding="utf-8")

    # 입력 순서: 0 = 이어 붙인 장면 영상, 1..N = 장면 음성, 그 뒤 = 자막 PNG들, 마지막 = 고지 PNG
    args = ["ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_list)]
    for s in scenes:
        args += ["-i", str(rd / s["audio"])]
    sub_start = 1 + len(scenes)
    for it in subs["items"]:
        args += ["-i", str(rd / it["png"])]
    notice_idx = sub_start + len(subs["items"])
    args += ["-i", str(rd / subs["notice"]["png"])]

    parts = []
    # 음성: 장면 길이에 맞게 무음을 붙이고 자른 뒤 이어 붙이기
    for i, s in enumerate(scenes, start=1):
        dur = round(s["end_sec"] - s["start_sec"], 3)
        parts.append(f"[{i}:a]aresample=48000,apad,atrim=end={dur},asetpts=N/SR/TB[a{i}]")
    parts.append("".join(f"[a{i}]" for i in range(1, len(scenes) + 1))
                 + f"concat=n={len(scenes)}:v=0:a=1[aout]")
    # 영상: 자막 PNG를 차례로 겹치기
    prev = "0:v"
    for k, it in enumerate(subs["items"]):
        label = f"v{k}"
        parts.append(f"[{prev}][{sub_start + k}:v]overlay=0:{L['subtitle_top']}:"
                     f"enable='between(t,{it['start']},{it['end'] - 0.001:.3f})'[{label}]")
        prev = label
    n = subs["notice"]
    parts.append(f"[{prev}][{notice_idx}:v]overlay=0:{L['notice_y']}:"
                 f"enable='between(t,{n['start']},{n['end']})',format=yuv420p[vout]")

    out = rd / output_name(cfg)
    args += ["-filter_complex", ";".join(parts), "-map", "[vout]", "-map", "[aout]",
             "-t", str(subs["total_sec"]), "-r", str(fps),
             "-c:v", "libx264", "-crf", "20", "-preset", "medium", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(out)]
    subprocess.run(args, check=True)
    return "ok", []
