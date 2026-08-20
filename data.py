"""
data.py – Language lists, translation targets, subtitle parsing/writing,
          Ollama helpers, and input validation.
"""
import os, re, json, time, urllib.request

# ══════════════════════════════════════════════════════════════════════════════
# Source languages  (faster-whisper supported)
# Format: ("English Name / Native Script", "language_code")
# ══════════════════════════════════════════════════════════════════════════════
LANGUAGES = [
    ("Auto Detect",              None),
    ("Chinese (Simplified) / 简体中文",     "zh"),
    ("Chinese (Traditional) / 繁體中文",    "zh"),
    ("Japanese / 日本語",                   "ja"),
    ("Korean / 한국어",                     "ko"),
    ("Thai / ภาษาไทย",                     "th"),
    ("Vietnamese / Tiếng Việt",            "vi"),
    ("Indonesian / Bahasa Indonesia",      "id"),
    ("Arabic / العربية",                   "ar"),
    ("Hebrew / עברית",                     "he"),
    ("Hindi / हिन्दी",                     "hi"),
    ("Turkish / Türkçe",                   "tr"),
    ("Persian / فارسی",                    "fa"),
    ("English / English",                  "en"),
    ("French / Français",                  "fr"),
    ("German / Deutsch",                   "de"),
    ("Spanish / Español",                  "es"),
    ("Portuguese / Português",             "pt"),
    ("Italian / Italiano",                 "it"),
    ("Russian / Русский",                  "ru"),
    ("Ukrainian / Українська",             "uk"),
    ("Polish / Polski",                    "pl"),
    ("Dutch / Nederlands",                 "nl"),
    ("Swedish / Svenska",                  "sv"),
    ("Norwegian / Norsk",                  "no"),
    ("Danish / Dansk",                     "da"),
    ("Finnish / Suomi",                    "fi"),
    ("Czech / Čeština",                    "cs"),
    ("Hungarian / Magyar",                 "hu"),
    ("Romanian / Română",                  "ro"),
    ("Greek / Ελληνικά",                   "el"),
]

LANG_DISPLAY = [l[0] for l in LANGUAGES]
LANG_CODE    = {l[0]: l[1] for l in LANGUAGES}

# ══════════════════════════════════════════════════════════════════════════════
# Translation target languages  (Ollama-driven)
# "code"   → subtitle file suffix  (e.g. video.chs.srt)
# "prompt" → instruction sent to Ollama
# ══════════════════════════════════════════════════════════════════════════════
TRANSLATE_TARGETS_DEF = [
    {
        "display": "Chinese (Simplified) / 简体中文",
        "code":    "chs",
        "prompt":  "You are a professional subtitle translator. Translate the following text into Simplified Chinese. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "Chinese (Traditional) / 繁體中文",
        "code":    "cht",
        "prompt":  "You are a professional subtitle translator. Translate the following text into Traditional Chinese. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "English / English",
        "code":    "eng",
        "prompt":  "You are a professional subtitle translator. Translate the following text into English. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "Japanese / 日本語",
        "code":    "jpn",
        "prompt":  "You are a professional subtitle translator. Translate the following text into Japanese. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "Korean / 한국어",
        "code":    "kor",
        "prompt":  "You are a professional subtitle translator. Translate the following text into Korean. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "French / Français",
        "code":    "fre",
        "prompt":  "You are a professional subtitle translator. Translate the following text into French. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "German / Deutsch",
        "code":    "ger",
        "prompt":  "You are a professional subtitle translator. Translate the following text into German. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "Spanish / Español",
        "code":    "spa",
        "prompt":  "You are a professional subtitle translator. Translate the following text into Spanish. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "Portuguese / Português",
        "code":    "por",
        "prompt":  "You are a professional subtitle translator. Translate the following text into Portuguese. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "Russian / Русский",
        "code":    "rus",
        "prompt":  "You are a professional subtitle translator. Translate the following text into Russian. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "Arabic / العربية",
        "code":    "ara",
        "prompt":  "You are a professional subtitle translator. Translate the following text into Arabic. Output only the translation, no explanations. Source: ",
    },
    {
        "display": "Italian / Italiano",
        "code":    "ita",
        "prompt":  "You are a professional subtitle translator. Translate the following text into Italian. Output only the translation, no explanations. Source: ",
    },
]

# Convenience lookups built from the definition list above
TRANSLATE_TARGETS = [t["display"] for t in TRANSLATE_TARGETS_DEF]
_TGT_BY_DISPLAY   = {t["display"]: t for t in TRANSLATE_TARGETS_DEF}

# The display name used to detect "English" target (for Whisper built-in translate)
ENGLISH_TARGET_DISPLAY = "English / English"

# The display name for "Auto Detect" source language (always kept at top of list)
AUTO_DETECT_DISPLAY = "Auto Detect"


def tgt_code(display):
    """Return the subtitle suffix code for a target language display name."""
    return _TGT_BY_DISPLAY.get(display, {}).get("code", "tr")


def tgt_prompt(display):
    """Return the Ollama prompt prefix for a target language display name."""
    return _TGT_BY_DISPLAY.get(display, {}).get("prompt",
        "Translate the following subtitle text. Output only the translation. Source: ")


def sorted_by_freq(items, freq_dict, pinned_top=None):
    """Return a copy of *items* sorted by descending usage frequency.

    Items with equal frequency keep their original relative order.
    If *pinned_top* is given, that item is always placed first regardless
    of its frequency.
    """
    pinned = [x for x in items if x == pinned_top]
    rest   = [x for x in items if x != pinned_top]
    rest.sort(key=lambda x: freq_dict.get(x, 0), reverse=True)
    return pinned + rest


# ══════════════════════════════════════════════════════════════════════════════
# Formats, Ollama, misc constants
# ══════════════════════════════════════════════════════════════════════════════
FORMATS    = [".srt", ".vtt", ".txt"]
OLLAMA_URL = "http://localhost:11434"
MAX_RETRIES = 3
MAX_TRANSLATION_CH = 2000

MEDIA_EXTS = {".mp3", ".mp4", ".wav", ".m4a", ".aac", ".flac", ".ogg",
              ".mkv", ".mov", ".avi", ".webm", ".wma", ".opus", ".oga", ".ts"}
SUBTITLE_EXTS = {".srt", ".vtt", ".txt"}
MAX_SUBTITLE_BYTES = 50 * 1024 * 1024


def ollama_models():
    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags")
        with urllib.request.urlopen(req, timeout=3) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return []


def ollama_translate(model, prompt, text, is_stopped, retries=MAX_RETRIES):
    """Translate *text* via Ollama.

    *is_stopped* is a zero-arg callable returning True if the caller wants
    to abort. Returns (text_or_translation, failed: bool).
    """
    for attempt in range(1, retries + 1):
        if is_stopped():
            return text, True
        try:
            body = json.dumps({"model": model, "prompt": prompt + text,
                               "stream": False,
                               "options": {"temperature": 0.1}}).encode()
            req = urllib.request.Request(
                f"{OLLAMA_URL}/api/generate", data=body,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                result = json.loads(r.read()).get("response", "").strip()
                if len(result) > MAX_TRANSLATION_CH:
                    result = result[:MAX_TRANSLATION_CH] + "..."
                return result, False
        except Exception:
            for _ in range(2 * attempt):
                if is_stopped():
                    return text, True
                time.sleep(1)
    return text, True


# ══════════════════════════════════════════════════════════════════════════════
# Batched Ollama translation
#
# Sending one Ollama request per subtitle line is slow (hundreds of blocking
# HTTP round-trips for a long video) and starves the model of context (each
# line is translated with no idea what the previous/next line says, which
# hurts pronoun resolution, tone, and continuity). The functions below send
# a whole group of lines - numbered, in order - in a single request and ask
# the model to return a JSON array of the same length, so one call does the
# work of many while giving the model the surrounding lines as context.
#
# Reliability matters more than the happy path here: small local models
# served through Ollama are not perfectly reliable JSON generators, so a
# batch whose response can't be parsed back into exactly as many lines as
# went in is retried, and - if it still won't parse - the batch quietly
# falls back to translating its lines one at a time via ollama_translate()
# above, so a single malformed reply never costs a whole batch of lines.
# ══════════════════════════════════════════════════════════════════════════════
TRANSLATE_BATCH_SIZE    = 15   # subtitle lines sent per Ollama request
TRANSLATE_BATCH_TIMEOUT = 180  # seconds - a batch reply is much longer than a single line


def _extract_json_array(raw, expected_n=None):
    """Best-effort extraction of a list of strings from a raw LLM response
    that may be clean JSON, JSON wrapped in a ``` fence, a JSON object keyed
    by line number, or JSON with some chatty text around it. Returns a list
    on success, or None if nothing usable could be found."""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1).strip()

    def _from_json_text(txt):
        try:
            data = json.loads(txt)
        except (json.JSONDecodeError, ValueError):
            return None
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            try:
                items = sorted(data.items(), key=lambda kv: int(kv[0]))
                return [v for _, v in items]
            except (ValueError, TypeError):
                return list(data.values())
        return None

    result = _from_json_text(raw)
    if result is not None:
        return result

    # The model may have added a preamble/postamble around the array -
    # slice out the outermost [...] and try again.
    start, end = raw.find("["), raw.rfind("]")
    if start != -1 and end != -1 and end > start:
        result = _from_json_text(raw[start:end + 1])
        if result is not None:
            return result
    return None


def _parse_numbered_lines(raw, expected_n):
    """Fallback parser for '1. xxx' / '1) xxx' / '1: xxx' style output, in
    case the model ignores the JSON-array instruction. Only accepted if
    every one of the expected numbers 1..expected_n was found exactly once."""
    found = {}
    for ln in raw.splitlines():
        m = re.match(r"\s*(\d+)[.:)、]\s*(.+?)\s*$", ln)
        if m:
            idx = int(m.group(1))
            if 1 <= idx <= expected_n:
                found[idx] = m.group(2).strip()
    if len(found) == expected_n:
        return [found[i] for i in range(1, expected_n + 1)]
    return None


def _batch_prompt(base_prompt, chunk):
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(chunk))
    return (
        f"{base_prompt}\n\n"
        f"You will be given {len(chunk)} numbered subtitle lines from the same "
        f"scene, in their original order. Translate each line on its own - use "
        f"the other lines only as context for tone, pronouns, and continuity. "
        f"Do not merge, split, add, or drop any line; the output must have "
        f"exactly {len(chunk)} items in the same order as the input.\n"
        f"Reply with ONLY a JSON array of {len(chunk)} translated strings, e.g. "
        f'["...", "...", ...] - no numbering, no code fences, no commentary.\n\n'
        f"{numbered}"
    )


def _translate_batch_once(model, prompt, chunk, timeout=TRANSLATE_BATCH_TIMEOUT):
    """Single Ollama call translating an entire chunk at once.
    Returns a list[str] of len(chunk) on success, or None if the response
    couldn't be parsed into exactly that many items."""
    body = json.dumps({"model": model, "prompt": _batch_prompt(prompt, chunk),
                       "stream": False,
                       "options": {"temperature": 0.1}}).encode()
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=body,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = json.loads(r.read()).get("response", "")

    items = _extract_json_array(raw, len(chunk))
    if items is None:
        items = _parse_numbered_lines(raw, len(chunk))
    if items is None or len(items) != len(chunk):
        return None

    out = []
    for it in items:
        it = str(it).strip()
        if len(it) > MAX_TRANSLATION_CH:
            it = it[:MAX_TRANSLATION_CH] + "..."
        out.append(it)
    return out


def translate_chunk(model, prompt, chunk, is_stopped, retries=MAX_RETRIES):
    """Translate one chunk (list[str]) with a single batched Ollama request
    when possible, retrying on failure/unparseable replies. If the batch
    still can't be parsed after *retries* attempts, falls back to
    translating the chunk's lines one at a time via ollama_translate(), so
    one malformed reply never loses a whole chunk of lines.

    *is_stopped* is a zero-arg callable returning True once the caller wants
    to abort; if it blocks (e.g. to honor a pause) it should return once
    resumed, and only return True to actually stop.

    Returns (translations: list[str], failed: list[bool]) - both the same
    length as *chunk*.
    """
    for attempt in range(1, retries + 1):
        if is_stopped():
            return list(chunk), [True] * len(chunk)
        try:
            result = _translate_batch_once(model, prompt, chunk)
            if result is not None:
                return result, [False] * len(chunk)
        except Exception:
            pass
        for _ in range(2 * attempt):
            if is_stopped():
                return list(chunk), [True] * len(chunk)
            time.sleep(1)

    # Batched translation kept failing to parse/respond - fall back to
    # one-by-one so a single bad reply doesn't cost the whole chunk.
    translations, failed = [], []
    for text in chunk:
        tr, fail = ollama_translate(model, prompt, text, is_stopped)
        translations.append(tr)
        failed.append(fail)
    return translations, failed


def translate_segments(model, prompt, texts, is_stopped, batch_size=TRANSLATE_BATCH_SIZE):
    """Translate *texts* (list[str]) in order, batch_size lines per Ollama
    request, yielding results as each batch completes.

    Yields (start_index, chunk_translations, chunk_failed) once per
    completed chunk - chunk_failed is a list[bool] aligned with
    chunk_translations - so the caller can update progress/log and write
    partial output incrementally as each chunk lands, without waiting for
    the whole file to finish.

    *is_stopped* is polled before each chunk is dispatched (and between
    retries inside a chunk). When it returns True the in-flight chunk is
    never yielded, so translations accumulated by the caller always remain
    a clean, contiguous prefix of *texts* - never a chunk with gaps.
    """
    n = len(texts)
    i = 0
    while i < n:
        if is_stopped():
            return
        chunk = texts[i:i + batch_size]
        translations, failed = translate_chunk(model, prompt, chunk, is_stopped)
        yield i, translations, failed
        i += len(chunk)


# ══════════════════════════════════════════════════════════════════════════════
# Subtitle parsing / writing
# ══════════════════════════════════════════════════════════════════════════════
def srt_time(s):
    h, m, sec, ms = int(s//3600), int((s%3600)//60), int(s%60), int((s%1)*1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def vtt_time(s):
    return srt_time(s).replace(",", ".")


def ext_of(fmt):
    return fmt.lstrip(".")


def write_segs(path, fmt, segs, translations):
    """Write subtitle segments with their translations to a file.
    segs and translations must be the same length."""
    e = ext_of(fmt)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if e == "vtt":
            f.write("WEBVTT\n\n")
        for i, (seg, txt) in enumerate(zip(segs, translations), 1):
            if e == "srt":
                f.write(f"{i}\n{srt_time(seg.start)} --> {srt_time(seg.end)}\n{txt}\n\n")
            elif e == "vtt":
                f.write(f"{vtt_time(seg.start)} --> {vtt_time(seg.end)}\n{txt}\n\n")
            else:
                f.write(txt + "\n")


def out_orig(d, b, fmt):
    """Original transcription output path."""
    return os.path.join(d, f"{b}{fmt}")


def out_trans(d, b, tgt_display, fmt):
    """Translated subtitle output path, e.g. video.chs.srt"""
    code = tgt_code(tgt_display)
    return os.path.join(d, f"{b}.{code}{fmt}")


def out_bili(d, b, tgt_display, fmt):
    """Bilingual subtitle output path, e.g. video.chs.bilingual.srt"""
    code = tgt_code(tgt_display)
    return os.path.join(d, f"{b}.{code}.bilingual{fmt}")


class SubSeg:
    __slots__ = ("index", "start", "end", "text")
    def __init__(self, i, s, e, t):
        self.index = i; self.start = s; self.end = e; self.text = t


def parse_sub(path):
    e = os.path.splitext(path)[1].lower()
    size = os.path.getsize(path)
    if size > MAX_SUBTITLE_BYTES:
        raise ValueError(f"File too large: {size/1024/1024:.1f} MB\nMax: 50 MB")
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except PermissionError:
        raise ValueError(f"Permission denied:\n{path}")
    except Exception as ex:
        raise ValueError(f"Cannot read file:\n{ex}")
    if not raw.strip():
        raise ValueError("Subtitle file is empty.")
    segs = []
    if e in (".srt", ".vtt"):
        for blk in re.split(r"\n\s*\n", raw.strip()):
            lines = blk.strip().splitlines()
            if not lines or lines[0].strip().upper().startswith("WEBVTT"):
                continue
            tl = next((l for l in lines if "-->" in l), None)
            if not tl:
                continue
            ti = lines.index(tl)
            pts = tl.split("-->")
            segs.append(SubSeg(
                lines[0].strip() if ti > 0 else str(len(segs)+1),
                pts[0].strip(), pts[1].strip().split()[0],
                "\n".join(lines[ti+1:]).strip()))
        if not segs:
            raise ValueError(f"No subtitle blocks found in {e} file.")
    else:
        for i, ln in enumerate(raw.splitlines(), 1):
            if ln.strip():
                segs.append(SubSeg(str(i), "0", "0", ln.strip()))
        if not segs:
            raise ValueError("Text file has no content.")
    return segs


def write_sub(path, fmt, segs, translations, bilingual):
    e = ext_of(fmt)
    with open(path, "w", encoding="utf-8") as f:
        if e == "vtt":
            f.write("WEBVTT\n\n")
        for i, (seg, tr) in enumerate(zip(segs, translations), 1):
            body = f"{seg.text}\n{tr}" if bilingual else tr
            if e == "txt":
                f.write(body + "\n")
            elif e == "srt":
                f.write(f"{i}\n{seg.start} --> {seg.end}\n{body}\n\n")
            else:
                f.write(f"{seg.start} --> {seg.end}\n{body}\n\n")


# ══════════════════════════════════════════════════════════════════════════════
# Input validation
# ══════════════════════════════════════════════════════════════════════════════
def sanitize_filename(name):
    name = os.path.basename(name)
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", name)
    name = re.sub(r"_{2,}", "_", name).strip("_. ")
    return name or "output"


def validate_media(path):
    if not path or not path.strip(): return False, "No file selected."
    if not os.path.exists(path):     return False, f"File not found:\n{path}"
    if not os.path.isfile(path):     return False, f"Not a file:\n{path}"
    if os.path.getsize(path) == 0:   return False, "File is empty (0 bytes)."
    ext = os.path.splitext(path)[1].lower()
    if ext not in MEDIA_EXTS:
        return False, (f"Unsupported type: '{ext}'\n\nSupported:\n"
                       + ", ".join(sorted(MEDIA_EXTS)))
    return True, ""


def validate_subtitle(path):
    if not path or not path.strip(): return False, "No file selected."
    if not os.path.exists(path):     return False, f"File not found:\n{path}"
    if not os.path.isfile(path):     return False, f"Not a file:\n{path}"
    if os.path.getsize(path) == 0:   return False, "File is empty (0 bytes)."
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUBTITLE_EXTS:
        hint = ""
        if ext in MEDIA_EXTS:
            hint = "\n\nThis looks like a media file.\nUse the Transcribe tab first."
        return False, (f"Unsupported type: '{ext}'\n\n"
                       f"Translate tab accepts: .srt .vtt .txt{hint}")
    return True, ""


def validate_output_dir(d):
    if not d or not d.strip(): return False, "No output directory selected."
    if not os.path.exists(d):
        try: os.makedirs(d, exist_ok=True)
        except Exception as e: return False, f"Cannot create directory:\n{e}"
    if not os.path.isdir(d): return False, f"Not a directory:\n{d}"
    test = os.path.join(d, ".fw_write_test")
    try:
        with open(test, "w") as f: f.write("x")
    except Exception as e:
        return False, f"Directory not writable:\n{e}"
    finally:
        try: os.remove(test)
        except Exception: pass
    return True, ""


def validate_ollama(name):
    if not name or name in ("detecting...", "(not found)"):
        return False, ("No Ollama model selected.\n\n"
                       "Make sure Ollama is running and click Refresh to reload.")
    return True, ""
