"""FFmpeg/ffprobe를 쓰는 도우미 (API 비용 없음)."""
import subprocess
from pathlib import Path


def fit_image(src: Path, dst: Path, width: int, height: int, color: str) -> None:
    """비율을 유지한 채 width×height 안에 맞게 키우고, 남는 부분은 color 여백으로 채운다.

    예: 1024×1536 → 1080×1620으로 키운 뒤 위아래에 150px씩 흰 여백 → 1080×1920
    """
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color={color}")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf", vf, str(dst)],
                   check=True)


def image_size(path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path)],
        check=True, capture_output=True, text=True).stdout.strip()
    w, h = out.split("x")
    return int(w), int(h)


def audio_duration(path: Path) -> float:
    """음성 파일의 실제 길이(초)."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        check=True, capture_output=True, text=True).stdout.strip()
    return round(float(out), 3)
