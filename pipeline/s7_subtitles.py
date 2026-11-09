"""S7 자막: 음성 길이로 장면 시간표를 만들고, 자막 SRT와 자막 그림(PNG)을 만든다 (API 비용 없음).

- 장면 길이 = 음성 길이 + 장면 사이 여유 (프레임 단위로 맞춤) → scenes.json의 start_sec / end_sec
- 문장을 1~2줄씩 나누고, 장면 안의 말하는 시간을 조각의 글자 수 비율로 나눈다
- FFmpeg에 자막 기능이 없어서, 자막을 투명 PNG 그림으로 만들어 S9에서 겹친다 (Pillow 사용)

결과: subtitles.srt, subtitles.json (S9용 목록), subs/sub_XX.png, subs/notice.png
"""
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import read_json, write_json

OUTPUT = "subtitles.srt"


def load_font(layout: dict, style: str, size: int) -> ImageFont.FreeTypeFont:
    """글꼴 묶음(.ttc)에서 원하는 굵기를 찾는다."""
    for i in range(64):
        try:
            font = ImageFont.truetype(layout["font_path"], size, index=i)
        except OSError:
            break
        if font.getname() == (layout["font_family"], style):
            return font
    raise SystemExit(f"❌ 글꼴을 찾지 못했습니다: {layout['font_family']} {style}")


def wrap(text: str, font, max_width: int) -> list[str]:
    """띄어쓰기 기준으로 max_width를 넘지 않게 줄을 나눈다."""
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and font.getlength(trial) > max_width:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def balanced(text: str, font, max_width: int) -> list[str] | None:
    """한 줄에 들어가면 한 줄로, 아니면 두 줄 길이가 비슷하게 나눈다. 두 줄에 안 들어가면 None."""
    if font.getlength(text) <= max_width:
        return [text]
    words, best = text.split(), None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        widest = max(font.getlength(a), font.getlength(b))
        if widest <= max_width and (best is None or widest < best[0]):
            best = (widest, [a, b])
    return best[1] if best else None


def chunks_for(narration: str, font, layout: dict) -> list[list[str]]:
    """대본을 화면 자막 조각으로 나눈다. 조각 하나 = 최대 2줄.

    1) 문장 단위로 나눈다.  2) 문장이 두 줄에 들어가면 두 줄 길이를 비슷하게 맞춘다.
    3) 두 줄을 넘으면 쉼표에서 나눠 다시 묶는다.  4) 그래도 길면 줄 단위로 자른다.
    """
    max_w, n = layout["subtitle_max_width"], layout["subtitle_max_lines"]
    result = []
    for sentence in [s for s in re.split(r"(?<=[.?!])\s+", narration.strip()) if s]:
        lines = balanced(sentence, font, max_w) if n >= 2 else None
        if lines:
            result.append(lines)
            continue
        cur = ""
        for clause in re.split(r"(?<=,)\s+", sentence):
            trial = f"{cur} {clause}".strip()
            if balanced(trial, font, max_w):
                cur = trial
                continue
            if cur:
                result.append(balanced(cur, font, max_w))
            if balanced(clause, font, max_w):
                cur = clause
            else:  # 쉼표 없이 아주 긴 경우: 줄 단위로 자름
                lines = wrap(clause, font, max_w)
                result += [lines[i:i + n] for i in range(0, len(lines), n)]
                cur = ""
        if cur:
            result.append(balanced(cur, font, max_w))
    return result


def render_text_png(lines: list[str], font, color: str, width: int, height: int,
                    line_spacing: float, path: Path) -> None:
    img = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    line_h = int(font.size * line_spacing)
    top = (height - line_h * len(lines)) // 2
    for i, line in enumerate(lines):
        draw.text((width / 2, top + i * line_h + line_h / 2), line, font=font, fill=color,
                  anchor="mm")
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def has_output(run_dir: Path) -> bool:
    return (run_dir / OUTPUT).exists()


def run(ctx, force: bool = False, **_) -> tuple[str, list[str]]:
    path = ctx.run_dir / "scenes.json"
    data = read_json(path)
    v, layout = ctx.cfg["video"], ctx.cfg["layout"]
    missing = [s["id"] for s in data["scenes"] if not s.get("audio_duration_sec")]
    if missing:
        raise SystemExit(f"❌ 음성 길이가 없는 장면이 있습니다: {missing}. S6를 먼저 실행하세요.")

    font = load_font(layout, layout["subtitle_font_style"], layout["subtitle_font_size"])
    W, H = v["width"], layout["subtitle_height"]
    fps = v["fps"]
    warnings, items, t = [], [], 0.0

    for s in data["scenes"]:
        frames = round((s["audio_duration_sec"] + v["scene_gap_sec"]) * fps)
        start, end = t, t + frames / fps
        s["start_sec"], s["end_sec"] = round(start, 3), round(end, 3)
        t = end

        # 자막은 자막용 문장(subtitle, 프롬프트 v2)이 있으면 그것을, 없으면 음성용 문장(narration)을 쓴다
        chunks = chunks_for(s.get("subtitle") or s["narration"], font, layout)
        weights = [len("".join(c).replace(" ", "")) for c in chunks]
        speech = s["audio_duration_sec"]
        cur = start
        for k, (lines, w) in enumerate(zip(chunks, weights)):
            last = k == len(chunks) - 1
            c_end = end if last else cur + speech * w / sum(weights)
            n = len(items) + 1
            png = ctx.run_dir / "subs" / f"sub_{n:02d}.png"
            render_text_png(lines, font, layout["subtitle_color"], W, H,
                            layout["subtitle_line_spacing"], png)
            items.append({"index": n, "scene": s["id"], "start": round(cur, 3),
                          "end": round(c_end, 3), "lines": lines,
                          "png": str(png.relative_to(ctx.run_dir))})
            cur = c_end
        if any(len(c) > layout["subtitle_max_lines"] for c in chunks):
            warnings.append(f"{s['id']}번 장면 자막이 {layout['subtitle_max_lines']}줄을 넘음")

    # AI 음성 고지 그림 (OpenAI 이용 정책): 마지막 장면 동안 위 여백에 표시
    notice_font = load_font(layout, layout["notice_font_style"], layout["notice_font_size"])
    notice_png = ctx.run_dir / "subs" / "notice.png"
    render_text_png([layout["notice_text"]], notice_font, layout["notice_color"], W,
                    int(layout["notice_font_size"] * 2), 1.0, notice_png)
    last = data["scenes"][-1]

    srt = "\n".join(f"{it['index']}\n{srt_time(it['start'])} --> {srt_time(it['end'])}\n"
                    + "\n".join(it["lines"]) + "\n" for it in items)
    (ctx.run_dir / OUTPUT).write_text(srt, encoding="utf-8")
    write_json(ctx.run_dir / "subtitles.json", {
        "total_sec": round(t, 3),
        "items": items,
        "notice": {"png": str(notice_png.relative_to(ctx.run_dir)),
                   "start": last["start_sec"], "end": last["end_sec"],
                   "text": layout["notice_text"]},
    })
    data["video_total_sec"] = round(t, 3)
    write_json(path, data)
    sc = ctx.cfg["script"]
    if not sc["min_duration_sec"] <= t <= sc["max_duration_sec"]:
        warnings.append(f"영상 길이 {t:.1f}초가 {sc['min_duration_sec']}~{sc['max_duration_sec']}초 범위 밖 "
                        "(대본 길이 자동 조정은 아직 구현 안 됨)")
    return "ok", warnings
