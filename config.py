"""
config.py – Persistent configuration: defaults, load, save.
"""
import os, json

SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(SCRIPT_DIR, "config.json")

DEFAULT_CONFIG = {
    "window_geometry": None,     # Qt saveGeometry() base64, or None for default
    "splitter_tr":     None,     # Transcribe QSplitter sizes [top, bottom]
    "splitter_tl":     None,     # Translate QSplitter sizes [top, bottom]
    "sidebar_width":   200,
    "skin":            "Fluent Glass",
    "bg_image":        "",
    "bg_opacity":       0.2,
    "lang":            None,
    "fmt":             ".srt",
    "vad":             True,
    "halluc":          True,
    "translate":       False,
    "bilingual":       False,
    "tgt_lang":        "English / English",
    "whisper_tr":      False,
    "samedir":         True,
    "t_bilingual":     False,
    "t_samedir":       True,
    "t_fmt":           ".srt",
    "lang_freq":       {},       # source language usage counts  {display_name: count}
    "tgt_lang_freq":   {},       # target language usage counts  {display_name: count}
}

def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, encoding="utf-8") as f:
                saved = json.load(f)
            if not isinstance(saved, dict):
                raise ValueError("config.json root must be an object")
            cfg = DEFAULT_CONFIG.copy()
            for k, default in DEFAULT_CONFIG.items():
                if k not in saved:
                    continue
                val = saved[k]
                if default is None:
                    cfg[k] = val
                elif isinstance(default, bool):
                    cfg[k] = bool(val)
                elif isinstance(default, int):
                    cfg[k] = int(val)
                elif isinstance(default, float):
                    cfg[k] = float(val)
                elif isinstance(default, str):
                    cfg[k] = str(val) if val is not None else None
                elif isinstance(default, dict):
                    cfg[k] = val if isinstance(val, dict) else {}
            return cfg
    except Exception:
        pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
