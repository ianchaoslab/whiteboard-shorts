"""데모 페이지의 뒤쪽 일: 블로그 글 확인, 영상 생성 실행, 진행 상황 읽기.

영상 생성은 run.py를 별도 프로그램으로 실행한다. 그래서 웹 페이지를 새로고침하거나 닫아도 생성이 멈추지 않고,
기존 파이프라인 코드를 그대로 쓴다. 진행 상황은 결과 폴더의 run_log.json을 읽어서 보여준다.
"""
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline import s1_extract  # noqa: E402
from pipeline.config import load_config, read_json, write_json  # noqa: E402

OUTPUTS = ROOT / "outputs"
JOB_DIR = OUTPUTS / "_demo"                 # 데모 실행 기록 (outputs/라서 Git 제외)
JOB_FILE = JOB_DIR / "current_job.json"
PYTHON = sys.executable                     # 가상환경(.venv)의 python

STEPS = [("s1", "원문 읽기"), ("s2", "요약"), ("s3", "대본"), ("s4", "그림 묘사"),
         ("s5", "그림 생성"), ("s6", "음성"), ("s7", "자막"), ("s8", "장면 영상"), ("s9", "최종 합성")]
SECTION_KO = {"intro": "도입", "body": "설명", "outro": "결론"}


def prepare_url(url: str) -> dict:
    """블로그 주소로 글을 준비한다 (허락받은 블로그만, 글 하나당 접속 1번).

    돌려주는 값: {"ok": True, title, body, note, source} 또는 {"ok": False, "not_allowed": bool, "message": ...}
    """
    cfg = load_config()
    try:
        post = s1_extract.get_post(cfg, url)
    except s1_extract.NotAllowedBlog:
        return {"ok": False, "not_allowed": True, "message": "허락된 블로그 주소만 사용할 수 있습니다"}
    except s1_extract.FetchFailed as e:
        return {"ok": False, "not_allowed": False, "message": f"글을 가져오지 못했습니다: {e}"}
    return {"ok": True, **{k: post[k] for k in ("title", "body", "note", "source", "sample_id")}}


def running_pipelines() -> list[str]:
    """지금 실행 중인 run.py 영상 생성 명령들 (한 번에 하나만 만들기 위해 확인)."""
    ps = subprocess.run(["ps", "-axo", "pid=,command="], capture_output=True, text=True).stdout
    return [line.strip() for line in ps.splitlines()
            if "run.py" in line and "--dry-run" not in line and "streamlit" not in line
            and re.search(r"--(sample|samples|text-file|url)\b", line)]


def _pid_running(pid: int) -> bool:
    try:
        done_pid, _ = os.waitpid(pid, os.WNOHANG)   # 우리가 띄운 프로세스면 끝났을 때 정리까지
        return done_pid == 0
    except ChildProcessError:                        # 페이지 서버를 다시 켠 경우 등
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False


def start(url: str, title: str) -> dict:
    """블로그 주소로 영상 생성을 시작한다 (한 번에 하나만).
    prepare_url()에서 이미 가져온 글을 쓰므로 블로그에 다시 접속하지 않는다."""
    if running_pipelines():
        raise RuntimeError("다른 영상 생성이 이미 실행 중입니다.")
    JOB_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    log = JOB_DIR / f"job_{ts}.log"
    with open(log, "w", encoding="utf-8") as f:
        proc = subprocess.Popen([PYTHON, "-u", "run.py", "--url", url.strip(), "--yes"], cwd=ROOT,
                                stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    job = {"pid": proc.pid, "url": url.strip(), "title": title.strip(), "log": str(log),
           "started_at": datetime.now().isoformat(timespec="seconds"), "started_ts": time.time()}
    write_json(JOB_FILE, job)
    return job


def status() -> dict | None:
    """가장 최근 데모 생성의 상태."""
    if not JOB_FILE.exists():
        return None
    job = read_json(JOB_FILE)
    job.setdefault("title", job.get("label", ""))
    running = _pid_running(job["pid"])
    log_text = Path(job["log"]).read_text(encoding="utf-8") if Path(job["log"]).exists() else ""
    m = re.search(r"결과 폴더: (\S+)", log_text)
    run_dir = ROOT / m.group(1) if m else None
    steps, this_run = {}, {}
    if run_dir and (run_dir / "run_log.json").exists():
        log = read_json(run_dir / "run_log.json")
        steps = log.get("steps", {})
        if not running and log.get("runs"):
            this_run = log["runs"][-1]
    failed = [(k, v.get("error")) for k, v in steps.items() if v.get("status") == "failed"]
    if not running and not run_dir:          # 결과 폴더를 만들기 전에 끝남 (주소 오류 등)
        failed = failed or [("시작", log_text.strip().splitlines()[-1] if log_text.strip() else "알 수 없음")]
    final = run_dir / "final.mp4" if run_dir else None
    ok = (not running) and final is not None and final.exists() and not failed and "이번 실행:" in log_text
    return {**job, "running": running, "run_dir": run_dir, "steps": steps, "failed": failed, "ok": ok,
            "done": sum(1 for k, _ in STEPS if steps.get(k, {}).get("status") in ("ok", "skipped")),
            "elapsed": round(time.time() - job["started_ts"]),
            "cost_usd": this_run.get("cost_usd"), "api_calls": this_run.get("api_calls"),
            "duration_sec": this_run.get("duration_sec")}


def script_rows(run_dir: Path) -> list[dict]:
    """장면별 대본 (음성용·자막)."""
    path = Path(run_dir) / "scenes.json"
    if not path.exists():
        return []
    return [{"장면": s["id"], "구분": SECTION_KO.get(s["section"], s["section"]),
             "음성용 문장": s["narration"], "자막": s.get("subtitle") or s["narration"]}
            for s in read_json(path)["scenes"]]
