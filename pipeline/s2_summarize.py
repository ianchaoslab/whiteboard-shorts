"""S2 요약: 핵심 메시지·핵심 포인트·원문 숫자·홍보 항목을 summary.json으로 저장한다 (API 1회)."""
from pathlib import Path

from .config import STALE_NOTE, cache_action, fill, load_prompt, read_json, sha, write_json
from .schemas import SummaryOut, validate_summary

OUTPUT = "summary.json"
PROMPT_FILE = "s2_summarize.md"


def has_output(run_dir: Path) -> bool:
    return (run_dir / OUTPUT).exists()


def run(ctx, force: bool = False) -> tuple[str, list[str]]:
    src_path = ctx.run_dir / "source.json"
    if not src_path.exists():
        raise SystemExit("❌ source.json이 없습니다. S1을 먼저 실행하세요.")
    source = read_json(src_path)
    template = load_prompt(ctx.cfg, PROMPT_FILE)
    models = ctx.cfg["models"]

    # 데이터(원문)가 같고 결과가 이미 있으면 API를 부르지 않는다 (config.cache_action 참고)
    data_sha = sha({"title": source["title"], "body": source["body"]})
    settings_sha = sha({"prompt": template, "model": models["text"],
                        "effort": models["text_reasoning_effort"]})
    out = ctx.run_dir / OUTPUT
    existing = read_json(out) if out.exists() else None
    action = cache_action(existing and existing.get("meta"), data_sha, settings_sha, force)
    if action == "upgrade":
        existing["meta"].update(data_sha=data_sha, settings_sha=settings_sha)
        write_json(out, existing)
    if action in ("skip", "upgrade"):
        return "skipped", []
    if action == "stale":
        return "skipped", [STALE_NOTE]

    prompt = fill(template, {"title": source["title"], "body": source["body"]})
    parsed, usage = ctx.llm().parse(
        "s2", prompt, SummaryOut,
        validate=lambda s: validate_summary(s, source)[0])
    _, warnings = validate_summary(parsed, source)

    write_json(out, {
        "sample_id": ctx.sample_id,
        **parsed.model_dump(),
        "warnings": warnings,
        "meta": {"data_sha": data_sha, "settings_sha": settings_sha,
                 "prompt_version": ctx.cfg["project"]["prompt_version"],
                 "model": models["text"], "usage": usage},
    })
    return "ok", warnings
