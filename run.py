"""WB_app 실행 시작점 (S1 추출 ~ S9 최종 합성).

사용법 (터미널에서 WB_app 폴더, 가상환경을 켠 상태):
  python run.py check                               API 연결 확인 (짧은 호출 1번)
  python run.py --sample 01                         S1~S9 한 번에 실행 (이미지는 만들기 전에 물어봄)
  python run.py --sample 01 --step s8 --scenes 1    장면 1번 영상만 만들기 (S7~S9는 API 비용 없음)
  python run.py --sample 01 --step s8 --effect whiteboard  손으로 그리기+펜 효과로 (이번 실행만)
  python run.py --sample 01 --step s3               S3만 실행
  python run.py --sample 01 --step s3 --force       S3 결과를 지우고 다시 만들기
  python run.py --sample 01 --step s5 --scenes 1    장면 1번 이미지만 만들기
  python run.py --sample 01 --step s6 --voice cedar cedar 목소리로 음성 만들기 (비교용)
  python run.py --sample 01 --new                   새 결과 폴더에서 처음부터
  python run.py --sample 01 --dry-run               API 호출 없이 계획만 보기
  python run.py --url https://blog.naver.com/아이디/글번호  허락받은 블로그(config [sources]) 글로 실행
  python run.py --samples 10,16,13 --yes            여러 샘플을 차례로 S1~S9 (실패해도 다음 샘플로)
  python run.py --samples 10,16,13 --dry-run        여러 샘플의 예상 비용만 보기
  python run.py --samples 01,10 --prompt-version v2 --style-preset whiteboard_v2 --yes  v2 프롬프트로 (새 폴더)
  --yes                                             이미지 비용 확인 질문 없이 진행 (사람 개입 없는 실행용)
"""
import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path


from pipeline import (s1_extract, s2_summarize, s3_script, s4_image_prompts, s5_images,
                      s6_tts, s7_subtitles, s8_clips, s9_compose)
from pipeline.config import load_config, project_path, read_json, snapshot, write_json
from pipeline.context import Context
from pipeline.llm import LLM
from pipeline.run_log import RunLog, now
from pipeline.schemas import CheckOut

STEPS = {
    "s1": ("S1 추출", s1_extract),
    "s2": ("S2 요약", s2_summarize),
    "s3": ("S3 대본", s3_script),
    "s4": ("S4 이미지 프롬프트", s4_image_prompts),
    "s5": ("S5 이미지 생성", s5_images),
    "s6": ("S6 음성", s6_tts),
    "s7": ("S7 자막", s7_subtitles),
    "s8": ("S8 장면 영상", s8_clips),
    "s9": ("S9 최종 합성", s9_compose),
}
API_STEPS = {"s2", "s3", "s4", "s5", "s6"}   # OpenAI 비용이 드는 단계 (S7~S9는 FFmpeg·Pillow만 사용)
PAID_MEDIA_STEPS = {"s5", "s6"}              # 장면별로 비용을 계산하는 단계
MEDIA_STEPS = {"s5", "s6", "s8"}             # --scenes, --voice 옵션을 쓰는 단계


def pick_run_dir(cfg: dict, sample_id: str, new: bool) -> tuple[Path, bool]:
    """같은 샘플·같은 설정(프롬프트 버전 등)의 가장 최근 결과 폴더를 이어서 쓴다.
    v1 폴더와 v2 폴더가 함께 있어도 설정이 맞는 폴더를 찾는다. 없으면 새로 만든다."""
    outputs = project_path(cfg, "outputs_dir")
    logs = sorted(outputs.glob(f"{sample_id}_*/run_log.json"))
    if logs and not new:
        for log_path in reversed(logs):
            if read_json(log_path).get("config_snapshot") == snapshot(cfg):
                return log_path.parent, False
        old = read_json(logs[-1]).get("config_snapshot") or {}
        changed = [k for k in snapshot(cfg) if old.get(k) != snapshot(cfg)[k]]
        print(f"ℹ️ 이 설정의 결과 폴더가 없어 새로 만듭니다 (최근 폴더와 다른 항목: {', '.join(changed)})")
    name = f"{sample_id}_{datetime.now():%Y%m%d-%H%M}"
    path, n = outputs / name, 2
    while path.exists():
        path, n = outputs / f"{name}-{n}", n + 1
    return path, True


def estimate(cfg: dict, step: str) -> float:
    e, p = cfg["estimate"][step], cfg["prices"][cfg["models"]["text"]]
    return (e["input"] * p["input"] + e["output"] * p["output"]) / 1_000_000


def media_plan(ctx_like, step: str, opts: dict, force: bool) -> tuple[list[int], float]:
    """S5/S6에서 새로 만들 장면 번호와 예상 비용."""
    cfg = ctx_like.cfg
    if step == "s5":
        ids = s5_images.pending(ctx_like, opts["scene_ids"], force)
        return ids, len(ids) * cfg["estimate"]["s5_image_usd"]
    voice = opts["voice"] or cfg["models"]["tts_voice"]
    ids = s6_tts.pending(ctx_like, opts["scene_ids"], force, voice)
    data = read_json(ctx_like.run_dir / "scenes.json") if (ctx_like.run_dir / "scenes.json").exists() else {"scenes": []}
    chars = sum(len(s["narration"]) for s in data["scenes"] if s["id"] in ids)
    seconds = chars / 7  # 대략: 초당 7자 가정 (dry-run 표시용)
    return ids, s6_tts.estimate_cost(cfg, chars, seconds) or 0.0


def confirm_images(n: int, cost: float, assume_yes: bool) -> bool:
    if n == 0 or assume_yes:
        return True
    if not sys.stdin.isatty():
        print(f"❌ 이미지 {n}장을 새로 만들어야 합니다 (예상 약 ${cost:.3f}). "
              "확인 질문에 답할 수 없는 환경이라 멈춥니다. 진행하려면 --yes를 붙이세요.")
        return False
    answer = input(f"이미지 {n}장을 새로 만듭니다. 예상 약 ${cost:.3f}. 계속할까요? (y/N) ")
    return answer.strip().lower() in ("y", "yes")


def cmd_check(cfg: dict) -> None:
    print(f"API 연결 확인: 모델 {cfg['models']['text']}, 짧은 JSON 응답 1번")
    llm = LLM(cfg, None)
    started = time.time()
    parsed, usage = llm.parse(
        "check",
        "API 연결 확인용 요청입니다. ok는 true, message는 '연결 성공'으로 답하세요.",
        CheckOut, effort="low")
    result = {"at": now(), "model": cfg["models"]["text"], "reasoning_effort": "low",
              "response": parsed.model_dump(), "usage": usage,
              "duration_sec": round(time.time() - started, 2)}
    write_json(project_path(cfg, "outputs_dir") / "api_check.json", result)
    print(f"✅ 응답: {parsed.model_dump()}")
    print(f"   토큰: 입력 {usage['input_tokens']}, 출력 {usage['output_tokens']} "
          f"(생각 {usage['reasoning_tokens']}), 비용 ${usage['cost_usd']:.6f}")


def dry_run_plan(cfg: dict, sample_id: str, run_dir: Path, steps: list[str], opts: dict,
                 force: bool) -> float:
    """API 호출 없이 단계별 계획과 예상 비용을 보여준다."""
    total = 0.0
    probe = Context(cfg=cfg, sample_id=sample_id, run_dir=run_dir, run_log=None)
    has_scenes = (run_dir / "scenes.json").exists()
    for s in steps:
        label, mod = STEPS[s]
        if s not in API_STEPS and s != "s1":
            print(f"  {label}: FFmpeg·Pillow로 이 Mac에서 처리 (API 비용 없음)")
            continue
        if s in PAID_MEDIA_STEPS and not has_scenes:
            # 아직 대본이 없으면 기본 장면 수와 목표 글자 수로 추정
            n, sc = cfg["script"]["scene_count"], cfg["script"]
            if s == "s5":
                cost = n * cfg["estimate"]["s5_image_usd"]
            else:
                chars = sc["narration_chars_target"]
                cost = s6_tts.estimate_cost(cfg, chars, sc["target_duration_sec"]) or 0.0
            total += cost
            print(f"  {label}: 대본 생성 후 약 {n}장면 예정 (추정), 예상 약 ${cost:.3f}")
            continue
        if s in PAID_MEDIA_STEPS:
            ids, cost = media_plan(probe, s, opts, force)
            total += cost
            what = "장" if s == "s5" else "개"
            print(f"  {label}: 새로 만들 장면 {ids or '없음'} ({len(ids)}{what}), 예상 약 ${cost:.3f}")
            continue
        if mod.has_output(run_dir) and not force:
            print(f"  {label}: 결과 있음 → 건너뛸 예정 (입력이 바뀌었으면 다시 만듦)")
        elif s in API_STEPS:
            cost = estimate(cfg, s)
            total += cost
            print(f"  {label}: API 호출 1회 예정 (형식 오류 시 최대 "
                  f"{cfg['api']['max_validation_retries']}회 재시도), 예상 약 ${cost:.3f}")
        else:
            print(f"  {label}: 파일 읽기 (비용 없음)")
    print(f"예상 비용 합계: 약 ${total:.3f} (dry-run이라 실제 호출은 하지 않았습니다)")
    return total


def cmd_run(cfg: dict, sample_id: str, step: str | None, force: bool, new: bool, dry_run: bool,
            opts: dict, assume_yes: bool) -> dict:
    """샘플 하나를 실행한다. 어떤 오류가 나도 프로그램을 멈추지 않고 결과(dict)를 돌려준다."""
    steps = [step] if step else list(STEPS)
    run_dir, is_new = pick_run_dir(cfg, sample_id, new)
    rel_dir = run_dir.relative_to(project_path(cfg, "outputs_dir").parent)
    print(f"샘플 {sample_id} | 결과 폴더: {rel_dir}{' (새로 만듦)' if is_new else ' (이어서 사용)'}")
    result = {"sample_id": sample_id, "run_dir": str(rel_dir), "ok": False,
              "failed_step": None, "error": None}

    if dry_run:
        result.update(ok=True, estimated_cost_usd=dry_run_plan(cfg, sample_id, run_dir, steps,
                                                               opts, force))
        return result

    run_dir.mkdir(parents=True, exist_ok=True)
    log = RunLog(run_dir, sample_id, snapshot(cfg))
    calls_before = len(log.data["calls"])
    ctx = Context(cfg=cfg, sample_id=sample_id, run_dir=run_dir, run_log=log,
                  input_file=opts.get("input_file"))
    run_started, started_at = time.time(), now()

    changed = False
    for s in steps:
        label, mod = STEPS[s]
        started = time.time()
        if s == "s5":
            try:
                ids, cost = media_plan(ctx, s, opts, force)
            except Exception:
                ids, cost = [], 0.0
            if not confirm_images(len(ids), cost, assume_yes):
                log.step_done(s, "failed", started, error="이미지 비용 확인에서 취소됨 (API 호출 안 함)")
                result.update(failed_step=s, error="이미지 비용 확인에서 취소됨")
                print("  S5 이미지 생성: 취소함 (API 호출 안 함)")
                break
        try:
            extra = opts if s in MEDIA_STEPS else {}
            status, warnings = mod.run(ctx, force=force, **extra)
        except BaseException as e:  # SystemExit 포함, 모든 오류를 기록하고 이 샘플만 멈춘다
            if isinstance(e, KeyboardInterrupt):
                raise
            msg = f"{type(e).__name__}: {str(e)[:500]}"
            log.step_done(s, "failed", started, error=msg)
            result.update(failed_step=s, error=msg)
            print(f"❌ {label} 실패: {msg}")
            print(f"   자세한 기록: {log.path}")
            break
        log.step_done(s, status, started, warnings=warnings)
        changed |= status == "ok"
        mark = "⏭️ 건너뜀 (결과 있음, API 호출 안 함)" if status == "skipped" else "✅ 완료"
        print(f"  {label}: {mark}")
        for w in warnings:
            print(f"     ⚠️ {w}")
    else:
        result["ok"] = True

    if result["ok"] and step and changed and step in ("s1", "s2", "s3", "s4"):
        later = list(STEPS)[list(STEPS).index(step) + 1:]
        if sample_id.isdigit():
            again = f"python run.py --sample {sample_id}"
        elif opts.get("input_file") and "-" in sample_id and not sample_id.startswith("custom-"):
            blog_id, log_no = sample_id.rsplit("-", 1)
            again = f"python run.py --url https://blog.naver.com/{blog_id}/{log_no}"
        else:
            again = f"python run.py --text-file {opts.get('input_file')}"
        print(f"ℹ️ {step} 결과가 바뀌었습니다. 뒤 단계({', '.join(later)})는 `{again}`로 다시 실행하세요.")

    new_calls = log.data["calls"][calls_before:]
    cost = round(sum(c.get("cost_usd") or 0 for c in new_calls), 6)
    duration = round(time.time() - run_started, 1)
    # 샘플 단위 실행 기록 (성공 여부, 실패 단계·원인, 소요 시간, 이번 실행 비용)
    log.data.setdefault("runs", []).append({
        "started_at": started_at, "finished_at": now(), "steps": steps,
        "ok": result["ok"], "failed_step": result["failed_step"], "error": result["error"],
        "duration_sec": duration, "api_calls": len(new_calls), "cost_usd": cost})
    log.save()
    result.update(duration_sec=duration, api_calls=len(new_calls), cost_usd=cost)
    print(f"이번 실행: API 호출 {len(new_calls)}회, 비용 ${cost:.6f}, {duration}초 | "
          f"폴더 누적: {log.data['totals']['api_calls']}회, ${log.data['totals']['cost_usd']:.6f}")
    return result


def summarize(cfg: dict, result: dict) -> dict:
    """결과 보고용: 제목, 영상 길이, 장면 수, 대본 글자 수."""
    rd = project_path(cfg, "outputs_dir").parent / result["run_dir"]
    info = {"title": None, "video_sec": None, "scenes": None, "chars": None}
    if (rd / "scenes.json").exists():
        d = read_json(rd / "scenes.json")
        info.update(title=d.get("title"), scenes=len(d["scenes"]),
                    chars=d.get("narration_chars_total"), video_sec=d.get("video_total_sec"))
    elif (rd / "source.json").exists():
        info["title"] = read_json(rd / "source.json").get("title")
    final = rd / s9_compose.output_name(cfg)
    info["final"] = str(final) if final.exists() else None
    return {**result, **info}


def cmd_batch(cfg: dict, sample_ids: list[str], args, opts: dict) -> int:
    """여러 샘플을 차례로 실행한다. 한 샘플이 실패해도 다음 샘플로 넘어간다."""
    results = []
    for sid in sample_ids:
        print(f"\n===== 샘플 {sid} =====")
        try:
            r = cmd_run(cfg, sid, args.step, args.force, args.new, args.dry_run, opts, args.yes)
        except Exception as e:  # 폴더 준비 등 단계 밖 오류
            r = {"sample_id": sid, "run_dir": "", "ok": False, "failed_step": "준비",
                 "error": f"{type(e).__name__}: {e}"}
            print(f"❌ 샘플 {sid} 준비 실패: {r['error']}")
        results.append(summarize(cfg, r) if r.get("run_dir") else r)

    print("\n===== 요약 =====")
    if args.dry_run:
        total = sum(r.get("estimated_cost_usd", 0) for r in results)
        print(f"{len(results)}건 예상 비용 합계: 약 ${total:.3f}")
        return 0
    for r in results:
        state = "✅ 성공" if r["ok"] else f"❌ 실패 ({r['failed_step']}: {r['error']})"
        print(f"{r['sample_id']} | {state} | 영상 {r.get('video_sec')}초 | 장면 {r.get('scenes')} | "
              f"{r.get('chars')}자 | {r.get('duration_sec')}초 | ${r.get('cost_usd', 0):.6f}")
    batch_path = project_path(cfg, "outputs_dir") / f"batch_{datetime.now():%Y%m%d-%H%M%S}.json"
    write_json(batch_path, {"at": now(), "samples": sample_ids, "results": results})
    print(f"요약 기록: {batch_path.relative_to(project_path(cfg, 'outputs_dir').parent)}")
    return 0 if all(r["ok"] for r in results) else 1


def main() -> int:
    p = argparse.ArgumentParser(description="WB_app 파이프라인 S1~S9")
    p.add_argument("command", nargs="?", choices=["check"], help="check: API 연결 확인")
    p.add_argument("--sample", help="샘플 번호 (예: 01)")
    p.add_argument("--samples", help="여러 샘플을 차례로 실행 (예: 10,16,13). 실패해도 다음 샘플로 넘어감")
    p.add_argument("--url", help="허락받은 블로그(config.toml [sources])의 글 주소")
    p.add_argument("--text-file", help="붙여넣은 원문 파일 (제목: / 주소: / 본문: 형식, 데모 페이지가 inputs/에 만듦)")
    p.add_argument("--step", choices=list(STEPS), help="이 단계만 실행")
    p.add_argument("--force", action="store_true", help="결과가 있어도 다시 만들기 (API 다시 호출)")
    p.add_argument("--new", action="store_true", help="새 결과 폴더에서 실행")
    p.add_argument("--dry-run", action="store_true", help="API 호출 없이 계획만 보기")
    p.add_argument("--scenes", help="S5/S6에서 이 장면만 (예: 1 또는 1,3,5)")
    p.add_argument("--voice", help="S6 목소리 (기본: config.toml의 tts_voice)")
    p.add_argument("--yes", action="store_true", help="이미지 비용 확인 질문 없이 진행")
    p.add_argument("--effect", choices=["wipe", "whiteboard"],
                   help="S8·S9 드로잉 효과를 이번 실행에서만 바꾸기 (config.toml은 그대로)")
    p.add_argument("--prompt-version", help="이번 실행에서만 쓸 프롬프트 버전 (예: v2). 결과는 새 폴더에")
    p.add_argument("--style-preset", help="이번 실행에서만 쓸 스타일 프리셋 (예: whiteboard_v2)")
    args = p.parse_args()
    cfg = load_config()
    if args.prompt_version:
        if not (project_path(cfg, "prompts_dir") / args.prompt_version).is_dir():
            p.error(f"프롬프트 폴더가 없습니다: prompts/{args.prompt_version}")
        cfg["project"]["prompt_version"] = args.prompt_version
    if args.style_preset:
        if not (project_path(cfg, "presets_dir") / f"{args.style_preset}.toml").exists():
            p.error(f"스타일 프리셋이 없습니다: presets/{args.style_preset}.toml")
        cfg["project"]["style_preset"] = args.style_preset
    if args.effect and args.effect != cfg["video"]["draw_effect"]:
        cfg["video"]["draw_effect"] = args.effect
        cfg["video"]["effect_overridden"] = True  # S9 결과를 final_{효과}.mp4로 따로 저장
    opts = {"scene_ids": [int(x) for x in args.scenes.split(",")] if args.scenes else None,
            "voice": args.voice}

    if args.command == "check":
        cmd_check(cfg)
        return 0
    if args.samples:
        ids = [f"{int(x):02d}" for x in args.samples.split(",") if x.strip()]
        return cmd_batch(cfg, ids, args, opts)
    if args.text_file:
        # 붙여넣은 원문 파일 (제목: / 주소: / 본문: 형식). 결과는 outputs/custom-..._날짜시각/
        path = Path(args.text_file).resolve()
        if not path.is_file():
            p.error(f"원문 파일이 없습니다: {args.text_file}")
        stem = re.sub(r"[^\w-]", "-", path.stem)
        sample_id = stem if stem.startswith("custom-") else f"custom-{stem}"
        opts["input_file"] = path
    elif args.url:
        # 허락받은 블로그(config [sources])의 글만 1번 가져온다. 이미 가져온 글은 다시 접속하지 않는다
        try:
            post = s1_extract.get_post(cfg, args.url)
        except s1_extract.NotAllowedBlog as e:
            print(f"❌ 허락받지 않은 블로그({e})라 자동 수집하지 않습니다. 본문을 붙여넣어 주세요 (--text-file).")
            return 1
        except s1_extract.FetchFailed as e:
            print(f"❌ 글을 가져오지 못했습니다: {e}")
            return 1
        print(f"ℹ️ {post['note']} 제목: {post['title']}")
        sample_id = post["sample_id"]
        opts["input_file"] = post["path"]
    elif args.sample:
        sample_id = f"{int(args.sample):02d}"
    else:
        p.error("--sample, --samples, --url 또는 --text-file 이 필요합니다 (예: python run.py --sample 01)")
    result = cmd_run(cfg, sample_id, args.step, args.force, args.new, args.dry_run, opts, args.yes)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
