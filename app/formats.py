"""Форматирование транскрипта в .txt / .srt."""


def _spk(label: str) -> str:
    return f"Спикер {label}"


def to_txt(rec: dict) -> str:
    utts = rec.get("utterances")
    if utts:
        speakers = {u.get("speaker") for u in utts}
        if len(speakers) > 1:
            return "\n\n".join(f"{_spk(u['speaker'])}: {u['text']}" for u in utts) + "\n"
    return (rec.get("text") or "") + "\n"


def _ts(ms: int) -> str:
    ms = int(ms)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def to_srt(rec: dict) -> str:
    utts = rec.get("utterances")
    multi = bool(utts) and len({u.get("speaker") for u in utts}) > 1
    blocks = []
    if utts:
        for i, u in enumerate(utts, 1):
            text = f"{_spk(u['speaker'])}: {u['text']}" if multi else u["text"]
            blocks.append(f"{i}\n{_ts(u['start'])} --> {_ts(u['end'])}\n{text}\n")
    elif rec.get("words"):
        words, chunk, i = rec["words"], [], 1
        for w in words:
            chunk.append(w)
            if len(chunk) >= 12 or w["text"].endswith((".", "?", "!")):
                blocks.append(f"{i}\n{_ts(chunk[0]['start'])} --> {_ts(chunk[-1]['end'])}\n"
                              + " ".join(c["text"] for c in chunk) + "\n")
                i += 1
                chunk = []
        if chunk:
            blocks.append(f"{i}\n{_ts(chunk[0]['start'])} --> {_ts(chunk[-1]['end'])}\n"
                          + " ".join(c["text"] for c in chunk) + "\n")
    return "\n".join(blocks)
