"""
models.py – Whisper model discovery, download, validation, and device detection.
"""
import os, shutil

ONLINE_MODELS = ["large-v3", "large-v3-turbo", "medium", "small", "base", "tiny"]
HF_REPOS = {
    "large-v3":       "Systran/faster-whisper-large-v3",
    "large-v3-turbo": "deepdml/faster-whisper-large-v3-turbo-ct2",
    "medium":         "Systran/faster-whisper-medium",
    "small":          "Systran/faster-whisper-small",
    "base":           "Systran/faster-whisper-base",
    "tiny":           "Systran/faster-whisper-tiny",
}
# Conservative lower-bound sizes (bytes) for download integrity checks.
MODEL_MIN_BYTES = {
    "large-v3":       2_900_000_000,
    "large-v3-turbo": 1_400_000_000,
    "medium":         1_400_000_000,
    "small":          440_000_000,
    "base":           130_000_000,
    "tiny":           65_000_000,
}
MODEL_APPROX_TOTAL_BYTES = {
    "large-v3":       3_100_000_000,
    "large-v3-turbo": 1_600_000_000,
    "medium":         1_530_000_000,
    "small":          484_000_000,
    "base":           145_000_000,
    "tiny":           75_000_000,
}

# Prefix used to mark models that need to be downloaded
_DL_PREFIX = "\u2193 "   # ↓ downward arrow


def folder_size_bytes(path):
    total = 0
    try:
        for root_dir, _, files in os.walk(path):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(root_dir, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def verify_model_integrity(dest, model_name):
    """Return (ok, reason). Catches missing/truncated/corrupt downloads."""
    model_bin = os.path.join(dest, "model.bin")
    if not os.path.exists(model_bin):
        return False, "model.bin is missing (download did not complete)."
    size = os.path.getsize(model_bin)
    min_size = MODEL_MIN_BYTES.get(model_name, 10_000_000)
    if size < min_size:
        return False, (f"model.bin is only {size/1e6:.1f} MB, expected at "
                       f"least ~{min_size/1e6:.0f} MB - the download was "
                       f"likely interrupted or corrupted.")
    return True, ""


def cleanup_incomplete_model(dest):
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)


def detect_device():
    """Pick the best available device for faster-whisper.

    Returns (device, compute_type, warning_or_None).
    Falls back to CPU with int8 if no CUDA-capable GPU is found.
    """
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16", None
    except Exception:
        pass
    return "cpu", "int8", (
        "No usable NVIDIA GPU detected - running on CPU. "
        "This works but is significantly slower than GPU transcription.")


def scan_local_models(d):
    """List local model folders that contain a valid model.bin.

    Folders with a missing or undersized model.bin are excluded so the UI
    never shows a broken model as ready.
    """
    if not os.path.isdir(d):
        return []
    found = []
    for n in os.listdir(d):
        model_bin = os.path.join(d, n, "model.bin")
        if not os.path.exists(model_bin):
            continue
        known_key = next((m for m in ONLINE_MODELS
                          if n == m or n.endswith(f"-{m}")), None)
        min_size = MODEL_MIN_BYTES.get(known_key, 10_000_000)
        try:
            if os.path.getsize(model_bin) < min_size:
                continue
        except OSError:
            continue
        found.append(n)
    return found


def build_model_choices(local):
    """Map each known online model to a local folder if one exists.

    Uses exact suffix matching to avoid false matches between similarly
    named models (e.g. large-v3 vs large-v3-turbo).

    Downloaded models are returned as-is (folder name).
    Models not yet downloaded are prefixed with _DL_PREFIX.
    """
    choices = []
    used = set()
    for m in ONLINE_MODELS:
        match = None
        for n in local:
            if n in used:
                continue
            if n == m or n.endswith(f"-{m}"):
                match = n
                break
        if match:
            choices.append(match)
            used.add(match)
        else:
            choices.append(f"{_DL_PREFIX}{m}")
    return choices


def is_dl_choice(choice):
    """Return True if this combo item represents a not-yet-downloaded model."""
    return choice.startswith(_DL_PREFIX)


def dl_model_name(choice):
    """Strip the download prefix and return the bare model name."""
    return choice[len(_DL_PREFIX):].strip()


def resolve_model(choice, models_dir):
    if is_dl_choice(choice):
        return None, True, dl_model_name(choice)
    return os.path.join(models_dir, choice), False, None


def validate_model(choice, models_dir):
    if not choice or choice == "Scanning...":
        return False, "No model selected."
    if is_dl_choice(choice):
        return True, ""
    mp = os.path.join(models_dir, choice)
    model_bin = os.path.join(mp, "model.bin")
    if not os.path.exists(model_bin):
        return False, (f"model.bin not found:\n{mp}\n\n"
                       "Only faster-whisper (CTranslate2) format is supported.")
    known_key = next((m for m in ONLINE_MODELS
                      if choice == m or choice.endswith(f"-{m}")), None)
    min_size = MODEL_MIN_BYTES.get(known_key, 10_000_000)
    actual = os.path.getsize(model_bin)
    if actual < min_size:
        return False, (f"model.bin looks incomplete or corrupted "
                       f"({actual/1e6:.1f} MB, expected at least "
                       f"~{min_size/1e6:.0f} MB):\n{mp}\n\n"
                       "Delete this folder and re-download the model.")
    return True, ""
