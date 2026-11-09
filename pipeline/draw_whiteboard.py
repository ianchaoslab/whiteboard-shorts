"""화이트보드 드로잉 효과: 선화가 손으로 그리듯 나타나고, 그리는 지점을 펜이 따라간다 (API 비용 없음).

- 그리는 순서와 픽셀별 "나타나는 시간표"는 whiteboard-animator 0.1.1 (MIT)로 계산한다.
  https://github.com/masihsultani/whiteboard-animator  (라이선스: NOTICE.md)
  시간표 계산은 이 라이브러리의 내부 함수를 쓰므로 버전을 0.1.1로 고정한다 (requirements.txt).
- 영상 만들기와 펜 아이콘은 우리 코드다. 펜은 Pillow로 직접 그린 단순한 선화 마커다 (외부 그림 없음).
"""
import math
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


def compute_timing(img: np.ndarray, draw_duration: float) -> tuple[np.ndarray, np.ndarray, float]:
    """픽셀마다 나타나는 시간(초)을 계산한다. 배경은 inf.

    whiteboard-animator의 render_to_file 앞부분(시간표 계산)과 같은 순서로 내부 함수를 부른다.
    돌려주는 값: (시간표, 흰 배경으로 정리된 그림, 그리기 끝나는 시간)
    """
    from whiteboard_animator import WhiteboardAnimator

    anim = WhiteboardAnimator()
    img = anim._enforce_white_bg(img)
    if max(img.shape[:2]) > 1280:
        raise ValueError("그림의 긴 쪽이 1280px을 넘으면 라이브러리가 줄여버립니다. 미리 줄여서 넣으세요.")
    h, w = img.shape[:2]
    timing = np.full((h, w), np.inf, dtype=np.float32)
    components = anim._find_components(img)
    if not components:
        return timing, img, 0.0
    components = anim._sort_components_layered(components)
    schedule = anim._schedule_components(components, draw_duration)
    for comp, start, dur in schedule:
        ct = anim._trace_component(comp, start, dur)
        sl = (slice(comp["top"], comp["bottom"] + 1), slice(comp["left"], comp["right"] + 1))
        mask = comp["mask"][sl]
        timing[sl][mask] = ct[sl][mask]
    draw_end = max(s + d for _, s, d in schedule)
    return timing, img, draw_end


def pen_polygons(tip: tuple[float, float], size: float, angle_deg: float) -> list[list[tuple]]:
    """펜(마커) 모양을 선으로 그리기 위한 다각형들. tip이 펜 끝 위치."""
    a = math.radians(angle_deg)
    ux, uy = math.cos(a), math.sin(a)          # 펜 끝에서 몸통 쪽 방향
    vx, vy = -uy, ux                            # 그에 수직인 방향

    def P(u, v):
        return (tip[0] + ux * u * size + vx * v * size, tip[1] + uy * u * size + vy * v * size)

    nib = [P(0, 0), P(0.16, -0.06), P(0.16, 0.06)]                      # 뾰족한 펜 끝
    collar = [P(0.16, -0.06), P(0.26, -0.11), P(0.26, 0.11), P(0.16, 0.06)]
    body = [P(0.26, -0.11), P(0.92, -0.11), P(0.92, 0.11), P(0.26, 0.11)]
    cap = [P(0.92, -0.12), P(1.0, -0.12), P(1.0, 0.12), P(0.92, 0.12)]
    return [body, cap, collar, nib]


def draw_pen(frame: Image.Image, tip: tuple[float, float], cfg_pen: dict) -> None:
    d = ImageDraw.Draw(frame)
    for poly in pen_polygons(tip, cfg_pen["size"], cfg_pen["angle_deg"]):
        d.polygon(poly, fill=(255, 255, 255), outline=(17, 17, 17), width=cfg_pen["line_width"])
    # 몸통 가운데 줄 하나 (마커 느낌)
    a = math.radians(cfg_pen["angle_deg"])
    s = cfg_pen["size"]
    p1 = (tip[0] + math.cos(a) * 0.40 * s, tip[1] + math.sin(a) * 0.40 * s)
    p2 = (tip[0] + math.cos(a) * 0.80 * s, tip[1] + math.sin(a) * 0.80 * s)
    d.line([p1, p2], fill=(17, 17, 17), width=max(1, cfg_pen["line_width"] - 1))


class PenPath:
    """시간 t에 펜 끝이 있어야 할 위치를 계산한다. 프레임 순서대로 at()을 불러야 한다.

    - 그리는 중: 방금(직전 프레임 이후) 나타난 픽셀 중 직전 펜 위치에서 가장 가까운 곳
      (한 덩어리 안에서 여러 곳이 동시에 그려질 때 펜이 순간이동하지 않게 하나의 획을 따라감)
    - 획과 획 사이(쉬는 시간): 다음에 그릴 픽셀 쪽으로 이동
    - 다 그린 뒤: 화면 오른쪽 아래로 빠져나감
    - 한 프레임에 max_step 이상은 움직이지 않음 (부드럽게)
    """

    def __init__(self, timing: np.ndarray, offset: tuple[int, int], exit_point: tuple[float, float],
                 draw_end: float, fps: int, max_step: float = 70.0):
        ys, xs = np.nonzero(np.isfinite(timing))
        order = np.argsort(timing[ys, xs], kind="stable")
        self.t = timing[ys, xs][order]
        self.x = xs[order].astype(np.float32) + offset[0]
        self.y = ys[order].astype(np.float32) + offset[1]
        self.exit = exit_point
        self.draw_end = draw_end
        self.dt = 1.0 / fps
        self.max_step = max_step
        self.pos = None

    def _target(self, t: float) -> tuple[float, float] | None:
        lo = int(np.searchsorted(self.t, t - self.dt, side="right"))
        hi = int(np.searchsorted(self.t, t, side="right"))
        if t > self.draw_end:
            k = (t - self.draw_end) / 0.5                          # 0.5초 동안 빠져나감
            return None if k >= 1 else self.exit
        if hi > lo:                                                # 이번 프레임에 그려진 픽셀이 있음
            if self.pos is None:
                return (self.x[lo], self.y[lo])
            d = (self.x[lo:hi] - self.pos[0]) ** 2 + (self.y[lo:hi] - self.pos[1]) ** 2
            j = lo + int(np.argmin(d))
            return (self.x[j], self.y[j])
        nxt = min(hi, len(self.t) - 1)                             # 쉬는 시간: 다음 획 시작점으로
        return (self.x[nxt], self.y[nxt])

    def at(self, t: float) -> tuple[float, float] | None:
        if len(self.t) == 0:
            return None
        target = self._target(t)
        if target is None:
            return None
        if self.pos is None:
            self.pos = target
            return self.pos
        dx, dy = target[0] - self.pos[0], target[1] - self.pos[1]
        dist = math.hypot(dx, dy)
        step = self.max_step * (3 if t > self.draw_end else 1)     # 빠져나갈 때는 더 빠르게
        if dist > step:
            dx, dy = dx * step / dist, dy * step / dist
        self.pos = (self.pos[0] + dx, self.pos[1] + dy)
        return self.pos


def remove_specks(img: np.ndarray, max_px: int, ink_level: int = 240) -> tuple[np.ndarray, int]:
    """max_px 픽셀 이하의 아주 작은 잉크 점을 흰색으로 지운다.

    그림에 섞인 1~10픽셀짜리 점에도 라이브러리가 하나씩 그리는 시간(최소 0.05초)을 줘서
    화면 변화 없이 그리기가 늦게 끝나는 문제를 막는다. (ink_level은 라이브러리의 배경 기준 240과 같게)
    돌려주는 값: (정리된 그림, 지운 점 개수)
    """
    from scipy import ndimage

    ink = img.min(axis=2) < ink_level
    labels, n = ndimage.label(ink, structure=np.ones((3, 3)))
    if n == 0:
        return img, 0
    sizes = np.bincount(labels.ravel())
    small = sizes <= max_px
    small[0] = False                       # 0번은 배경
    mask = small[labels]
    out = img.copy()
    out[mask] = 255
    return out, int(small.sum())


def build_whiteboard_clip(cfg: dict, image_rgb: Image.Image, duration: float, out: Path) -> dict:
    """줄인 그림(800x1200)을 받아 1080x1920 장면 영상을 만든다.

    그리기 시간: 장면 길이 x draw_ratio (최대 draw_max_sec). 그래도 완성 후 유지 시간이
    min_hold_sec보다 짧아지면, 시간표 전체를 같은 비율로 당겨서 더 빨리 그린다.
    """
    v, L, wb = cfg["video"], cfg["layout"], cfg["whiteboard"]
    W, H, fps = v["width"], v["height"], v["fps"]
    fade = wb["fade_sec"]
    draw_dur = round(min(duration * wb["draw_ratio"], wb["draw_max_sec"]), 3)

    img_arr, n_specks = remove_specks(np.array(image_rgb), wb["speck_max_px"])
    timing, img, draw_end = compute_timing(img_arr, draw_dur)

    # 완성 후 최소 유지 시간 보장 (라이브러리가 할당보다 늦게 끝내는 경우 포함)
    latest_end = max(duration * 0.4, duration - wb["min_hold_sec"] - fade)
    scaled = draw_end > latest_end > 0
    if scaled:
        timing = timing * (latest_end / draw_end)
        draw_end = latest_end
    hold = round(duration - draw_end - fade, 3)
    ink = img.astype(np.float32)
    ox, oy = L["image_x"], L["image_y"]
    h, w = timing.shape
    pen = PenPath(timing, (ox, oy), (W + 150, H * 0.8), draw_end, fps) if wb["pen"] else None

    out.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
        "-t", str(duration), "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)

    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    finite = np.where(np.isfinite(timing), timing, 1e9).astype(np.float32)
    n_frames = round(duration * fps)
    try:
        for f in range(n_frames):
            t = f / fps
            alpha = np.clip((t - finite) / fade, 0.0, 1.0)[..., None]
            region = (255.0 - alpha * (255.0 - ink)).astype(np.uint8)
            frame = canvas.copy()
            frame.paste(Image.fromarray(region), (ox, oy))
            if pen is not None:
                tip = pen.at(t)
                if tip is not None:
                    draw_pen(frame, tip, wb["pen_style"])
            proc.stdin.write(frame.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("FFmpeg 영상 저장 실패")
    return {"draw_alloc_sec": draw_dur, "draw_end_sec": round(draw_end, 3), "hold_sec": hold,
            "sped_up": bool(scaled), "specks_removed": n_specks, "frames": n_frames}
