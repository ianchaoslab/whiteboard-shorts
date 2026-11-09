# 외부 라이브러리 라이선스

이 프로젝트가 사용하는 외부 코드 중 출처와 라이선스 문구를 함께 남겨야 하는 것들입니다.
이 저장소에는 아래 코드나 모델을 복사해 넣지 않았고, `pip install -r requirements.txt`로 설치해서 사용합니다.

## whiteboard-animator

| 항목 | 내용 |
|---|---|
| 저장소 | https://github.com/masihsultani/whiteboard-animator |
| 사용 버전 | 0.1.1 (PyPI `whiteboard-animator==0.1.1`) |
| 라이선스 | MIT License, Copyright (c) 2026 Masih Sultani |
| 사용 위치 | `pipeline/draw_whiteboard.py`: 선화를 그리는 순서와 픽셀별 나타나는 시간 계산 |
| 비고 | 내부 함수를 사용하므로 버전을 0.1.1로 고정합니다 |

```
MIT License

Copyright (c) 2026 Masih Sultani

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## CRAFT 글자 감지 모델 (whiteboard-animator에 포함)

whiteboard-animator 패키지에는 글자 감지 모델 `craft.onnx`가 들어 있습니다.
whiteboard-animator의 README에 따르면 이 모델은 CRAFT-pytorch의 `craft_mlt_25k`를 ONNX로 변환한 것입니다.

| 항목 | 내용 |
|---|---|
| 저장소 | https://github.com/clovaai/CRAFT-pytorch |
| 라이선스 | MIT License, Copyright (c) 2019-present NAVER Corp. |

```
Copyright (c) 2019-present NAVER Corp.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
```

## 그 밖의 라이브러리

`requirements.txt`의 다른 라이브러리(openai, pydantic, Pillow, numpy, Streamlit 등)는 각 패키지에 들어 있는 라이선스를 따릅니다.
