"""TTS 엔진 모음 (교체 가능한 구조).

모든 엔진은 같은 모양이다:
    엔진(ctx, 대본 글, 목소리, 저장할 경로) → 정보 dict
나머지 단계(S6~S9)는 엔진이 만든 음성 파일만 쓰고, 어떤 엔진인지는 모른다.
다른 모델이나 서비스로 바꿀 때는 이 파일에 함수를 하나 추가하고
ENGINES에 이름을 등록한 뒤, config.toml의 tts_provider만 바꾸면 된다.

⚠️ gpt-4o-mini-tts는 2027-01-06 종료 예정 (README 한계점 참고).
"""
from pathlib import Path


def openai_speech(ctx, text: str, voice: str, out_path: Path) -> dict:
    """OpenAI Speech API (/v1/audio/speech).

    공식 문서: https://developers.openai.com/api/docs/guides/text-to-speech
    응답은 음성 파일뿐이라 사용량(토큰) 정보가 없다.
    """
    m = ctx.cfg["models"]
    client = ctx.llm().client
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with client.audio.speech.with_streaming_response.create(
        model=m["tts"],
        voice=voice,
        input=text,
        instructions=m["tts_instructions"],
        response_format=m["tts_format"],
    ) as response:
        response.stream_to_file(out_path)
    return {"provider": "openai", "model": m["tts"], "voice": voice,
            "instructions": m["tts_instructions"], "format": m["tts_format"]}


ENGINES = {
    "openai": openai_speech,
}


def synthesize(ctx, text: str, voice: str, out_path: Path) -> dict:
    provider = ctx.cfg["models"]["tts_provider"]
    if provider not in ENGINES:
        raise SystemExit(f"❌ 알 수 없는 TTS 엔진: {provider} (사용 가능: {', '.join(ENGINES)})")
    return ENGINES[provider](ctx, text, voice, out_path)
