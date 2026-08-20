"""
workers.py – Background QThread workers for transcription and translation,
             plus the stdout/stderr redirector used during model downloads.

Stop/Pause/Stop-All model
--------------------------
Each worker exposes four control methods, meant to be called from the GUI
thread while the worker runs in the background:

    request_stop_stage()   Stop only the CURRENT file's CURRENT stage
                            (transcription, or translation). Whatever was
                            already produced for that stage is kept; the
                            queue then continues normally to the next
                            stage/file, completely unaffected.
    request_stop_all()     Abort the whole queue immediately: no further
                            stage or file is started. Work already
                            completed before the request is still kept.
    request_pause()        Freeze at the next safe point, without losing
                            or discarding any data produced so far.
    request_resume()       Continue from exactly where it paused.

Internally this is three flags per worker:

    _stop_stage   Reset to False every time a NEW stage begins (a new
                  file's transcription, or that same file's translation).
                  This reset is what keeps a stop from one stage/file
                  "bleeding" into the next one.
    _stop_all     Set once by Stop All and never reset - once true, the
                  file loop and every stage loop exit without starting
                  anything new.
    _resume_evt   A threading.Event; clear() = paused, set() = running.
                  _checkpoint() blocks on this between units of work
                  (each transcribed segment, each translated batch)
                  without discarding anything already produced.
"""
import sys, os, time, threading

from PySide6.QtCore import QThread, Signal

from models import (
    HF_REPOS, MODEL_APPROX_TOTAL_BYTES,
    verify_model_integrity, cleanup_incomplete_model, detect_device,
)
from data import (
    tgt_prompt, translate_segments,
    srt_time, vtt_time, ext_of, write_segs, out_orig, out_trans, out_bili,
    parse_sub, write_sub,
)

# ══════════════════════════════════════════════════════════════════════════════
# stdout/stderr redirector
# Pipes huggingface_hub / tqdm output into the GUI log during downloads.
# ══════════════════════════════════════════════════════════════════════════════
class _StreamToSignal:
    """Redirect sys.stdout / sys.stderr to a Qt Signal so that
    download progress appears in the GUI log."""
    def __init__(self, signal, original):
        self._signal   = signal
        self._original = original
        self._buf      = ""

    def write(self, text):
        try:
            self._original.write(text)
        except Exception:
            pass
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            stripped = line.rstrip()
            if stripped:
                self._signal.emit(stripped + "\n")

    def flush(self):
        try:
            self._original.flush()
        except Exception:
            pass
        if self._buf.strip():
            self._signal.emit(self._buf + "\n")
            self._buf = ""

    def fileno(self):
        return self._original.fileno()

    def isatty(self):
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Shared Pause/Stop/Stop-All control surface
# ══════════════════════════════════════════════════════════════════════════════
class _StageController:
    """Mixin providing the request_*/._checkpoint() control surface described
    in the module docstring. Subclasses must call __init__ and use
    ._checkpoint() between units of work in their run() loops."""

    def _init_controller(self):
        self._stop_stage = False
        self._stop_all   = False
        self._resume_evt = threading.Event()
        self._resume_evt.set()   # not paused by default

    def request_stop_stage(self):
        """Stop only the current file's current stage. Already-produced
        output for that stage is kept; the queue continues normally."""
        self._stop_stage = True
        self._resume_evt.set()   # wake up immediately if paused

    def request_stop_all(self):
        """Abort the entire queue immediately - no further stage or file
        is started. Work already completed before this call is kept."""
        self._stop_all = True
        self._resume_evt.set()

    def request_pause(self):
        self._resume_evt.clear()

    def request_resume(self):
        self._resume_evt.set()

    def _begin_stage(self):
        """Call at the start of every new stage (a new file's transcription,
        or that file's translation) to reset the per-stage stop flag."""
        self._stop_stage = False

    def _checkpoint(self):
        """Call between units of work (each segment, each translated batch).
        Blocks here while paused, without discarding anything already
        produced. Returns True if the current stage (or everything) should
        stop now."""
        while not self._resume_evt.is_set():
            if self._stop_all or self._stop_stage:
                return True
            self._resume_evt.wait(timeout=0.2)
        return self._stop_all or self._stop_stage


# ══════════════════════════════════════════════════════════════════════════════
# Transcription worker
# ══════════════════════════════════════════════════════════════════════════════
class TranscribeWorker(QThread, _StageController):
    log      = Signal(str)
    progress = Signal(float)
    status   = Signal(str)
    done     = Signal()
    failed   = Signal(str)

    def __init__(self, params):
        super().__init__()
        self.p = params
        self._init_controller()

    def run(self):
        p = self.p
        try:
            from faster_whisper import WhisperModel
            model_path  = p["model_path"]
            needs_dl    = p["needs_dl"]
            online_name = p["online_name"]
            models_dir  = p["models_dir"]

            if needs_dl:
                dest = os.path.join(models_dir, f"faster-whisper-{online_name}")
                if os.path.isdir(dest):
                    ok, reason = verify_model_integrity(dest, online_name)
                    if ok:
                        self.log.emit(f"Found existing complete download at {dest}, reusing it.\n")
                        model_path, needs_dl = dest, False
                    else:
                        self.log.emit(f"Found incomplete/corrupt previous download "
                                      f"({reason}) - removing it before retrying.\n")
                        cleanup_incomplete_model(dest)

            if needs_dl:
                dest = os.path.join(models_dir, f"faster-whisper-{online_name}")
                self.log.emit(f"Downloading {online_name}  ->  {dest}\n")
                self.status.emit("Downloading...")

                old_stdout = sys.stdout
                old_stderr = sys.stderr
                sys.stdout = _StreamToSignal(self.log, old_stdout)
                sys.stderr = _StreamToSignal(self.log, old_stderr)

                dl_error = None
                try:
                    from huggingface_hub import snapshot_download
                    snapshot_download(repo_id=HF_REPOS[online_name], local_dir=dest)
                except Exception as ex:
                    dl_error = ex
                finally:
                    sys.stdout = old_stdout
                    sys.stderr = old_stderr

                if dl_error is not None:
                    self.log.emit(f"\n[ERROR] Download failed: {dl_error}\n")
                    self.log.emit("Removing incomplete download so the next attempt starts clean...\n")
                    cleanup_incomplete_model(dest)
                    raise RuntimeError(f"Model download failed: {dl_error}\n\n"
                                       "The incomplete download has been removed.")

                ok, reason = verify_model_integrity(dest, online_name)
                if not ok:
                    self.log.emit(f"\n[ERROR] Downloaded model failed verification: {reason}\n")
                    cleanup_incomplete_model(dest)
                    raise RuntimeError(f"Downloaded model failed verification: {reason}\n\n"
                                       "The incomplete/corrupt files have been removed.")

                self.progress.emit(1.0)
                model_path = dest
                self.log.emit("Download complete and verified.\n\n")

            self.log.emit("Loading model...\n")
            self.status.emit("Loading model...")
            device, compute_type, warning = detect_device()
            if warning:
                self.log.emit(f"[WARN] {warning}\n")
            try:
                model = WhisperModel(model_path, device=device, compute_type=compute_type)
            except Exception as ex:
                if device == "cuda":
                    self.log.emit(f"[WARN] GPU load failed ({ex}), falling back to CPU...\n")
                    model = WhisperModel(model_path, device="cpu", compute_type="int8")
                else:
                    raise
            self.log.emit("Model ready.\n\n")

            if self._stop_all:
                self.status.emit("Stopped")
                self.done.emit()
                return

            files = p["files"]
            total_files = len(files)
            for idx, (src, out_name) in enumerate(files, 1):
                if self._stop_all:
                    self.log.emit("\n[STOP ALL] Queue aborted - remaining files were not processed.\n")
                    break
                self._begin_stage()   # fresh stage: this file's transcription
                if total_files > 1:
                    self.log.emit(f"\n{'='*60}\nFile {idx}/{total_files}: {os.path.basename(src)}\n{'='*60}\n")
                    self.status.emit(f"Transcribing file {idx}/{total_files}...")
                else:
                    self.status.emit("Transcribing...")
                self._process_one_file(model, src, out_name, p)

            if self._stop_all:
                self.status.emit("Stopped")
            else:
                self.progress.emit(1.0)
                self.status.emit("Done")
            self.done.emit()

        except Exception as ex:
            import traceback
            self.log.emit(f"\n[ERROR]  {ex}\n{traceback.format_exc()}\n")
            self.status.emit("Error")
            self.failed.emit(str(ex))

    def _process_one_file(self, model, src, out_name, p):
        """Transcribe (and optionally translate) exactly one file.

        A Stop on this file's current stage never affects any other file,
        nor the other stage of this same file - it only cuts the current
        stage short while keeping whatever it already produced. Only
        Stop All prevents moving on to the next stage/file.
        """
        duration = 0
        try:
            import av
            with av.open(src) as c:
                duration = float(c.duration) / 1_000_000
        except Exception:
            duration = 0

        task = "translate" if p["use_wtr"] else "transcribe"
        segs_iter, info = model.transcribe(
            src, language=p["lang_code"], beam_size=5,
            vad_filter=p["use_vad"],
            condition_on_previous_text=not p["no_halluc"],
            task=task)
        self.log.emit(f"Language: {info.language}  ({info.language_probability:.0%})\n")
        if p["use_wtr"]:
            self.log.emit("Whisper built-in -> English\n")
        self.log.emit("\n")

        fmt = p["fmt"]
        op = out_orig(p["out_dir"], out_name, fmt)
        segments = []
        with open(op, "w", encoding="utf-8") as f:
            e = ext_of(fmt)
            if e == "vtt": f.write("WEBVTT\n\n")
            for i, seg in enumerate(segs_iter, 1):
                if self._checkpoint():
                    self.log.emit(f"\n[STOP] Transcription stopped - kept {len(segments)} segment(s).\n")
                    break
                segments.append(seg)
                if duration > 0:
                    pct = min(seg.end / duration, 1.0)
                    scale = 0.9 if (p["do_translate"] and not p["use_wtr"]) else 1.0
                    self.progress.emit(pct * scale)
                txt = seg.text.strip()
                if e == "srt":
                    f.write(f"{i}\n{srt_time(seg.start)} --> {srt_time(seg.end)}\n{txt}\n\n")
                elif e == "vtt":
                    f.write(f"{vtt_time(seg.start)} --> {vtt_time(seg.end)}\n{txt}\n\n")
                else:
                    f.write(txt + "\n")
                self.log.emit(f"[{seg.start:.1f}s->{seg.end:.1f}s]  {txt}\n")

        self.log.emit(f"\n[OK] Original -> {op}\n")

        if self._stop_all:
            return   # Stop All: do not start translation for this file

        if p["do_translate"] and not p["use_wtr"] and segments:
            self._begin_stage()   # fresh stage: this file's translation -
                                   # a stop from the transcription stage above
                                   # must not carry over and cut this short
            self.status.emit("Translating...")
            prompt = tgt_prompt(p["tgt"])
            texts = [s.text.strip() for s in segments]
            self.log.emit(f"\nTranslating {len(texts)} segments [{p['ollama']}] "
                          f"in batches...\n")
            translations, failed_n = [], 0
            for start, chunk_tr, chunk_failed in translate_segments(
                    p["ollama"], prompt, texts, self._checkpoint):
                translations.extend(chunk_tr)
                failed_n += sum(chunk_failed)
                pct = 0.9 + 0.1 * len(translations) / len(texts)
                self.progress.emit(pct)
                for j, tr in enumerate(chunk_tr):
                    tag = "  [WARN] failed, kept original -> " if chunk_failed[j] else "  "
                    self.log.emit(f"{tag}[{start+j+1}/{len(texts)}]  {tr}\n")
            if self._stop_stage or self._stop_all:
                self.log.emit(f"[STOP] Translation stopped - kept {len(translations)} segment(s).\n")
            if failed_n:
                self.log.emit(f"\n[WARN] {failed_n} segment(s) failed translation.\n")

            n = len(translations)
            if n > 0:
                done_segs = segments[:n]
                tp = out_trans(p["out_dir"], out_name, p["tgt"], fmt)
                write_segs(tp, fmt, done_segs, translations)
                self.log.emit(f"[OK] Translated ({n}) -> {tp}\n")
                if p["bilingual"]:
                    bp = out_bili(p["out_dir"], out_name, p["tgt"], fmt)
                    bili_texts = [f"{s.text.strip()}\n{translations[i]}"
                                  for i, s in enumerate(done_segs)]
                    write_segs(bp, fmt, done_segs, bili_texts)
                    self.log.emit(f"[OK] Bilingual -> {bp}\n")


# ══════════════════════════════════════════════════════════════════════════════
# Translation-only worker
# ══════════════════════════════════════════════════════════════════════════════
class TranslateWorker(QThread, _StageController):
    log      = Signal(str)
    progress = Signal(float)
    status   = Signal(str)
    done     = Signal()
    failed   = Signal(str)

    def __init__(self, params):
        super().__init__()
        self.p = params
        self._init_controller()

    def run(self):
        p = self.p
        try:
            files = p["files"]
            total_files = len(files)
            for idx, (src, out_name) in enumerate(files, 1):
                if self._stop_all:
                    self.log.emit("\n[STOP ALL] Queue aborted - remaining files were not processed.\n")
                    break
                self._begin_stage()   # fresh stage: this file's translation
                if total_files > 1:
                    self.log.emit(f"\n{'='*60}\nFile {idx}/{total_files}: {os.path.basename(src)}\n{'='*60}\n")
                    self.status.emit(f"Translating file {idx}/{total_files}...")
                else:
                    self.status.emit("Translating...")
                self._process_one_file(src, out_name, p, idx, total_files)

            if self._stop_all:
                self.status.emit("Stopped")
            else:
                self.progress.emit(1.0)
                self.status.emit("Done")
            self.done.emit()
        except Exception as ex:
            import traceback
            self.log.emit(f"\n[ERROR]  {ex}\n{traceback.format_exc()}\n")
            self.status.emit("Error")
            self.failed.emit(str(ex))

    def _process_one_file(self, src, out_name, p, idx, total_files):
        """Translate exactly one subtitle file.

        A Stop on this file's stage never affects any other file - it only
        cuts this file's translation short while keeping whatever it
        already produced. Only Stop All prevents moving on to the next
        file.
        """
        self.log.emit(f"Parsing {os.path.basename(src)}\n")
        try:
            segs = parse_sub(src)
        except Exception as ex:
            self.log.emit(f"[WARN] Skipping {os.path.basename(src)}: {ex}\n")
            return
        self.log.emit(f"{len(segs)} segments found.\n\n")
        prompt = tgt_prompt(p["tgt"])
        texts = [s.text for s in segs]

        translations, failed_n = [], 0
        for start, chunk_tr, chunk_failed in translate_segments(
                p["ollama"], prompt, texts, self._checkpoint):
            translations.extend(chunk_tr)
            failed_n += sum(chunk_failed)
            base  = (idx - 1) / total_files
            local = (len(translations) / len(texts)) if texts else 1.0
            self.progress.emit(base + local / total_files)
            for j, tr in enumerate(chunk_tr):
                tag = "[WARN] failed, kept original -> " if chunk_failed[j] else ""
                self.log.emit(f"{tag}[{start+j+1}/{len(texts)}]  {tr}\n")
        if self._stop_stage or self._stop_all:
            self.log.emit(f"[STOP] Translation stopped - kept {len(translations)} segment(s).\n")
        if failed_n:
            self.log.emit(f"\n[WARN] {failed_n} segment(s) failed.\n")

        n = len(translations)
        if n > 0:
            done_segs = segs[:n]
            op = out_trans(p["out_dir"], out_name, p["tgt"], p["fmt"])
            write_sub(op, p["fmt"], done_segs, translations, False)
            self.log.emit(f"\n[OK] Translated ({n}) -> {op}\n")
            if p["bilingual"]:
                bp = out_bili(p["out_dir"], out_name, p["tgt"], p["fmt"])
                write_sub(bp, p["fmt"], done_segs, translations, True)
                self.log.emit(f"[OK] Bilingual -> {bp}\n")
