"""실행 하나에 필요한 정보(설정, 샘플 번호, 결과 폴더, 기록)를 묶어 각 단계에 넘긴다."""
from dataclasses import dataclass, field
from pathlib import Path

from .llm import LLM
from .run_log import RunLog


@dataclass
class Context:
    cfg: dict
    sample_id: str
    run_dir: Path
    run_log: RunLog
    input_file: Path | None = None   # 붙여넣은 원문 파일 (없으면 samples/의 샘플 파일)
    _llm: LLM | None = field(default=None, repr=False)

    def llm(self) -> LLM:
        """OpenAI 연결은 실제로 API가 필요한 단계에서만 만든다."""
        if self._llm is None:
            self._llm = LLM(self.cfg, self.run_log)
        return self._llm
