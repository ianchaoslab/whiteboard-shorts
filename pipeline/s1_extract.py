"""S1 추출: 글의 제목·본문을 source.json으로 저장한다 (API 비용 없음).

입력 규칙
- 자동 수집 허락 범위는 블로그 아이디 기준이다: config.toml [sources] allowed_blog_ids
  다른 블로그 주소는 접속하지 않고 멈춘다.
- 허락받은 블로그 주소는 PostView 주소로 1번만 가져와 samples/web/에 저장한다.
  이미 가져온 글은 다시 접속하지 않는다 (글 하나당 1번).
- 접속이 실패했는데 그 글이 평가용 샘플 중 하나면, samples/에 저장된 본문을 쓴다.
- --sample 실행은 samples/의 저장된 파일을 쓰고 네이버에 접속하지 않는다.
- 붙여넣은 원문 파일(--text-file)은 그 파일을 쓴다.
"""
import re
from pathlib import Path

from .config import ROOT, project_path, read_json, sha, write_json

OUTPUT = "source.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
}


class NotAllowedBlog(Exception):
    """허락받지 않은 블로그 주소."""


class FetchFailed(Exception):
    """허락받은 블로그지만 본문을 가져오지 못함."""


def allowed_samples(cfg: dict) -> list[dict]:
    """평가용 샘플 목록 표(config [paths] samples_doc)의 샘플들. 표 파일이 없으면 빈 목록."""
    doc = project_path(cfg, "samples_doc")
    if not doc.exists():
        return []
    text = doc.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\|\s*(\d+)\s*\|\s*([\w-]+)\s*\|\s*(\d+)\s*\|\s*(https://blog\.naver\.com/\S+)\s*\|",
        text, flags=re.M)
    return [{"sample_id": f"{int(no):02d}", "blog_id": b, "log_no": l, "url": u}
            for no, b, l, u in rows]


def parse_blog_url(url: str) -> tuple[str, str] | None:
    """네이버 블로그 글 주소에서 (블로그 아이디, 글 번호)를 꺼낸다. 글 주소가 아니면 None."""
    url = url.strip()
    m = (re.search(r"blog\.naver\.com/PostView\.n\w+\?.*?blogId=([\w-]+).*?logNo=(\d+)", url)
         or re.search(r"blog\.naver\.com/PostView\.n\w+\?.*?logNo=(\d+).*?blogId=([\w-]+)", url)
         or re.search(r"(?:m\.)?blog\.naver\.com/([\w-]+)/(\d+)", url))
    if not m:
        return None
    a, b = m.group(1), m.group(2)
    return (b, a) if a.isdigit() and not b.isdigit() else (a, b)


def is_allowed_blog(cfg: dict, blog_id: str) -> bool:
    return blog_id in cfg["sources"]["allowed_blog_ids"]


def find_sample_file(cfg: dict, sample_id: str) -> Path | None:
    files = sorted(project_path(cfg, "samples_dir").glob(f"{sample_id}_*.txt"))
    return files[0] if files else None


def parse_sample_file(path: Path) -> dict:
    """'제목: / 주소: / 본문:' 형식의 파일을 읽는다."""
    text = path.read_text(encoding="utf-8")
    head, body = text.split("본문:\n", 1)
    lines = head.splitlines()
    title = next(l for l in lines if l.startswith("제목:")).removeprefix("제목:").strip()
    url = next((l for l in lines if l.startswith("주소:")), "주소:").removeprefix("주소:").strip()
    return {"title": title, "url": url, "body": body.strip()}


def fetch_post(blog_id: str, log_no: str) -> dict:
    """허락받은 블로그 글 1개를 PostView 주소로 한 번 가져온다 (요청 1번)."""
    import requests
    from bs4 import BeautifulSoup

    url = (f"https://blog.naver.com/PostView.naver?blogId={blog_id}&logNo={log_no}"
           "&redirect=Dlog&widgetTypeCall=true&noTrackingCode=true&directAccess=false")
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.raise_for_status()
    except requests.RequestException as e:
        raise FetchFailed(f"접속 오류: {type(e).__name__}") from e
    soup = BeautifulSoup(r.text, "html.parser")
    body_el = soup.select_one(".se-main-container") or soup.select_one("#postViewArea")
    if body_el is None:
        raise FetchFailed("본문 영역을 찾지 못함 (비공개·삭제된 글일 수 있음)")
    title_el = soup.select_one(".se-title-text") or soup.select_one(".pcol1")
    body = body_el.get_text("\n", strip=True)
    if not body:
        raise FetchFailed("본문이 비어 있음")
    return {"title": title_el.get_text(" ", strip=True) if title_el else "", "body": body}


def write_post_file(path: Path, title: str, url: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"제목: {title}\n주소: {url}\n본문:\n{body}\n", encoding="utf-8")


def get_post(cfg: dict, url: str) -> dict:
    """블로그 주소로 글을 준비한다.

    돌려주는 값: {sample_id, path, title, body, source, note}
      source: "cache"(이미 가져온 글, 접속 안 함) / "live"(지금 1번 접속) / "saved_sample"(접속 실패 → 저장된 샘플)
    허락받지 않은 블로그면 NotAllowedBlog, 가져오지 못하면 FetchFailed.
    """
    parsed = parse_blog_url(url)
    if parsed is None:
        raise FetchFailed("네이버 블로그 글 주소 형식이 아닙니다 (예: https://blog.naver.com/아이디/글번호)")
    blog_id, log_no = parsed
    if not is_allowed_blog(cfg, blog_id):
        raise NotAllowedBlog(blog_id)
    canonical = f"https://blog.naver.com/{blog_id}/{log_no}"
    sample = next((s for s in allowed_samples(cfg) if (s["blog_id"], s["log_no"]) == (blog_id, log_no)), None)
    # 샘플 20건이면 평가용 샘플 번호를, 아니면 "블로그아이디-글번호"를 결과 이름으로 쓴다
    sample_id = sample["sample_id"] if sample else f"{blog_id}-{log_no}"
    cache = ROOT / cfg["sources"]["web_cache_dir"] / f"{blog_id}_{log_no}.txt"
    if cache.exists():
        post = parse_sample_file(cache)
        return {"sample_id": sample_id, "path": cache, **post, "source": "cache",
                "note": "이미 가져온 글이라 다시 접속하지 않았습니다."}
    try:
        post = fetch_post(blog_id, log_no)
    except FetchFailed as e:
        saved = find_sample_file(cfg, sample["sample_id"]) if sample else None
        if saved:
            post = parse_sample_file(saved)
            return {"sample_id": sample_id, "path": saved, **post, "source": "saved_sample",
                    "note": f"블로그 접속에 실패해 저장된 본문(샘플 {sample_id})을 씁니다. ({e})"}
        raise
    write_post_file(cache, post["title"], canonical, post["body"])
    return {"sample_id": sample_id, "path": cache, "title": post["title"], "url": canonical,
            "body": post["body"], "source": "live", "note": "블로그에서 본문을 가져왔습니다 (접속 1번)."}


def get_sample_file(cfg: dict, sample_id: str) -> Path:
    """--sample 실행용: samples/의 저장된 파일 (없으면 허락받은 블로그에서 1번 가져옴)."""
    path = find_sample_file(cfg, sample_id)
    if path:
        return path
    sample = next((s for s in allowed_samples(cfg) if s["sample_id"] == sample_id), None)
    if sample is None:
        raise SystemExit(f"❌ 샘플 {sample_id}번 파일이 samples/에 없고, 샘플 목록에도 없습니다.")
    if not is_allowed_blog(cfg, sample["blog_id"]):
        raise SystemExit(f"❌ 허락받지 않은 블로그입니다: {sample['blog_id']}")
    print(f"   samples/에 {sample_id}번 파일이 없어 허락받은 블로그에서 1번 가져옵니다: {sample['url']}")
    post = fetch_post(sample["blog_id"], sample["log_no"])
    path = project_path(cfg, "samples_dir") / f"{sample_id}_{sample['log_no']}.txt"
    write_post_file(path, post["title"], sample["url"], post["body"])
    return path


def has_output(run_dir: Path) -> bool:
    return (run_dir / OUTPUT).exists()


def run(ctx, force: bool = False) -> tuple[str, list[str]]:
    out = ctx.run_dir / OUTPUT
    # 붙여넣은 원문 파일이 있으면 그것을, 없으면 허락받은 샘플 파일을 쓴다
    path = ctx.input_file or get_sample_file(ctx.cfg, ctx.sample_id)
    src = parse_sample_file(path)
    if not src["body"].strip():
        raise SystemExit(f"❌ 원문 본문이 비어 있습니다: {path}")
    input_sha = sha(src)

    if out.exists() and not force and read_json(out).get("meta", {}).get("input_sha") == input_sha:
        return "skipped", []

    warnings = [] if src["body"] else ["본문이 비어 있음"]
    write_json(out, {
        "sample_id": ctx.sample_id,
        "title": src["title"],
        "url": src["url"],
        "body": src["body"],
        "body_chars": len(src["body"]),
        "source_file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "meta": {"input_sha": input_sha},
    })
    return "ok", warnings
