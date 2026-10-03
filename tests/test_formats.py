from app.formats import to_srt, to_txt
from tests.conftest import TRANSCRIPT


def test_txt_with_speakers():
    assert to_txt(TRANSCRIPT) == "Спикер A: Привет мир.\n\nСпикер B: Hello world.\n"


def test_txt_single_speaker_is_plain():
    rec = {"text": "один", "utterances": [{"speaker": "A", "text": "один", "start": 0, "end": 1}]}
    assert to_txt(rec) == "один\n"


def test_srt():
    out = to_srt(TRANSCRIPT)
    assert out.startswith("1\n00:00:00,000 --> 00:00:01,500\nСпикер A: Привет мир.\n")
    assert "2\n00:00:01,600 --> 00:00:03,200" in out


def test_srt_from_words():
    rec = {"words": [{"text": "Hi", "start": 0, "end": 400}, {"text": "there.", "start": 500, "end": 1200}]}
    assert "00:00:00,000 --> 00:00:01,200\nHi there." in to_srt(rec)
