import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from .. import transcription


@pytest.fixture
def local_whisper(monkeypatch, tmp_path):
    monkeypatch.setenv("DOUYIN_WHISPER_ROOT", str(tmp_path))
    monkeypatch.delenv("DOUYIN_WHISPER_MODEL", raising=False)
    checkpoint = tmp_path / "base.pt"
    checkpoint.write_bytes(b"test checkpoint")
    model = Mock(device=SimpleNamespace(type="cpu"))
    model.transcribe.return_value = {"language": "en", "segments": [
        {"start": 0, "end": 1, "text": " Hello"},
        {"start": 1, "end": 1.1, "text": " "},
        {"start": 1.1, "end": 2, "text": "world "},
    ]}
    whisper = SimpleNamespace(load_model=Mock(return_value=model),
                              load_audio=Mock(return_value=[0] * 32000),
                              audio=SimpleNamespace(SAMPLE_RATE=16000))
    monkeypatch.setitem(sys.modules, "whisper", whisper)
    transcription._load_model.cache_clear()
    yield checkpoint, whisper, model
    transcription._load_model.cache_clear()


def test_local_checkpoint_and_timestamp_contract(local_whisper):
    checkpoint, whisper, model = local_whisper
    stages, progress = [], []
    result = transcription.transcribe_segments("audio.wav", "en-US", stage=stages.append, progress=progress.append)
    whisper.load_model.assert_called_once_with(str(checkpoint.resolve()))
    assert result == {"text": "Hello world", "duration": 2.0, "language": "en", "segments": [
        {"id": "s1", "start": 0.0, "end": 1.0, "text": " Hello", "original_text": " Hello"},
        {"id": "s2", "start": 1.1, "end": 2.0, "text": "world ", "original_text": "world "},
    ]}
    assert stages == ["加载本地 Whisper 模型", "转写口播"]
    assert progress == [0, 2.0]
    assert model.transcribe.call_args.kwargs["language"] == "en"
    assert model.transcribe.call_args.kwargs["fp16"] is False
    transcription.transcribe_segments("audio.wav", "auto")
    assert model.transcribe.call_args.kwargs["language"] is None
    assert whisper.load_model.call_count == 1


def test_missing_checkpoint_never_calls_loader(local_whisper):
    checkpoint, whisper, _ = local_whisper
    checkpoint.unlink()
    with pytest.raises(ValueError, match="未找到本地 Whisper 模型"):
        transcription.transcribe_segments("audio.wav")
    whisper.load_model.assert_not_called()


def test_explicit_checkpoint(local_whisper, monkeypatch, tmp_path):
    checkpoint, whisper, _ = local_whisper
    monkeypatch.setenv("DOUYIN_WHISPER_MODEL", str(checkpoint))
    monkeypatch.setenv("DOUYIN_WHISPER_ROOT", str(tmp_path / "unused"))
    transcription.transcribe_segments("audio.wav")
    whisper.load_model.assert_called_once_with(str(checkpoint.resolve()))


def test_cancel_before_loading(local_whisper):
    _, whisper, _ = local_whisper
    with pytest.raises(InterruptedError):
        transcription.transcribe_segments("audio.wav", cancelled=lambda: True)
    whisper.load_model.assert_not_called()


def test_cancel_after_inference_does_not_publish_result(local_whisper):
    _, _, model = local_whisper
    progress = Mock()
    with pytest.raises(InterruptedError):
        transcription.transcribe_segments("audio.wav", cancelled=lambda: model.transcribe.called, progress=progress)
    progress.assert_called_once_with(0)
    # Cancellation must release the model lock for the next task.
    assert transcription.transcribe_segments("audio.wav")["duration"] == 2.0


def test_missing_dependency_is_actionable(local_whisper, monkeypatch):
    monkeypatch.setitem(sys.modules, "whisper", None)
    with pytest.raises(ValueError, match="openai-whisper"):
        transcription.transcribe_segments("audio.wav")
