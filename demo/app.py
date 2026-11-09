"""화이트보드 숏폼 생성기 — 데모 페이지 (Streamlit).

한 화면: 블로그 글 주소 입력 → [영상 만들기] → 진행 표시 → 완성 영상·다운로드·대본.
실행: source .venv/bin/activate 후  streamlit run demo/app.py  → http://localhost:8501
(원문 텍스트로 만들기는 화면에 없고, 명령어 python run.py --text-file 로 할 수 있다)
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jobs  # noqa: E402

st.set_page_config(page_title="화이트보드 숏폼 생성기", page_icon="✏️", layout="centered")
st.title("✏️ 화이트보드 숏폼 생성기")
st.caption("블로그 글 주소를 넣으면 9:16 화이트보드 숏폼 영상을 만듭니다. (2~3분)")


def show_result(job: dict) -> None:
    """완성 영상 재생, MP4 다운로드, 접힌 대본."""
    run_dir = job["run_dir"]
    final = run_dir / "final.mp4"
    st.success("완성!")
    st.video(str(final), width=360)
    st.download_button("⬇️ MP4 다운로드", data=final.read_bytes(), file_name=f"{run_dir.name}.mp4",
                       mime="video/mp4")
    with st.expander("대본 보기", expanded=False):
        for row in jobs.script_rows(run_dir):
            st.markdown(f"**{row['장면']}. {row['구분']}** — {row['자막']}")
    if job.get("cost_usd") is not None:
        st.caption(f"실제 비용 ${job['cost_usd']:.3f} · API {job.get('api_calls', 0)}회 · "
                   f"{job.get('duration_sec')}초")


@st.fragment(run_every=3)
def progress_box() -> None:
    """생성 중 진행 표시 (3초마다 갱신). 끝나면 전체 화면을 다시 그린다."""
    job = jobs.status()
    if not job or not job["running"]:
        st.rerun()
        return
    total = len(jobs.STEPS)
    now = next((name for k, name in jobs.STEPS
                if job["steps"].get(k, {}).get("status") not in ("ok", "skipped")), "마무리")
    st.markdown(f"⏳ **만드는 중:** {job['title']}")
    st.progress(job["done"] / total, text=f"{job['done']}/{total} 단계 · {now} · {job['elapsed']}초")
    st.caption("페이지를 닫아도 생성은 계속됩니다.")


job = jobs.status()
mine = job and job["pid"] == st.session_state.get("my_job_pid")   # 이 화면에서 시작한 생성인지

if job and job["running"] and mine:
    progress_box()
else:
    url = st.text_input("블로그 글 주소", placeholder="https://blog.naver.com/아이디/글번호  (입력 후 Enter)")
    info = None
    if url.strip():
        if st.session_state.get("prepared_url") != url.strip():
            with st.spinner("글을 확인하는 중..."):
                st.session_state["prepared"] = jobs.prepare_url(url)
            st.session_state["prepared_url"] = url.strip()
        info = st.session_state["prepared"]
        if not info["ok"] and info.get("not_allowed"):
            st.error("허락된 블로그 주소만 사용할 수 있습니다")
        elif not info["ok"]:
            st.error(info["message"])
        else:
            title = info["title"]
            st.caption(f"📄 {title[:50]}{'…' if len(title) > 50 else ''}")

    busy = jobs.running_pipelines()
    if busy:
        st.warning("다른 영상을 만드는 중입니다. 끝난 뒤에 다시 눌러 주세요.")
    ready = bool(info and info["ok"])
    if st.button("🎬 영상 만들기", type="primary", disabled=not ready or bool(busy)):
        started = jobs.start(url, info["title"])
        st.session_state["my_job_pid"] = started["pid"]
        st.rerun()

    # 이 화면에서 시작한 생성이 끝났으면 결과를 보여준다
    if job and mine and not job["running"]:
        if job["ok"]:
            show_result(job)
        else:
            st.error("영상 생성에 실패했습니다.")
            for step, err in job["failed"]:
                st.caption(f"{step}: {err}")
