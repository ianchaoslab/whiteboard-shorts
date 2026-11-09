"""설정 파일(config.toml), 프롬프트 파일, 스타일 프리셋을 읽는 곳."""
import hashlib
import json
import re
import tomllib
from pathlib import Path

# 프로젝트 맨 위 폴더 (/Users/.../WB_app)
ROOT = Path(__file__).resolve().parent.parent


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config.toml", "rb") as f:
        return tomllib.load(f)


def project_path(cfg: dict, key: str) -> Path:
    """config.toml [paths]에 적힌 폴더를 실제 경로로 바꾼다."""
    return ROOT / cfg["paths"][key]


def load_prompt(cfg: dict, filename: str) -> str:
    """prompts/{버전}/{파일} 내용을 읽는다."""
    path = project_path(cfg, "prompts_dir") / cfg["project"]["prompt_version"] / filename
    return path.read_text(encoding="utf-8")


def load_prompt_toml(cfg: dict, filename: str) -> dict:
    path = project_path(cfg, "prompts_dir") / cfg["project"]["prompt_version"] / filename
    with open(path, "rb") as f:
        return tomllib.load(f)


def prompt_features(cfg: dict) -> dict:
    """prompts/{버전}/features.toml (없으면 빈 dict → 모든 기능 끔, 예: v1)."""
    path = project_path(cfg, "prompts_dir") / cfg["project"]["prompt_version"] / "features.toml"
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_preset(cfg: dict) -> dict:
    path = project_path(cfg, "presets_dir") / f"{cfg['project']['style_preset']}.toml"
    with open(path, "rb") as f:
        return tomllib.load(f)


def fill(template: str, values: dict) -> str:
    """프롬프트 속 {{이름}} 자리를 실제 값으로 바꾼다. 빠진 값이 있으면 오류."""
    def repl(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            raise KeyError(f"프롬프트에 필요한 값 '{key}'가 없습니다")
        return str(values[key])

    return re.sub(r"\{\{(\w+)\}\}", repl, template)


def sha(obj) -> str:
    """내용이 같으면 같은 값이 나오는 짧은 지문. 입력이 바뀌었는지 확인할 때 쓴다."""
    data = json.dumps(obj, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(data).hexdigest()[:16]


STALE_NOTE = ("설정(프롬프트·모델·목표값 등)이 바뀌었지만 기존 결과를 그대로 씁니다. "
              "다시 만들려면 --force를 붙이세요")


def cache_action(meta: dict | None, data_sha: str, settings_sha: str, force: bool,
                 prefix: str = "") -> str:
    """이미 있는 결과를 쓸지, 새로 만들지 정한다.

    - "run":     결과 없음, --force, 또는 앞 단계 결과(데이터)가 바뀜 → 새로 만든다 (API 호출)
    - "skip":    그대로 → API를 부르지 않는다
    - "stale":   설정만 바뀜 → API를 부르지 않고 기존 결과를 쓰며 경고만 남긴다
                 (재생성은 --force로 명시적으로 요청할 때만)
    - "upgrade": 이전 형식의 기록 → 지금 값으로 기록만 고치고 기존 결과를 쓴다
    """
    if force or meta is None:
        return "run"
    data_key, settings_key = f"{prefix}data_sha", f"{prefix}settings_sha"
    if data_key not in meta:
        return "upgrade"
    if meta[data_key] != data_sha:
        return "run"
    if meta.get(settings_key) != settings_sha:
        return "stale"
    return "skip"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot(cfg: dict) -> dict:
    """결과 폴더에 남길 설정 요약. 이 값이 바뀌면 새 결과 폴더를 만든다."""
    return {
        "prompt_version": cfg["project"]["prompt_version"],
        "style_preset": cfg["project"]["style_preset"],
        "cta_mode": cfg["project"]["cta_mode"],
        "text_model": cfg["models"]["text"],
        "text_reasoning_effort": cfg["models"]["text_reasoning_effort"],
    }
