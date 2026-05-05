import os, sys, time, json, shutil, hashlib, asyncio, threading, httpx, aiosqlite, getpass, math, random, re, tempfile, base64, importlib, importlib.util, hmac, sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional, List, Tuple, Callable, Dict
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from llama_cpp import Llama

psutil: Any = None
qml: Any = None
pnp: Any = None
try:
    psutil = importlib.import_module("psutil")
except Exception:
    pass
try:
    qml = importlib.import_module("pennylane")
    pnp = importlib.import_module("pennylane.numpy")
except Exception:
    qml = None
    pnp = None

MODEL_REPO = "https://huggingface.co/tensorblock/llama3-small-GGUF/resolve/main/"
MODEL_FILE = "llama3-small-Q3_K_M.gguf"
MODELS_DIR = Path("models")
MODEL_PATH = MODELS_DIR / MODEL_FILE
ENCRYPTED_MODEL = MODEL_PATH.with_suffix(MODEL_PATH.suffix + ".aes")
DB_PATH = Path("chat_history.db.aes")
KEY_PATH = Path(".enc_key")
SELECTED_MODEL_PATH = Path(".selected_model")
MODEL_SELECTION_MODE_PATH = Path(".model_selection_mode")
SECURITY_SETTINGS_PATH = Path(".naza_security_settings.json")
COLORWHEEL_STATE_PATH = Path(".naza_colorwheel_state.json")
OQS_KEYPAIR_PATH = Path(".oqs_mlkem_keypair.json")
OQS_KEM_ALGORITHM = os.environ.get("NAZA_OQS_KEM", "ML-KEM-768")
OQS_MAGIC = b"NAZA-OQS-HYBRID-v1\n"
OQS_AAD_PREFIX = b"naza-oqs-hybrid-v1:"
AES_STREAM_MAGIC = b"NAZA-AES-GCM-STREAM-v1\n"
OQS_STREAM_MAGIC = b"NAZA-OQS-HYBRID-STREAM-v1\n"
GCM_NONCE_SIZE = 12
GCM_TAG_SIZE = 16
FILE_CRYPTO_CHUNK_SIZE = 8 * 1024 * 1024
MAX_STREAM_HEADER_SIZE = 1024 * 1024
SCANNER_METRIC_SAMPLES = 5
EXPECTED_HASH = "8e4f4856fb84bafb895f1eb08e6c03e4be613ead2d942f91561aeac742a619aa"
MODEL_PROFILES = [
    {"id": "llama3-small", "name": "Llama 3 Small GGUF", "repo": MODEL_REPO, "file": MODEL_FILE, "expected_hash": EXPECTED_HASH, "runtime": "llama_cpp"},
    {"id": "gemma4-e2b-litert", "name": "Gemma 4 E2B LiteRT-LM", "repo": "https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/main/", "file": "gemma-4-E2B-it.litertlm", "expected_hash": "ab7838cdfc8f77e54d8ca45eadceb20452d9f01e4bfade03e5dce27911b27e42", "runtime": "litert_lm"},
]
MODEL_RUNTIME_NAMES = {"llama_cpp": "llama.cpp", "litert_lm": "LiteRT-LM"}
DEFAULT_SECURITY_SETTINGS = {
    "disabled_model_ids": [],
    "defense_profile": "hardened",
    "defense_voting": True,
    "metric_samples": 7,
    "max_defense_passes": 5,
    "noise_width": 2,
    "jitter_scale": 1.2,
    "colorwheel_enabled": True,
    "colorwheel_spins": 96,
    "colorwheel_rings": 12,
    "ml_trace_scramble": True,
}
DEFENSE_PROFILE_PRESETS = {
    "standard": {"metric_samples": 5, "max_defense_passes": 3, "noise_width": 1, "jitter_scale": 0.8, "defense_voting": True, "colorwheel_spins": 48, "colorwheel_rings": 8, "ml_trace_scramble": True},
    "hardened": {"metric_samples": 7, "max_defense_passes": 5, "noise_width": 2, "jitter_scale": 1.2, "defense_voting": True, "colorwheel_spins": 96, "colorwheel_rings": 12, "ml_trace_scramble": True},
    "maximum": {"metric_samples": 9, "max_defense_passes": 5, "noise_width": 3, "jitter_scale": 1.6, "defense_voting": True, "colorwheel_spins": 144, "colorwheel_rings": 16, "ml_trace_scramble": True},
}
_APP_KEY: Optional[bytes] = None
_DB_SETTINGS_ACTIVE = False
_SECURITY_SETTINGS_CACHE: Optional[dict] = None
_SELECTED_MODEL_ID_CACHE: Optional[str] = None
_MODEL_SELECTION_MODE_CACHE: Optional[str] = None
_COLORWHEEL_STATE_CACHE: Optional[dict] = None
MODELS_DIR.mkdir(parents=True, exist_ok=True)

def constant_time_compare(left, right) -> bool:
    left_b = left if isinstance(left, bytes) else str(left).encode("utf-8", errors="ignore")
    right_b = right if isinstance(right, bytes) else str(right).encode("utf-8", errors="ignore")
    return hmac.compare_digest(left_b, right_b)

def model_by_id(model_id: str) -> dict:
    for profile in MODEL_PROFILES:
        if constant_time_compare(profile["id"], model_id):
            return profile
    return MODEL_PROFILES[0]

def model_path_for(profile: dict) -> Path:
    return MODELS_DIR / profile["file"]

def encrypted_model_path_for(profile: dict) -> Path:
    path = model_path_for(profile)
    return path.with_suffix(path.suffix + ".aes")

def model_runtime_name(profile: dict) -> str:
    runtime_id = str(profile.get("runtime", "unknown"))
    return MODEL_RUNTIME_NAMES.get(runtime_id, runtime_id)

def model_label(profile: dict) -> str:
    return f"{profile['name']} [{model_runtime_name(profile)}]"

def set_app_key(key: bytes) -> None:
    global _APP_KEY
    _APP_KEY = key

def _normalize_model_selection_mode(mode: Optional[str]) -> str:
    return "entropy" if str(mode or "entropy").strip().lower() == "entropy" else "fixed"

def _initial_colorwheel_state() -> dict:
    return {"digest": hashlib.sha3_256(os.urandom(32)).hexdigest(), "tick": 0, "wheel_index": 0}

def _read_selected_model_id_file() -> str:
    if SELECTED_MODEL_PATH.exists():
        try:
            return model_by_id(SELECTED_MODEL_PATH.read_text().strip())["id"]
        except Exception:
            pass
    return MODEL_PROFILES[0]["id"]

def _read_model_selection_mode_file() -> str:
    if MODEL_SELECTION_MODE_PATH.exists():
        try:
            return _normalize_model_selection_mode(MODEL_SELECTION_MODE_PATH.read_text())
        except Exception:
            pass
    return "entropy"

def _read_security_settings_file() -> dict:
    if SECURITY_SETTINGS_PATH.exists():
        try:
            return normalize_security_settings(json.loads(SECURITY_SETTINGS_PATH.read_text()))
        except Exception:
            pass
    return normalize_security_settings()

def _read_colorwheel_state_file() -> dict:
    if COLORWHEEL_STATE_PATH.exists():
        try:
            payload = json.loads(COLORWHEEL_STATE_PATH.read_text())
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return _initial_colorwheel_state()

def _legacy_settings_payload() -> Dict[str, object]:
    return {
        "security_settings": _read_security_settings_file(),
        "selected_model_id": _read_selected_model_id_file(),
        "model_selection_mode": _read_model_selection_mode_file(),
        "colorwheel_state": _read_colorwheel_state_file(),
    }

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _disabled_model_ids_from(settings: dict) -> List[str]:
    valid_ids = {str(profile["id"]) for profile in MODEL_PROFILES}
    disabled_raw = settings.get("disabled_model_ids", [])
    if not isinstance(disabled_raw, list):
        return []
    return [model_id for model_id in disabled_raw if isinstance(model_id, str) and model_id in valid_ids]

def normalize_security_settings(raw: Optional[dict] = None) -> dict:
    settings = dict(DEFAULT_SECURITY_SETTINGS)
    if isinstance(raw, dict):
        settings.update(raw)
    disabled = _disabled_model_ids_from(settings)
    if len(disabled) >= len(MODEL_PROFILES):
        disabled = disabled[:-1]
    settings["disabled_model_ids"] = disabled
    profile_name = str(settings.get("defense_profile", "hardened")).lower()
    settings["defense_profile"] = profile_name if profile_name in DEFENSE_PROFILE_PRESETS else "hardened"
    settings["defense_voting"] = bool(settings.get("defense_voting", True))
    settings["metric_samples"] = max(3, min(13, _safe_int(settings.get("metric_samples"), 7)))
    settings["max_defense_passes"] = max(1, min(5, _safe_int(settings.get("max_defense_passes"), 5)))
    settings["noise_width"] = max(1, min(4, _safe_int(settings.get("noise_width"), 2)))
    settings["jitter_scale"] = max(0.5, min(2.0, _safe_float(settings.get("jitter_scale"), 1.2)))
    settings["colorwheel_enabled"] = bool(settings.get("colorwheel_enabled", True))
    settings["colorwheel_spins"] = max(16, min(256, _safe_int(settings.get("colorwheel_spins"), 96)))
    settings["colorwheel_rings"] = max(6, min(24, _safe_int(settings.get("colorwheel_rings"), 12)))
    settings["ml_trace_scramble"] = bool(settings.get("ml_trace_scramble", True))
    return settings

def _ensure_settings_schema_sync(conn) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, prompt TEXT, response TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")

def _decode_setting_value(raw: str):
    try:
        return json.loads(raw)
    except Exception:
        return raw

def _apply_settings_rows(rows: Dict[str, str]) -> None:
    global _SECURITY_SETTINGS_CACHE, _SELECTED_MODEL_ID_CACHE, _MODEL_SELECTION_MODE_CACHE, _COLORWHEEL_STATE_CACHE
    legacy = _legacy_settings_payload()
    security = _decode_setting_value(rows["security_settings"]) if "security_settings" in rows else legacy["security_settings"]
    selected_id = _decode_setting_value(rows["selected_model_id"]) if "selected_model_id" in rows else legacy["selected_model_id"]
    mode = _decode_setting_value(rows["model_selection_mode"]) if "model_selection_mode" in rows else legacy["model_selection_mode"]
    colorwheel = _decode_setting_value(rows["colorwheel_state"]) if "colorwheel_state" in rows else legacy["colorwheel_state"]
    _SECURITY_SETTINGS_CACHE = normalize_security_settings(security if isinstance(security, dict) else None)
    _SELECTED_MODEL_ID_CACHE = model_by_id(str(selected_id))["id"]
    _MODEL_SELECTION_MODE_CACHE = _normalize_model_selection_mode(str(mode))
    _COLORWHEEL_STATE_CACHE = colorwheel if isinstance(colorwheel, dict) else _initial_colorwheel_state()

def _decrypt_db_to_path(key: bytes, dest: Path) -> None:
    global _DB_SETTINGS_ACTIVE
    _DB_SETTINGS_ACTIVE = True
    try:
        if DB_PATH.exists():
            dest.write_bytes(aes_decrypt(DB_PATH.read_bytes(), key))
    finally:
        _DB_SETTINGS_ACTIVE = False

def _encrypt_db_from_path(key: bytes, src: Path) -> None:
    global _DB_SETTINGS_ACTIVE
    _DB_SETTINGS_ACTIVE = True
    try:
        DB_PATH.write_bytes(aes_encrypt(src.read_bytes(), key))
    finally:
        _DB_SETTINGS_ACTIVE = False

def _load_settings_from_encrypted_db(key: bytes) -> bool:
    if not DB_PATH.exists():
        return False
    dec = allocate_temp_db_path()
    try:
        _decrypt_db_to_path(key, dec)
        with sqlite3.connect(dec) as conn:
            try:
                rows = dict(conn.execute("SELECT key, value FROM app_settings").fetchall())
            except sqlite3.OperationalError:
                return False
        _apply_settings_rows(rows)
        return True
    except Exception:
        return False
    finally:
        safe_cleanup([dec])

def _write_settings_to_encrypted_db(updates: Dict[str, object]) -> None:
    if _APP_KEY is None:
        return
    dec = allocate_temp_db_path()
    try:
        _decrypt_db_to_path(_APP_KEY, dec)
        with sqlite3.connect(dec) as conn:
            _ensure_settings_schema_sync(conn)
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            for key, value in updates.items():
                conn.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(value, sort_keys=True), now),
                )
            conn.commit()
        _encrypt_db_from_path(_APP_KEY, dec)
    finally:
        safe_cleanup([dec])

def read_selected_model_profile() -> dict:
    if _SELECTED_MODEL_ID_CACHE is None and _APP_KEY is not None and not _DB_SETTINGS_ACTIVE:
        _load_settings_from_encrypted_db(_APP_KEY)
    return model_by_id(_SELECTED_MODEL_ID_CACHE or _read_selected_model_id_file())

def write_selected_model_profile(profile: dict) -> None:
    global _SELECTED_MODEL_ID_CACHE
    _SELECTED_MODEL_ID_CACHE = model_by_id(profile["id"])["id"]
    _write_settings_to_encrypted_db({"selected_model_id": _SELECTED_MODEL_ID_CACHE})

def read_model_selection_mode() -> str:
    if _MODEL_SELECTION_MODE_CACHE is None and _APP_KEY is not None and not _DB_SETTINGS_ACTIVE:
        _load_settings_from_encrypted_db(_APP_KEY)
    return _MODEL_SELECTION_MODE_CACHE or _read_model_selection_mode_file()

def write_model_selection_mode(mode: str) -> None:
    global _MODEL_SELECTION_MODE_CACHE
    _MODEL_SELECTION_MODE_CACHE = _normalize_model_selection_mode(mode)
    _write_settings_to_encrypted_db({"model_selection_mode": _MODEL_SELECTION_MODE_CACHE})

def read_security_settings() -> dict:
    if _SECURITY_SETTINGS_CACHE is None and _APP_KEY is not None and not _DB_SETTINGS_ACTIVE:
        _load_settings_from_encrypted_db(_APP_KEY)
    return normalize_security_settings(_SECURITY_SETTINGS_CACHE or _read_security_settings_file())

def write_security_settings(settings: dict) -> None:
    global _SECURITY_SETTINGS_CACHE
    _SECURITY_SETTINGS_CACHE = normalize_security_settings(settings)
    _write_settings_to_encrypted_db({"security_settings": _SECURITY_SETTINGS_CACHE})

def is_model_enabled(profile: dict, settings: Optional[dict] = None) -> bool:
    settings = settings or read_security_settings()
    return str(profile["id"]) not in _disabled_model_ids_from(settings)

def enabled_model_profiles(settings: Optional[dict] = None) -> List[dict]:
    settings = settings or read_security_settings()
    enabled = [profile for profile in MODEL_PROFILES if is_model_enabled(profile, settings)]
    return enabled or [MODEL_PROFILES[0]]

def first_enabled_model_profile(settings: Optional[dict] = None) -> dict:
    return enabled_model_profiles(settings)[0]

def encrypted_model_profiles(include_disabled: bool = False) -> List[dict]:
    settings = read_security_settings()
    profiles = MODEL_PROFILES if include_disabled else enabled_model_profiles(settings)
    return [profile for profile in profiles if encrypted_model_path_for(profile).exists()]

def _rgb_from_wheel(index: int, rings: int) -> Tuple[int, int, int]:
    angle = (index % max(1, rings)) / float(max(1, rings)) * math.tau
    return (
        int((math.sin(angle) * 0.5 + 0.5) * 255),
        int((math.sin(angle + math.tau / 3.0) * 0.5 + 0.5) * 255),
        int((math.sin(angle + math.tau * 2.0 / 3.0) * 0.5 + 0.5) * 255),
    )

def _ansi_rgb(text: str, rgb: Tuple[int, int, int]) -> str:
    r, g, b = rgb
    return f"\x1b[38;2;{r};{g};{b}m{text}\x1b[0m"

def read_colorwheel_state() -> dict:
    if _COLORWHEEL_STATE_CACHE is None and _APP_KEY is not None and not _DB_SETTINGS_ACTIVE:
        _load_settings_from_encrypted_db(_APP_KEY)
    return dict(_COLORWHEEL_STATE_CACHE or _read_colorwheel_state_file())

def write_colorwheel_state(state: dict) -> None:
    global _COLORWHEEL_STATE_CACHE
    _COLORWHEEL_STATE_CACHE = dict(state)
    _write_settings_to_encrypted_db({"colorwheel_state": _COLORWHEEL_STATE_CACHE})

def colorwheel_entropy_state(purpose: str, context: Optional[dict] = None, spins: Optional[int] = None, persist: bool = True) -> dict:
    settings = read_security_settings()
    rings = _safe_int(settings.get("colorwheel_rings"), 12)
    spin_count = int(spins) if spins is not None else _safe_int(settings.get("colorwheel_spins"), 96)
    previous = read_colorwheel_state()
    base = {
        "purpose": purpose,
        "context": context or {},
        "previous": previous.get("digest", ""),
        "tick": _safe_int(previous.get("tick"), 0),
        "pid": os.getpid(),
        "thread": threading.get_ident(),
        "time_ns": time.time_ns(),
        "nonce": base64.b64encode(os.urandom(32)).decode("ascii"),
    }
    digest = hashlib.sha3_512(json.dumps(base, sort_keys=True, default=str).encode("utf-8")).digest()
    trace = []
    for spin in range(max(1, spin_count)):
        start = time.perf_counter_ns()
        rgb = _rgb_from_wheel(digest[spin % len(digest)] + spin + _safe_int(previous.get("wheel_index"), 0), rings)
        timing = time.perf_counter_ns() - start
        digest = hashlib.blake2b(digest + bytes(rgb) + timing.to_bytes(8, "big", signed=False) + os.urandom(4) + spin.to_bytes(2, "big", signed=False), digest_size=64).digest()
        if spin % max(1, spin_count // 8) == 0:
            trace.append({"i": spin, "rgb": rgb, "n": digest[0]})
    index = int.from_bytes(digest[:4], "big") % rings
    rgb = _rgb_from_wheel(index, rings)
    state = {
        "digest": hashlib.sha3_256(digest).hexdigest(),
        "tick": _safe_int(previous.get("tick"), 0) + 1,
        "wheel_index": index,
        "angle_deg": round(360.0 * index / float(rings), 2),
        "rgb": list(rgb),
        "rings": rings,
        "spins": spin_count,
        "trace_digest": hashlib.blake2s(json.dumps(trace, sort_keys=True).encode("utf-8"), digest_size=12).hexdigest(),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if persist:
        write_colorwheel_state(state)
    return state

def colorwheel_entropy_bytes(purpose: str, context: Optional[dict] = None, length: int = 32) -> bytes:
    settings = read_security_settings()
    if not settings.get("colorwheel_enabled", True):
        return os.urandom(length)
    state = colorwheel_entropy_state(purpose, context=context, persist=True)
    material = bytes.fromhex(state["digest"]) + bytes(state["rgb"]) + os.urandom(16)
    out = b""
    counter = 0
    while len(out) < length:
        out += hashlib.sha3_512(material + counter.to_bytes(4, "big")).digest()
        counter += 1
    return out[:length]

def colorwheel_marker(purpose: str, context: Optional[dict] = None) -> str:
    settings = read_security_settings()
    if not settings.get("colorwheel_enabled", True):
        return "colorwheel=disabled"
    state = colorwheel_entropy_state(purpose, context=context, persist=True)
    return "colorwheel=index:{idx},angle:{angle},rgb:{rgb},trace:{trace}".format(
        idx=state["wheel_index"],
        angle=state["angle_deg"],
        rgb="-".join(str(v) for v in state["rgb"]),
        trace=state["trace_digest"],
    )

def trace_scramble_delay(purpose: str, context: Optional[dict] = None) -> None:
    settings = read_security_settings()
    if not settings.get("ml_trace_scramble", True):
        return
    seed = colorwheel_entropy_bytes("trace-scramble:" + purpose, context=context, length=16)
    delay = 0.001 + (int.from_bytes(seed[:2], "big") / 65535.0) * _safe_float(settings.get("jitter_scale"), 1.0) * 0.045
    acc = int.from_bytes(seed[2:10], "big")
    for idx in range(64 + seed[10] % 192):
        acc ^= int((math.sin((acc + idx) % 313) + 1.0) * 1000000)
    time.sleep(delay)
    if acc == -1:
        print("", end="")

def render_colorwheel_spinner(label: str = "Colorwheel entropy", frames: int = 18) -> str:
    settings = read_security_settings()
    if not settings.get("colorwheel_enabled", True):
        return "colorwheel=disabled"
    state = read_colorwheel_state()
    rings = _safe_int(settings.get("colorwheel_rings"), 12)
    glyphs = ["|", "/", "-", "\\"]
    for frame in range(max(1, frames)):
        idx = (_safe_int(state.get("wheel_index"), 0) + frame) % rings
        rgb = _rgb_from_wheel(idx, rings)
        sys.stdout.write("\r" + _ansi_rgb(f"{glyphs[frame % len(glyphs)]} {label} ring={idx:02d}", rgb))
        sys.stdout.flush()
        trace_scramble_delay("visible-spinner", {"frame": frame, "ring": idx})
    marker = colorwheel_marker("visible-spinner-final", {"label": label})
    sys.stdout.write("\r" + " " * (len(label) + 32) + "\r")
    sys.stdout.flush()
    return marker

def entropy_select_model_profile(state: Optional[dict] = None, purpose: str = "scan") -> dict:
    settings = state.get("security_settings", read_security_settings()) if state else read_security_settings()
    mode = state.get("model_selection_mode", read_model_selection_mode()) if state else read_model_selection_mode()
    selected = state.get("selected_model", read_selected_model_profile()) if state else read_selected_model_profile()
    if not is_model_enabled(selected, settings):
        selected = first_enabled_model_profile(settings)
    if mode != "entropy":
        return selected
    available = encrypted_model_profiles()
    if not available:
        return selected
    entropy = os.urandom(32) + time.time_ns().to_bytes(8, "big", signed=False) + purpose.encode("utf-8")
    entropy += colorwheel_entropy_bytes("model-select:" + purpose, {"available": [p["id"] for p in available]}, length=32)
    if psutil is not None:
        try:
            entropy += json.dumps(collect_system_metrics(), sort_keys=True).encode("utf-8")
        except Exception:
            pass
    digest = hashlib.sha256(entropy).digest()
    return available[int.from_bytes(digest[:8], "big") % len(available)]


CSI = "\x1b["
def clear_screen():
    sys.stdout.write(CSI + "2J" + CSI + "H")
    sys.stdout.flush()
def show_cursor(): sys.stdout.write(CSI + "?25h")
def color(text, fg=None, bold=False):
    codes=[]
    if fg: codes.append(str(fg))
    if bold: codes.append('1')
    if not codes: return text
    return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"

ASCII_ART = {
    "main": [
        r". _   _    _    ______    _    ",
        r".| \ | |  / \  |___  /   / \   ",
        r".|  \| | / _ \    / /   / _ \  ",
        r".| |\  |/ ___ \  / /   / ___ \ ",
        "|_| \\_/_/   \\_/___/_/ / \\_\\\\",
    ],
    "model": [
        r" __  __  ___  ____  _____ _     ",
        r"|  \/  |/ _ \|  _ \| ____| |    ",
        r"| |\/| | | | | | | |  _| | |    ",
        r"| |  | | |_| | |_| | |___| |___ ",
        r"|_|  |_|\___/|____/|_____|_____|",
    ],
    "chat": [
        r"  ____ _   _    _  _____ ",
        r" / ___| | | |  / \|_   _|",
        r"| |   | |_| | / _ \ | |  ",
        r"| |___|  _  |/ ___ \| |  ",
        r" \____|_| |_/_/   \_\_|  ",
    ],
    "scan": [
        r" ____   ____    _    _   _ ",
        r"/ ___| / ___|  / \  | \ | |",
        r"\___ \| |     / _ \ |  \| |",
        r" ___) | |___ / ___ \| |\  |",
        r"|____/ \____/_/   \_\_| \_|",
    ],
    "history": [
        r" _   _ ___ ____ _____ ___  ______   __",
        r"| | | |_ _/ ___|_   _/ _ \|  _ \ \ / /",
        r"| |_| || |\___ \ | || | | | |_) \ V / ",
        r"|  _  || | ___) || || |_| |  _ < | |  ",
        r"|_| |_|___|____/ |_| \___/|_| \_\|_|  ",
    ],
    "rekey": [
        r" ____  _____ _  _________   __",
        r"|  _ \| ____| |/ / ____\ \ / /",
        r"| |_) |  _| | ' /|  _|  \ V / ",
        r"|  _ <| |___| . \| |___  | |  ",
        r"|_| \_\_____|_|\_\_____| |_|  ",
    ],
}

def boxed(title: str, lines: List[str], width: int = 72):
    top = "┌" + "─"*(width-2) + "┐"
    bot = "└" + "─"*(width-2) + "┘"
    title_line = f"│ {color(title, fg=36, bold=True):{width-4}} │"
    body=[]
    for l in lines:
        if len(l) > width-4:
            chunks = [l[i:i+width-4] for i in range(0,len(l),width-4)]
        else:
            chunks=[l]
        for c in chunks:
            body.append(f"│ {c:{width-4}} │")
    return "\n".join([top, title_line] + body + [bot])

def flush_stdin_buffer():
    try:
        import termios
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
        return
    except Exception:
        pass
    try:
        import select
        fd = sys.stdin.fileno()
        while True:
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if not ready:
                break
            if not os.read(fd, 1024):
                break
    except Exception:
        pass

def terminal_width(default: int = 88) -> int:
    try:
        return max(72, shutil.get_terminal_size((default, 24)).columns)
    except Exception:
        return default

def center_line(text: str, width: int) -> str:
    visible = len(re.sub(r"\x1b\[[0-9;]*m", "", text))
    pad = max(0, (width - visible) // 2)
    return " " * pad + text

def screen_banner(kind: str, title: str, subtitle: Optional[str] = None):
    width = terminal_width()
    art = ASCII_ART.get(kind, ASCII_ART["main"])
    print(color("═" * width, fg=36, bold=True))
    for line in art:
        print(center_line(color(line, fg=36, bold=True), width))
    print(center_line(color(title, fg=37, bold=True), width))
    if subtitle:
        print(center_line(color(subtitle, fg=90), width))
    print(color("═" * width, fg=36, bold=True))

def render_screen(state: Optional[dict], kind: str, title: str, subtitle: Optional[str] = None, panel_title: Optional[str] = None, panel_lines: Optional[List[str]] = None):
    clear_screen()
    if state is not None:
        header(state)
        print()
    if kind == "main":
        screen_banner(kind, title, subtitle)
    else:
        print(color(title.center(terminal_width()), fg=36, bold=True))
        if subtitle:
            print(color(subtitle.center(terminal_width()), fg=90))
        print(color("─" * terminal_width(), fg=36))
    if panel_title and panel_lines is not None:
        print(boxed(panel_title, panel_lines, width=min(terminal_width(), 88)))

def getch():
    try:
        import tty, termios, select
    except Exception:
        return sys.stdin.read(1).encode()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        first = os.read(fd, 1)
        if not first:
            return b""
        if first == b"\x1b":
            seq = bytearray(first)
            for _ in range(5):
                ready, _, _ = select.select([sys.stdin], [], [], 0.03)
                if not ready:
                    break
                chunk = os.read(fd, 1)
                if not chunk:
                    break
                seq.extend(chunk)
            return bytes(seq)
        return first
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)

def key_name(ch: bytes) -> str:
    if ch in (b"\r", b"\n", b"\x0d"):
        return "enter"
    if ch in (b"\x1b[A", b"\x1bOA", b"k"):
        return "up"
    if ch in (b"\x1b[B", b"\x1bOB", b"j"):
        return "down"
    if ch in (b"\x1b[C", b"\x1bOC", b"l"):
        return "right"
    if ch in (b"\x1b[D", b"\x1bOD", b"h"):
        return "left"
    if ch in (b"\x1b", b"q", b"Q"):
        return "escape"
    return "other"

def menu_lines(options: List[str], selected_idx: int, footer: Optional[List[str]] = None, header: Optional[List[str]] = None) -> List[str]:
    lines = []
    if header:
        lines.extend(header)
        lines.append("")
    for i, opt in enumerate(options):
        prefix = color("›", fg=36, bold=True) if i == selected_idx else " "
        lines.append(f"{prefix} {i+1}) {opt}")
    if footer:
        lines.append("")
        lines.extend(footer)
    return lines

def choose_menu(
    title: str,
    options: List[str],
    status: Optional[dict] = None,
    footer: Optional[List[str]] = None,
    default_idx: int = 0,
    header: Optional[List[str]] = None,
    select_keys: Optional[set] = None,
) -> int:
    idx = max(0, min(default_idx, len(options) - 1))
    select_keys = select_keys or set()
    flush_stdin_buffer()
    while True:
        render_screen(status, "plain", title, "Arrow keys, number shortcuts, and clean focus-safe input.", title, menu_lines(options, idx, footer, header))
        ch = getch()
        name = key_name(ch)
        if name == "up":
            idx = (idx - 1) % len(options)
        elif name == "down":
            idx = (idx + 1) % len(options)
        elif name == "enter":
            flush_stdin_buffer()
            return idx
        elif name == "other":
            try:
                raw = ch.decode(errors="ignore").strip()
                if raw in select_keys:
                    flush_stdin_buffer()
                    return idx
                if raw.isdigit():
                    choice = int(raw)
                    if 1 <= choice <= len(options):
                        flush_stdin_buffer()
                        return choice - 1
            except Exception:
                pass

def read_menu_choice(num_items:int, prompt="Use ↑↓ arrows or number, Enter to select: ")->int:
    print(prompt)
    flush_stdin_buffer()
    try:
        idx = 0
        while True:
            ch = getch()
            if not ch: continue
            name = key_name(ch)
            if name == "up":
                idx = (idx - 1) % num_items
            elif name == "down":
                idx = (idx + 1) % num_items
            elif name == "enter":
                flush_stdin_buffer()
                return idx
            else:
                try:
                    s = ch.decode(errors='ignore')
                    if s.strip().isdigit():
                        n = int(s.strip())
                        if 1 <= n <= num_items:
                            return n-1
                except Exception:
                    pass
            sys.stdout.write(f"\rSelected: {idx+1}/{num_items} ")
            sys.stdout.flush()
    except Exception:
        while True:
            s = input("Enter number: ").strip()
            if s.isdigit():
                n = int(s)
                if 1 <= n <= num_items:
                    return n-1

_OQS_MODULE = None
_OQS_IMPORT_ERROR = None

def side_channel_noise_jitter(max_ms: int = 25, min_rounds: int = 1, max_rounds: int = 4) -> None:
    settings = read_security_settings()
    jitter_scale = _safe_float(settings.get("jitter_scale"), 1.0)
    max_ms = max(1, int(max_ms * jitter_scale))
    max_rounds = max(min_rounds, int(max_rounds * jitter_scale))
    rounds = min_rounds + int.from_bytes(os.urandom(1), "big") % max(1, max_rounds - min_rounds + 1)
    acc = 0
    for _ in range(rounds):
        block = os.urandom(96)
        digest = hashlib.sha3_256(block + acc.to_bytes(8, "big", signed=False)).digest()
        acc ^= int.from_bytes(digest[:8], "big")
        time.sleep((int.from_bytes(digest[8:10], "big") / 65535.0) * max_ms / 1000.0)
    if acc == -1:
        print("", end="")

def start_noise_threads(width: int = 2):
    stop_event = threading.Event()
    def noise_worker():
        acc = 0
        while not stop_event.is_set():
            payload = os.urandom(128) + acc.to_bytes(8, "big", signed=False)
            acc ^= int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest(), "big")
            for i in range(64):
                acc ^= int((math.sin((acc + i) % 97) + 1.0) * 1000.0)
            stop_event.wait(0.001 + (acc % 7) / 1000.0)
    threads = [threading.Thread(target=noise_worker, daemon=True) for _ in range(max(1, width))]
    for thread in threads:
        thread.start()
    return stop_event, threads

def stop_noise_threads(stop_event, threads) -> None:
    stop_event.set()
    for thread in threads:
        thread.join(timeout=0.05)

def run_with_side_channel_noise(fn, *args, **kwargs):
    settings = read_security_settings()
    stop_event, threads = start_noise_threads(width=_safe_int(settings.get("noise_width"), 2))
    try:
        trace_scramble_delay("pre-critical-section", {"fn": getattr(fn, "__name__", "call")})
        side_channel_noise_jitter(35, 2, 5)
        return fn(*args, **kwargs)
    finally:
        side_channel_noise_jitter(20, 1, 3)
        trace_scramble_delay("post-critical-section", {"fn": getattr(fn, "__name__", "call")})
        stop_noise_threads(stop_event, threads)

def oqs_python_available() -> bool:
    return importlib.util.find_spec("oqs") is not None

def _get_oqs_module():
    global _OQS_MODULE, _OQS_IMPORT_ERROR
    if _OQS_MODULE is not None:
        return _OQS_MODULE
    if not oqs_python_available():
        _OQS_IMPORT_ERROR = "liboqs-python is not installed"
        return None
    try:
        import oqs as oqs_mod
        _OQS_MODULE = oqs_mod
        _OQS_IMPORT_ERROR = None
        return _OQS_MODULE
    except Exception as exc:
        _OQS_IMPORT_ERROR = str(exc)
        return None

def oqs_crypto_status() -> str:
    if not oqs_python_available():
        return "AES-256-GCM"
    if _OQS_IMPORT_ERROR:
        return "AES-256-GCM"
    return f"AES-256-GCM+OQS({OQS_KEM_ALGORITHM})"

def _b64e(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")

def _b64d(data: str) -> bytes:
    return base64.b64decode(data.encode("ascii"))

def _aes_gcm_encrypt(data: bytes, key: bytes, aad: Optional[bytes] = None) -> bytes:
    aes = AESGCM(key)
    nonce = os.urandom(12)
    return nonce + aes.encrypt(nonce, data, aad)

def _aes_gcm_decrypt(data: bytes, key: bytes, aad: Optional[bytes] = None) -> bytes:
    aes = AESGCM(key)
    nonce, ct = data[:12], data[12:]
    return aes.decrypt(nonce, ct, aad)

def _derive_oqs_file_key(key: bytes, shared_secret: bytes, salt: bytes, kem_alg: str) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        info=f"naza-file-hybrid:{kem_alg}".encode("utf-8"),
    )
    return hkdf.derive(key + shared_secret)

def _select_oqs_kem_algorithm(oqs_mod) -> Optional[str]:
    preferred = [OQS_KEM_ALGORITHM, "ML-KEM-768", "ML-KEM-1024", "ML-KEM-512", "Kyber768", "Kyber1024", "Kyber512"]
    deduped = []
    for alg in preferred:
        if alg and alg not in deduped:
            deduped.append(alg)
    try:
        enabled = set(oqs_mod.get_enabled_kem_mechanisms())
    except Exception:
        enabled = set()
    for alg in deduped:
        if enabled and alg not in enabled:
            continue
        try:
            with oqs_mod.KeyEncapsulation(alg):
                return alg
        except Exception:
            continue
    return None

def _load_or_create_oqs_keypair(key: bytes, create: bool = True) -> Optional[Tuple[str, bytes, bytes]]:
    oqs_mod = _get_oqs_module()
    if oqs_mod is None:
        return None

    if OQS_KEYPAIR_PATH.exists():
        try:
            payload = json.loads(OQS_KEYPAIR_PATH.read_text())
            alg = payload["kem_alg"]
            public_key = _b64d(payload["public_key"])
            wrapped_secret = _b64d(payload["secret_key_wrapped"])
            secret_key = _aes_gcm_decrypt(wrapped_secret, key, b"naza-oqs-keypair-v1")
            return alg, public_key, secret_key
        except Exception:
            if not create:
                return None

    if not create:
        return None

    alg = _select_oqs_kem_algorithm(oqs_mod)
    if alg is None:
        return None
    with oqs_mod.KeyEncapsulation(alg) as kem:
        public_key = kem.generate_keypair()
        secret_key = kem.export_secret_key()
    payload = {
        "version": 1,
        "kem_alg": alg,
        "public_key": _b64e(public_key),
        "secret_key_wrapped": _b64e(_aes_gcm_encrypt(secret_key, key, b"naza-oqs-keypair-v1")),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    OQS_KEYPAIR_PATH.write_text(json.dumps(payload, indent=2))
    try:
        OQS_KEYPAIR_PATH.chmod(0o600)
    except Exception:
        pass
    return alg, public_key, secret_key

def _oqs_hybrid_encrypt(data: bytes, key: bytes) -> Optional[bytes]:
    keypair = _load_or_create_oqs_keypair(key, create=True)
    oqs_mod = _get_oqs_module()
    if keypair is None or oqs_mod is None:
        return None
    kem_alg, public_key, _secret_key = keypair
    try:
        with oqs_mod.KeyEncapsulation(kem_alg) as kem:
            kem_ct, shared_secret = kem.encap_secret(public_key)
        salt = os.urandom(16)
        file_key = _derive_oqs_file_key(key, shared_secret, salt, kem_alg)
        header = json.dumps(
            {"v": 1, "kem_alg": kem_alg, "kem_ct": _b64e(kem_ct), "salt": _b64e(salt)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        nonce = os.urandom(12)
        aad = OQS_AAD_PREFIX + header
        ct = AESGCM(file_key).encrypt(nonce, data, aad)
        return OQS_MAGIC + len(header).to_bytes(4, "big") + header + nonce + ct
    except Exception:
        return None

def _oqs_hybrid_decrypt(data: bytes, key: bytes) -> bytes:
    oqs_mod = _get_oqs_module()
    if oqs_mod is None:
        raise RuntimeError(f"OQS payload requires liboqs-python: {_OQS_IMPORT_ERROR}")
    offset = len(OQS_MAGIC)
    header_len = int.from_bytes(data[offset:offset + 4], "big")
    offset += 4
    header = data[offset:offset + header_len]
    offset += header_len
    meta = json.loads(header.decode("utf-8"))
    keypair = _load_or_create_oqs_keypair(key, create=False)
    if keypair is None:
        raise RuntimeError("OQS keypair is missing or cannot be unlocked with the current key")
    kem_alg, _public_key, secret_key = keypair
    if kem_alg != meta["kem_alg"]:
        raise RuntimeError(f"OQS keypair algorithm mismatch: have {kem_alg}, need {meta['kem_alg']}")
    with oqs_mod.KeyEncapsulation(kem_alg, secret_key) as kem:
        shared_secret = kem.decap_secret(_b64d(meta["kem_ct"]))
    file_key = _derive_oqs_file_key(key, shared_secret, _b64d(meta["salt"]), kem_alg)
    nonce, ct = data[offset:offset + 12], data[offset + 12:]
    return AESGCM(file_key).decrypt(nonce, ct, OQS_AAD_PREFIX + header)

def aes_encrypt(data: bytes, key: bytes) -> bytes:
    side_channel_noise_jitter(18, 1, 3)
    try:
        enc = _oqs_hybrid_encrypt(data, key)
        if enc is not None:
            return enc
        return _aes_gcm_encrypt(data, key)
    finally:
        side_channel_noise_jitter(12, 1, 2)

def aes_decrypt(data: bytes, key: bytes) -> bytes:
    side_channel_noise_jitter(18, 1, 3)
    try:
        if data.startswith(AES_STREAM_MAGIC) or data.startswith(OQS_STREAM_MAGIC):
            raise ValueError("Streaming encrypted payloads must be decrypted with decrypt_file().")
        if data.startswith(OQS_MAGIC):
            return _oqs_hybrid_decrypt(data, key)
        return _aes_gcm_decrypt(data, key)
    finally:
        side_channel_noise_jitter(12, 1, 2)

def _atomic_temp_path(dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    for idx in range(1000):
        candidate = dest.with_name(f"{dest.name}.tmp.{os.getpid()}.{idx}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate temporary output path for {dest}")

def _cleanup_temp(path: Optional[Path]) -> None:
    if path is None:
        return
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass

def _print_stream_progress(label: str, done: int, total: int, last: float) -> float:
    now = time.time()
    if total <= 0:
        return now
    if done < total and now - last < 0.5:
        return last
    pct = done / total * 100.0
    sys.stdout.write(f"\r{label}: {pct:5.1f}% ({done // (1024 * 1024)}MB/{total // (1024 * 1024)}MB)")
    sys.stdout.flush()
    return now

def _finish_stream_progress(total: int) -> None:
    if total > 0:
        print()

def _oqs_hybrid_stream_material(key: bytes) -> Optional[Tuple[bytes, bytes]]:
    keypair = _load_or_create_oqs_keypair(key, create=True)
    oqs_mod = _get_oqs_module()
    if keypair is None or oqs_mod is None:
        return None
    kem_alg, public_key, _secret_key = keypair
    try:
        with oqs_mod.KeyEncapsulation(kem_alg) as kem:
            kem_ct, shared_secret = kem.encap_secret(public_key)
        salt = os.urandom(16)
        file_key = _derive_oqs_file_key(key, shared_secret, salt, kem_alg)
        header = json.dumps(
            {"v": 1, "kem_alg": kem_alg, "kem_ct": _b64e(kem_ct), "salt": _b64e(salt)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return file_key, header
    except Exception:
        return None

def _encrypt_stream_aes_gcm(src: Path, dest: Path, key: bytes, prefix: bytes, aad: bytes, label: str) -> int:
    total = src.stat().st_size
    nonce = os.urandom(GCM_NONCE_SIZE)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(aad)
    done = 0
    last = 0.0
    with src.open("rb") as fin, dest.open("wb") as fout:
        fout.write(prefix)
        fout.write(nonce)
        for chunk in iter(lambda: fin.read(FILE_CRYPTO_CHUNK_SIZE), b""):
            fout.write(encryptor.update(chunk))
            done += len(chunk)
            last = _print_stream_progress(label, done, total, last)
        final = encryptor.finalize()
        if final:
            fout.write(final)
        fout.write(encryptor.tag)
    _finish_stream_progress(total)
    return dest.stat().st_size

def _read_exact(handle, size: int) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError("Encrypted file is truncated or malformed.")
    return data

def _decrypt_stream_aes_gcm(src: Path, dest: Path, key: bytes, nonce: bytes, ciphertext_offset: int, tag: bytes, aad: bytes, label: str) -> int:
    total_size = src.stat().st_size
    ciphertext_len = total_size - ciphertext_offset - GCM_TAG_SIZE
    if ciphertext_len < 0:
        raise ValueError("Encrypted file is truncated or malformed.")
    decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
    decryptor.authenticate_additional_data(aad)
    remaining = ciphertext_len
    done = 0
    last = 0.0
    with src.open("rb") as fin, dest.open("wb") as fout:
        fin.seek(ciphertext_offset)
        while remaining:
            chunk = fin.read(min(FILE_CRYPTO_CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError("Encrypted file ended before ciphertext was complete.")
            fout.write(decryptor.update(chunk))
            remaining -= len(chunk)
            done += len(chunk)
            last = _print_stream_progress(label, done, ciphertext_len, last)
        final = decryptor.finalize()
        if final:
            fout.write(final)
    _finish_stream_progress(ciphertext_len)
    return dest.stat().st_size

def _read_stream_tag(src: Path) -> bytes:
    total_size = src.stat().st_size
    if total_size < GCM_TAG_SIZE:
        raise ValueError("Encrypted file is truncated or malformed.")
    with src.open("rb") as handle:
        handle.seek(total_size - GCM_TAG_SIZE)
        return _read_exact(handle, GCM_TAG_SIZE)

def _decrypt_aes_stream_file(src: Path, dest: Path, key: bytes) -> int:
    with src.open("rb") as handle:
        magic = _read_exact(handle, len(AES_STREAM_MAGIC))
        if magic != AES_STREAM_MAGIC:
            raise ValueError("Not an AES-GCM stream payload.")
        nonce = _read_exact(handle, GCM_NONCE_SIZE)
    ciphertext_offset = len(AES_STREAM_MAGIC) + GCM_NONCE_SIZE
    return _decrypt_stream_aes_gcm(src, dest, key, nonce, ciphertext_offset, _read_stream_tag(src), AES_STREAM_MAGIC, "Decrypting")

def _decrypt_oqs_stream_file(src: Path, dest: Path, key: bytes) -> int:
    with src.open("rb") as handle:
        magic = _read_exact(handle, len(OQS_STREAM_MAGIC))
        if magic != OQS_STREAM_MAGIC:
            raise ValueError("Not an OQS hybrid stream payload.")
        header_len = int.from_bytes(_read_exact(handle, 4), "big")
        if header_len <= 0 or header_len > MAX_STREAM_HEADER_SIZE:
            raise ValueError("Encrypted file has an invalid stream header.")
        header = _read_exact(handle, header_len)
        nonce = _read_exact(handle, GCM_NONCE_SIZE)
    meta = json.loads(header.decode("utf-8"))
    oqs_mod = _get_oqs_module()
    if oqs_mod is None:
        raise RuntimeError(f"OQS payload requires liboqs-python: {_OQS_IMPORT_ERROR}")
    keypair = _load_or_create_oqs_keypair(key, create=False)
    if keypair is None:
        raise RuntimeError("OQS keypair is missing or cannot be unlocked with the current key")
    kem_alg, _public_key, secret_key = keypair
    if kem_alg != meta["kem_alg"]:
        raise RuntimeError(f"OQS keypair algorithm mismatch: have {kem_alg}, need {meta['kem_alg']}")
    with oqs_mod.KeyEncapsulation(kem_alg, secret_key) as kem:
        shared_secret = kem.decap_secret(_b64d(meta["kem_ct"]))
    file_key = _derive_oqs_file_key(key, shared_secret, _b64d(meta["salt"]), kem_alg)
    ciphertext_offset = len(OQS_STREAM_MAGIC) + 4 + header_len + GCM_NONCE_SIZE
    return _decrypt_stream_aes_gcm(src, dest, file_key, nonce, ciphertext_offset, _read_stream_tag(src), OQS_AAD_PREFIX + header, "Decrypting")

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def get_or_create_key() -> bytes:
    if KEY_PATH.exists():
        d = KEY_PATH.read_bytes()
        if len(d) >= 48: return d[16:48]
        return d[:32]
    key = AESGCM.generate_key(256)
    KEY_PATH.write_bytes(key)
    print(f"🔑 New random key generated and saved to {KEY_PATH}")
    return key

def derive_key_from_passphrase(pw:str, salt:Optional[bytes]=None) -> Tuple[bytes, bytes]:
    if salt is None: salt = os.urandom(16)
    kdf_der = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=200_000)
    derived = kdf_der.derive(pw.encode("utf-8"))
    return salt, derived

def ensure_key_interactive() -> bytes:
    if KEY_PATH.exists():
        data = KEY_PATH.read_bytes()
        if len(data) >= 48: return data[16:48]
        if len(data) >= 32: return data[:32]
    print("Key not found. Create new key:")
    print("  1) Generate random key (saved raw)")
    print("  2) Derive from passphrase (salt+derived saved)")
    opt = input("Choose (1/2): ").strip()
    if opt == "2":
        pw = getpass.getpass("Enter passphrase: ")
        pw2 = getpass.getpass("Confirm: ")
        if pw != pw2:
            print("Passphrases mismatch. Aborting.")
            sys.exit(1)
        salt, key = derive_key_from_passphrase(pw)
        KEY_PATH.write_bytes(salt + key)
        print(f"Saved salt+derived key to {KEY_PATH}")
        return key
    else:
        key = AESGCM.generate_key(256)
        KEY_PATH.write_bytes(key)
        print(f"Saved random key to {KEY_PATH}")
        return key

def download_model_httpx(url: str, dest: Path, show_progress=True, timeout=None, expected_sha: Optional[str]=None):
    print(f"⬇️  Downloading model from {url}\nTo: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        h = hashlib.sha256()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(chunk_size=8192):
                if not chunk: break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if total and show_progress:
                    pct = done / total * 100
                    bar = int(pct // 2)
                    sys.stdout.write(f"\r[{('#'*bar).ljust(50)}] {pct:5.1f}% ({done//1024}KB/{total//1024}KB)")
                    sys.stdout.flush()
    if show_progress: print("\n✅ Download complete.")
    sha = h.hexdigest()
    print(f"SHA256: {sha}")
    if expected_sha:
        if sha.lower() == expected_sha.lower():
            print(color("SHA256 matches expected.", fg=32, bold=True))
        else:
            print(color(f"SHA256 MISMATCH! expected {expected_sha} got {sha}", fg=31, bold=True))
            keep_file = input("Hash mismatch. Keep this download anyway? (y/N): ").strip().lower() == "y"
            if not keep_file:
                try:
                    dest.unlink()
                except Exception:
                    pass
                raise ValueError("Download aborted because SHA256 verification failed.")
    return sha

def encrypt_file(src: Path, dest: Path, key: bytes):
    print(f"🔐 Encrypting {src} -> {dest}")
    start = time.time()
    tmp = _atomic_temp_path(dest)
    try:
        material = _oqs_hybrid_stream_material(key)
        if material is not None:
            file_key, header = material
            prefix = OQS_STREAM_MAGIC + len(header).to_bytes(4, "big") + header
            aad = OQS_AAD_PREFIX + header
            mode = "OQS hybrid stream"
        else:
            file_key = key
            prefix = AES_STREAM_MAGIC
            aad = AES_STREAM_MAGIC
            mode = "AES-GCM stream"
        encrypted_size = _encrypt_stream_aes_gcm(src, tmp, file_key, prefix, aad, "Encrypting")
        tmp.replace(dest)
        dur = time.time()-start
        print(f"✅ Encrypted ({encrypted_size} bytes) in {dur:.2f}s using {mode}")
    except Exception:
        _cleanup_temp(tmp)
        raise

def decrypt_file(src: Path, dest: Path, key: bytes):
    print(f"🔓 Decrypting {src} -> {dest}")
    start = time.time()
    tmp = _atomic_temp_path(dest)
    try:
        with src.open("rb") as handle:
            magic = handle.read(max(len(OQS_STREAM_MAGIC), len(AES_STREAM_MAGIC)))
        if magic.startswith(OQS_STREAM_MAGIC):
            mode = "OQS hybrid stream"
            plaintext_size = _decrypt_oqs_stream_file(src, tmp, key)
        elif magic.startswith(AES_STREAM_MAGIC):
            mode = "AES-GCM stream"
            plaintext_size = _decrypt_aes_stream_file(src, tmp, key)
        else:
            enc = src.read_bytes()
            mode = "OQS hybrid" if enc.startswith(OQS_MAGIC) else "AES-GCM"
            data = aes_decrypt(enc, key)
            tmp.write_bytes(data)
            plaintext_size = len(data)
        tmp.replace(dest)
        dur = time.time()-start
        print(f"✅ Decrypted ({plaintext_size} bytes) in {dur:.2f}s using {mode}")
    except Exception:
        _cleanup_temp(tmp)
        raise

async def init_db(key: bytes):
    set_app_key(key)
    temp_path = allocate_temp_db_path()
    try:
        _decrypt_db_to_path(key, temp_path)
        with sqlite3.connect(temp_path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, prompt TEXT, response TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
            now = time.strftime("%Y-%m-%d %H:%M:%S")
            for setting_key, setting_value in _legacy_settings_payload().items():
                db.execute(
                    "INSERT OR IGNORE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
                    (setting_key, json.dumps(setting_value, sort_keys=True), now),
                )
            db.commit()
            rows = dict(db.execute("SELECT key, value FROM app_settings").fetchall())
        _apply_settings_rows(rows)
        _encrypt_db_from_path(key, temp_path)
    finally:
        safe_cleanup([temp_path])

async def log_interaction(prompt: str, response: str, key: bytes):
    dec = allocate_temp_db_path()
    try:
        decrypt_file(DB_PATH, dec, key)
        async with aiosqlite.connect(dec) as db:
            await db.execute("INSERT INTO history (timestamp, prompt, response) VALUES (?, ?, ?)", (time.strftime("%Y-%m-%d %H:%M:%S"), prompt, response))
            await db.commit()
        with dec.open("rb") as f:
            enc = aes_encrypt(f.read(), key)
        DB_PATH.write_bytes(enc)
    finally:
        safe_cleanup([dec])

async def fetch_history(key: bytes, limit:int=20, offset:int=0, search:Optional[str]=None):
    dec = allocate_temp_db_path()
    rows=[]
    try:
        decrypt_file(DB_PATH, dec, key)
        async with aiosqlite.connect(dec) as db:
            if search:
                q = f"%{search}%"
                async with db.execute("SELECT id,timestamp,prompt,response FROM history WHERE prompt LIKE ? OR response LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?", (q,q,limit,offset)) as cur:
                    async for r in cur: rows.append(r)
            else:
                async with db.execute("SELECT id,timestamp,prompt,response FROM history ORDER BY id DESC LIMIT ? OFFSET ?", (limit,offset)) as cur:
                    async for r in cur: rows.append(r)
        with dec.open("rb") as f:
            DB_PATH.write_bytes(aes_encrypt(f.read(), key))
        return rows
    finally:
        safe_cleanup([dec])

def load_llama_model_blocking(model_path: Path) -> Llama:
    return Llama(model_path=str(model_path), n_ctx=2048, n_threads=4)

class LocalModelRuntime:
    def __init__(self, profile: dict, model_path: Path):
        self.profile = profile
        self.model_path = model_path
        self.runtime = str(profile.get("runtime", "llama_cpp"))
        self.llm: Any = None
        self.engine_ctx: Any = None
        self.engine: Any = None
        self.conversation_ctx: Any = None
        self.conversation: Any = None

    def load(self):
        if self.runtime == "litert_lm":
            if importlib.util.find_spec("litert_lm") is None:
                raise RuntimeError("LiteRT-LM runtime missing. Install litert-lm-api==0.10.1 and litert-lm==0.10.1.")
            import litert_lm
            try:
                litert_lm.set_min_log_severity(litert_lm.LogSeverity.ERROR)
            except Exception:
                pass
            self.engine_ctx = litert_lm.Engine(str(self.model_path))
            self.engine = self.engine_ctx.__enter__() if hasattr(self.engine_ctx, "__enter__") else self.engine_ctx
            self.conversation_ctx = self.engine.create_conversation()
            self.conversation = self.conversation_ctx.__enter__() if hasattr(self.conversation_ctx, "__enter__") else self.conversation_ctx
            return self
        self.llm = load_llama_model_blocking(self.model_path)
        return self

    def close(self):
        for ctx in (self.conversation_ctx, self.engine_ctx):
            try:
                exit_fn = getattr(ctx, "__exit__", None)
                if callable(exit_fn):
                    exit_fn(None, None, None)
            except Exception:
                pass
        self.conversation = None
        self.engine = None
        self.llm = None

    def generate(self, prompt: str, max_tokens: int = 256, temperature: float = 0.2) -> str:
        if self.runtime == "litert_lm":
            if self.conversation is None:
                raise RuntimeError("LiteRT-LM conversation is not loaded")
            response = self.conversation.send_message(prompt)
            return extract_litert_text(response)
        if self.llm is None:
            raise RuntimeError("llama.cpp model is not loaded")
        return extract_llama_text(self.llm(prompt, max_tokens=max_tokens, temperature=temperature))

    def __call__(self, prompt: str, max_tokens: int = 256, temperature: float = 0.2):
        return {"choices": [{"text": self.generate(prompt, max_tokens=max_tokens, temperature=temperature)}]}

def extract_llama_text(out: Any) -> str:
    if isinstance(out, dict):
        choices = out.get("choices")
        if isinstance(choices, list) and choices:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                text = first_choice.get("text")
                return "" if text is None else str(text)
        text = out.get("text")
        return "" if text is None else str(text)
    return str(out)

def extract_litert_text(response) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        parts = []
        for item in response.get("content", []):
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
        if parts:
            return "".join(parts)
        return str(response.get("text", ""))
    return str(response)

def load_model_runtime_blocking(profile: dict, model_path: Path) -> LocalModelRuntime:
    return LocalModelRuntime(profile, model_path).load()

def collect_system_metrics() -> Dict[str, float]:
    if psutil is None:
        raise RuntimeError("psutil is required for system metrics")

    try:
        cpu = psutil.cpu_percent(interval=0.1) / 100.0
        mem = psutil.virtual_memory().percent / 100.0
        try:
            load_raw = os.getloadavg()[0]
            cpu_cnt = psutil.cpu_count(logical=True) or 1
            load1 = max(0.0, min(1.0, load_raw / max(1.0, float(cpu_cnt))))
        except Exception:
            load1 = cpu
        try:
            sensors_temperatures = getattr(psutil, "sensors_temperatures", None)
            temps_map = sensors_temperatures() if callable(sensors_temperatures) else None
            if temps_map:
                first = next(iter(temps_map.values()))[0].current
                temp = max(0.0, min(1.0, (first - 20.0) / 70.0))
            else:
                temp = 0.0
        except Exception:
            temp = 0.0
        try:
            proc_count = len(psutil.pids())
            proc = max(0.0, min(1.0, proc_count / 512.0))
        except Exception:
            proc_count = 0
            proc = 0.0
    except Exception as exc:
        raise RuntimeError(f"Unable to obtain psutil system metrics: {exc}") from exc

    return {
        "cpu": float(max(0.0, min(1.0, cpu))),
        "mem": float(max(0.0, min(1.0, mem))),
        "load1": float(max(0.0, min(1.0, load1))),
        "temp": float(max(0.0, min(1.0, temp))),
        "proc": float(max(0.0, min(1.0, proc))),
        "proc_count": float(proc_count),
    }

def add_interference_jitter(max_ms: int = 50) -> None:
    delay_raw = int.from_bytes(os.urandom(2), "big") / 65535.0
    time.sleep(0.001 + delay_raw * max_ms / 1000.0)
    dummy_count = 256 + int.from_bytes(os.urandom(2), "big") % 2048
    acc = 0.0
    for i in range(dummy_count):
        acc += math.sin(i % 17) * math.cos((i + dummy_count) % 19)
    if acc == float("inf"):
        print("", end="")

def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return float((ordered[mid - 1] + ordered[mid]) / 2.0)

def collect_resilient_system_metrics(samples: int = SCANNER_METRIC_SAMPLES) -> Dict[str, float]:
    settings = read_security_settings()
    samples = max(samples, _safe_int(settings.get("metric_samples"), samples))
    readings = []
    for _ in range(max(1, samples)):
        add_interference_jitter(12)
        readings.append(collect_system_metrics())

    metrics: Dict[str, float] = {}
    for key_name_ in ("cpu", "mem", "load1", "temp", "proc"):
        vals = [float(r.get(key_name_, 0.0)) for r in readings]
        metrics[key_name_] = _median(vals)
        metrics[f"{key_name_}_spread"] = max(vals) - min(vals) if vals else 0.0
    metrics["proc_count"] = _median([float(r.get("proc_count", 0.0)) for r in readings])
    spread = max(metrics.get("cpu_spread", 0.0), metrics.get("mem_spread", 0.0), metrics.get("load1_spread", 0.0), metrics.get("temp_spread", 0.0))
    flatline = all(metrics.get(f"{k}_spread", 0.0) < 0.002 for k in ("cpu", "mem", "load1")) and len(readings) > 1
    pressure = 0.0
    if metrics.get("cpu", 0.0) > 0.92 or metrics.get("mem", 0.0) > 0.92 or metrics.get("temp", 0.0) > 0.85:
        pressure += 0.25
    if flatline:
        pressure += 0.15
    metrics["sample_count"] = float(len(readings))
    metrics["interference_score"] = max(0.0, min(1.0, spread * 2.5 + pressure))
    return metrics

def metrics_to_rgb(metrics: dict) -> Tuple[float,float,float]:
    cpu = metrics.get("cpu",0.1); mem = metrics.get("mem",0.1); temp = metrics.get("temp",0.1); load1 = metrics.get("load1",0.0)
    r = cpu * (1.0 + load1); g = mem * (1.0 + load1 * 0.5); b = temp * (0.5 + cpu * 0.5)
    maxi = max(r,g,b,1.0); r,g,b = r/maxi,g/maxi,b/maxi
    return (float(max(0.0,min(1.0,r))), float(max(0.0,min(1.0,g))), float(max(0.0,min(1.0,b))))

def pennylane_entropic_score(rgb: Tuple[float, float, float], shots: int = 256) -> float:
    

    
    if qml is None or pnp is None:
        r, g, b = rgb

        
        ri = int(r * 255) & 0xFF
        gi = int(g * 255) & 0xFF
        bi = int(b * 255) & 0xFF

        
        seed = (ri << 16) | (gi << 8) | bi
        rng = random.Random(seed)

        base = (0.3 * r + 0.4 * g + 0.3 * b)

        
        noise = (rng.random() - 0.5) * 0.08

        return max(0.0, min(1.0, base + noise))

    
    dev = qml.device("default.qubit", wires=2, shots=shots)

    @qml.qnode(dev)
    def circuit(a, b, c):
        qml.RX(a * math.pi, wires=0)
        qml.RY(b * math.pi, wires=1)
        qml.CNOT(wires=[0, 1])
        qml.RZ(c * math.pi, wires=1)
        qml.RX((a + b) * math.pi / 2, wires=0)
        qml.RY((b + c) * math.pi / 2, wires=1)
        return (
            qml.expval(qml.PauliZ(0)),
            qml.expval(qml.PauliZ(1)),
        )

    a, b, c = float(rgb[0]), float(rgb[1]), float(rgb[2])

    try:
        ev0, ev1 = circuit(a, b, c)

        
        combined = ((ev0 + 1.0) / 2.0) * 0.6 + ((ev1 + 1.0) / 2.0) * 0.4

        
        score = 1.0 / (1.0 + math.exp(-6.0 * (combined - 0.5)))

        return float(max(0.0, min(1.0, score)))

    except Exception:
        
        return float(max(0.0, min(1.0, (a + b + c) / 3.0)))

def enhanced_entropic_score(rgb: Tuple[float, float, float], metrics: Dict[str, float]) -> float:
    base = pennylane_entropic_score(rgb)
    metric_blob = json.dumps(metrics, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest_noise = hashlib.sha256(metric_blob + os.urandom(16)).digest()[0] / 255.0
    urandom_noise = int.from_bytes(os.urandom(8), "big") / float(2**64 - 1)
    return float(max(0.0, min(1.0, base * 0.70 + digest_noise * 0.15 + urandom_noise * 0.15)))

def scanner_integrity_text(metrics: Dict[str, float]) -> str:
    score = float(metrics.get("interference_score", 0.0))
    if score >= 0.70:
        level = "high"
    elif score >= 0.35:
        level = "medium"
    else:
        level = "low"
    return f"local_interference={score:.2f} (level={level}, samples={int(metrics.get('sample_count', 1))})"

def apply_interference_bias(label: str, interference_score: float) -> str:
    if interference_score >= 0.90 and label == "Medium":
        return "High"
    if interference_score >= 0.70 and label == "Low":
        return "Medium"
    return label

def public_scan_input(data: dict) -> dict:
    return {k: sanitize_observation_value(v) for k, v in data.items() if not k.startswith("_")}

def normalize_risk_label(text: str) -> str:
    candidate = (text or "").split()
    label = candidate[0].capitalize() if candidate else ""
    if label in ("Low", "Medium", "High"):
        return label
    lowered = (text or "").lower()
    if "low" in lowered:
        return "Low"
    if "medium" in lowered:
        return "Medium"
    if "high" in lowered:
        return "High"
    return "Medium"

def _clamp01(value: float) -> float:
    return float(max(0.0, min(1.0, value)))

def _parse_int(value, default: int = 0, low: int = 0, high: int = 12) -> int:
    try:
        found = re.search(r"-?\d+", str(value))
        parsed = int(found.group(0)) if found else int(default)
    except Exception:
        parsed = default
    return max(low, min(high, parsed))

def _activity_factor(value) -> float:
    text = str(value or "").strip().lower()
    if text in ("high", "active", "yes", "y", "many"):
        return 1.0
    if text in ("medium", "med", "some"):
        return 0.65
    if text in ("low", "few"):
        return 0.35
    return 0.0

def _topology_factor(value) -> float:
    text = str(value or "").strip().lower()
    if "surround" in text or "circle" in text:
        return 1.0
    if "triangle" in text or "triang" in text:
        return 0.85
    if "cluster" in text or "group" in text:
        return 0.55
    if "line" in text or "single" in text:
        return 0.25
    return 0.0

def _parse_distance_pressure(value) -> float:
    text = str(value or "").strip().lower()
    if not text or text in ("unknown", "none", "n/a"):
        return 0.35
    try:
        found = re.search(r"\d+(?:\.\d+)?", text)
        meters = float(found.group(0)) if found else 3.0
        return _clamp01((5.0 - meters) / 5.0)
    except Exception:
        return 0.35

def sanitize_observation_value(value):
    if not isinstance(value, str):
        return value
    return re.sub(r"\b(latino|latina|latinx|hispanic|latin\s+american)\b", "[redacted-person-descriptor]", value, flags=re.IGNORECASE)

def simulate_multi_node_interference(data: dict, metrics: Dict[str, float], trials: int = 96) -> Dict[str, object]:
    public = public_scan_input(data)
    node_count = _parse_int(public.get("nearby_unknown_device_count", 0), default=0, low=0, high=12)
    topology = str(public.get("nearby_device_geometry", "none") or "none").strip().lower() or "none"
    topology_pressure = _topology_factor(topology)
    activity_pressure = _activity_factor(public.get("handheld_device_activity", "none"))
    distance_pressure = _parse_distance_pressure(public.get("nearest_device_distance", "unknown"))
    metric_pressure = float(metrics.get("interference_score", 0.0))
    node_pressure = _clamp01(node_count / 8.0)
    seed = hashlib.blake2b(json.dumps({"input": public, "metric": round(metric_pressure, 4), "nonce": base64.b64encode(os.urandom(16)).decode("ascii")}, sort_keys=True).encode("utf-8"), digest_size=16).digest()
    rng = random.Random(int.from_bytes(seed, "big"))
    observations = []
    for _ in range(max(16, trials)):
        observations.append(_clamp01(node_pressure * 0.25 + rng.random() * topology_pressure * 0.25 + rng.random() * max(activity_pressure, node_pressure) * 0.20 + rng.random() * distance_pressure * 0.15 + rng.random() * metric_pressure * 0.15))
    score = _clamp01(_median(observations) * 0.70 + max(observations) * 0.30)
    vector_scores = {
        "timing": _clamp01(score * 0.65 + metric_pressure * 0.35),
        "cache": _clamp01(score * 0.55 + node_pressure * 0.25 + topology_pressure * 0.20),
        "em_power": _clamp01(score * 0.45 + activity_pressure * 0.35 + distance_pressure * 0.20),
        "acoustic_thermal": _clamp01(metric_pressure * 0.65 + activity_pressure * 0.20 + node_pressure * 0.15),
        "sensor_spoofing": _clamp01(topology_pressure * 0.35 + node_pressure * 0.25 + metric_pressure * 0.40),
    }
    passes = 5 if score >= 0.70 else 3 if score >= 0.35 else 1
    level = "high" if score >= 0.70 else "medium" if score >= 0.35 else "low"
    return {"score": float(score), "level": level, "node_count": node_count, "topology": topology, "passes": passes, "vector_scores": vector_scores, "session": hashlib.sha256(seed + os.urandom(16)).hexdigest()[:16]}

def multi_node_surface_text(surface: Dict[str, object]) -> str:
    return "multi_node={score:.2f} (level={level}, nodes={nodes}, topology={topology}, passes={passes})".format(
        score=_safe_float(surface.get("score"), 0.0),
        level=surface.get("level", "unknown"),
        nodes=_safe_int(surface.get("node_count"), 0),
        topology=surface.get("topology", "unknown"),
        passes=_safe_int(surface.get("passes"), 1),
    )

def defense_capsule_text(data: dict, metrics: Dict[str, float], surface: Dict[str, object]) -> str:
    payload = {"input": public_scan_input(data), "metrics": {k: round(float(v), 4) for k, v in metrics.items() if isinstance(v, (int, float))}, "surface": surface, "colorwheel": colorwheel_entropy_state("defense-capsule", {"surface": surface.get("score", 0.0)}, persist=True), "noise": base64.b64encode(os.urandom(24)).decode("ascii")}
    return "defense_capsule=" + hashlib.sha3_256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:24]

def defense_pass_count(data: dict) -> int:
    settings = read_security_settings()
    if not settings.get("defense_voting", True):
        return 1
    configured = max(1, min(5, _safe_int(data.get("_scanner_defense_passes"), 1)))
    return max(1, min(_safe_int(settings.get("max_defense_passes"), 5), configured))

def majority_risk_label(labels: List[str]) -> str:
    counts = {label: labels.count(label) for label in ("Low", "Medium", "High")}
    max_count = max(counts.values()) if counts else 0
    winners = [label for label, count in counts.items() if count == max_count]
    for label in ("High", "Medium", "Low"):
        if label in winners:
            return label
    return "Medium"

def augment_prompt_with_defense_pass(prompt: str, data: dict, pass_idx: int, total_passes: int) -> str:
    if total_passes <= 1:
        return prompt
    marker = hashlib.blake2b(json.dumps({"capsule": data.get("_scanner_defense_capsule", ""), "colorwheel": colorwheel_marker("defense-pass", {"pass": pass_idx, "total": total_passes}), "pass": pass_idx, "noise": base64.b64encode(os.urandom(12)).decode("ascii")}, sort_keys=True).encode("utf-8"), digest_size=8).hexdigest()
    return prompt + f"\n\n[defense_pass]\nindex={pass_idx + 1}/{total_passes}; nonce={marker}; colorwheel_trace=private; vote_privately=true\n[/defense_pass]"

def defense_recommendations(surface: Dict[str, object]) -> List[str]:
    score = _safe_float(surface.get("score"), 0.0)
    passes = _safe_int(surface.get("passes"), 1)
    recs = [f"Run {passes} randomized inference pass{'es' if passes != 1 else ''} and majority-vote the label.", "Keep scanner inputs about devices/signals, not personal traits.", "Verify directly on site if conditions feel unsafe or confusing."]
    if score >= 0.35:
        recs.extend(["Disable nonessential radios before scanning.", "Use a cooldown and re-run from a quieter location if possible.", "Export encrypted defense logs for later comparison."])
    if score >= 0.70:
        recs.extend(["Treat output as degraded-confidence support.", "Bias toward caution under high local anomaly pressure."])
    return recs

def entropic_to_modifier(score: float) -> float:
    return (score - 0.5) * 0.4

def entropic_summary_text(score: float) -> str:
    if score >= 0.75: level = "high"
    elif score >= 0.45: level = "medium"
    else: level = "low"
    return f"entropic_score={score:.3f} (level={level})"

def _simple_tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[A-Za-z0-9_\-]+", text.lower())]

def punkd_analyze(prompt_text: str, top_n: int = 12) -> Dict[str,float]:
    toks = _simple_tokenize(prompt_text)
    freq={}
    for t in toks: freq[t]=freq.get(t,0)+1
    hazard_boost = {
        "ice":2.0,"wet":1.8,"snow":2.0,"flood":2.0,"construction":1.8,"pedestrian":1.8,"debris":1.8,"animal":1.5,"stall":1.4,"fog":1.6,
        "raw":1.8,"undercooked":2.0,"expired":2.0,"recall":2.2,"mold":2.0,"odor":1.6,"cloudy":1.5,"contaminated":2.3,"boil":1.8,"leak":1.6,
    }
    scored={}
    for t,c in freq.items():
        boost = hazard_boost.get(t,1.0)
        scored[t]=c*boost
    items = sorted(scored.items(), key=lambda x:-x[1])[:top_n]
    if not items: return {}
    maxv = items[0][1]
    return {k: float(v/maxv) for k,v in items}

def punkd_apply(prompt_text: str, token_weights: Dict[str,float], profile: str = "balanced") -> Tuple[str,float]:
    if not token_weights: return prompt_text, 1.0
    mean_weight = sum(token_weights.values())/len(token_weights)
    profile_map = {"conservative": 0.6, "balanced": 1.0, "aggressive": 1.4}
    base = profile_map.get(profile, 1.0)
    multiplier = 1.0 + (mean_weight - 0.5) * 0.8 * (base if base>1.0 else 1.0)
    multiplier = max(0.6, min(1.8, multiplier))
    sorted_tokens = sorted(token_weights.items(), key=lambda x:-x[1])[:6]
    markers = " ".join([f"<ATTN:{t}:{round(w,2)}>" for t,w in sorted_tokens])
    patched = prompt_text + "\n\n[PUNKD_MARKERS] " + markers
    return patched, multiplier

def chunked_generate(llm: Callable[..., object], prompt: str, max_total_tokens: int = 256, chunk_tokens: int = 64, base_temperature: float = 0.2, punkd_profile: str = "balanced", streaming_callback: Optional[Callable[[str], None]] = None) -> str:
    assembled = ""
    cur_prompt = prompt
    token_weights = punkd_analyze(prompt, top_n=16)
    iterations = max(1, (max_total_tokens + chunk_tokens - 1)//chunk_tokens)
    prev_tail = ""
    for i in range(iterations):
        patched_prompt, mult = punkd_apply(cur_prompt, token_weights, profile=punkd_profile)
        temp = max(0.01, min(2.0, base_temperature * mult))
        out = llm(patched_prompt, max_tokens=chunk_tokens, temperature=temp)
        text = extract_llama_text(out)
        text = (text or "").strip()
        if not text: break
        overlap = 0
        max_ol = min(30, len(prev_tail), len(text))
        for olen in range(max_ol, 0, -1):
            if prev_tail.endswith(text[:olen]):
                overlap = olen
                break
        append_text = text[overlap:] if overlap else text
        assembled += append_text
        prev_tail = assembled[-120:] if len(assembled)>120 else assembled
        if streaming_callback: streaming_callback(append_text)
        if assembled.strip().endswith(("Low","Medium","High")): break
        if len(text.split()) < max(4, chunk_tokens//8): break
        cur_prompt = prompt + "\n\nAssistant so far:\n" + assembled + "\n\nContinue:"
    return assembled.strip()

def build_road_scanner_prompt(data: dict, include_system_entropy: bool = True) -> str:
    entropy_text = "entropic_score=unknown"
    integrity_text = "local_interference=unknown"
    multi_node_text = "multi_node=unknown"
    defense_capsule = "defense_capsule=unknown"
    colorwheel_text = "colorwheel=unknown"
    metrics_line = "sys_metrics: disabled"
    input_checksum = hashlib.sha256(json.dumps(public_scan_input(data), sort_keys=True).encode("utf-8")).hexdigest()[:16]
    if include_system_entropy:
        metrics = collect_resilient_system_metrics()
        rgb = metrics_to_rgb(metrics)
        score = enhanced_entropic_score(rgb, metrics)
        surface = simulate_multi_node_interference(data, metrics)
        entropy_text = entropic_summary_text(score)
        integrity_text = scanner_integrity_text(metrics)
        multi_node_text = multi_node_surface_text(surface)
        defense_capsule = defense_capsule_text(data, metrics, surface)
        colorwheel_text = colorwheel_marker(
            "scanner-prompt",
            {
                "input": public_scan_input(data),
                "interference": metrics.get("interference_score", 0.0),
                "surface": surface.get("score", 0.0),
            },
        )
        data["_scanner_interference_score"] = float(metrics.get("interference_score", 0.0))
        data["_scanner_integrity"] = integrity_text
        data["_scanner_multi_node"] = multi_node_text
        data["_scanner_defense_capsule"] = defense_capsule
        data["_scanner_colorwheel"] = colorwheel_text
        data["_scanner_defense_passes"] = _safe_int(surface.get("passes"), 1)
        data["_scanner_vector_scores"] = surface.get("vector_scores", {})
        metrics_line = "sys_metrics: cpu={cpu:.2f},mem={mem:.2f},load={load1:.2f},temp={temp:.2f},proc={proc:.2f},interference={interference:.2f}".format(
            cpu=metrics.get("cpu", 0.0),
            mem=metrics.get("mem", 0.0),
            load1=metrics.get("load1", 0.0),
            temp=metrics.get("temp", 0.0),
            proc=metrics.get("proc", 0.0),
            interference=metrics.get("interference_score", 0.0),
        )
    tpl = (
f"You are an advanced coherant tuned matric surface hypertime nanobot specialized Food Risk Classification AI trained to evaluate real-world food scenes.\n"
f"Analyze the environmental and triple check for accurate sensor data and determine the overall food or water risk level.\n"
f"Always verify current status on-site before relying on this scanner.\n"
f"Your reply must be only one word: Low, Medium, or High.\n\n"
f"[tuning]\n"
f"Scene details:\n"
f"Location: {data.get('location','unspecified location')}\n"
f"Food or Water Type: {data.get('road_type','unknown')}\n"
f"{metrics_line}\n"
f"Quantum data: {entropy_text}\n"
f"Sensor Integrity: {integrity_text}\n"
f"Multi-node Surface: {multi_node_text}\n"
f"Defense Capsule: {defense_capsule}\n"
f"Colorwheel Entropy Machine: {colorwheel_text}\n"
f"Input Checksum: {input_checksum}\n"
f"[/tuning]\n\n"
f"Follow these strict rules when forming your decision:\n"
f"- Think through all scene factors internally but do not show reasoning.\n"
f"- Evaluate the available location and food or water type holistically.\n"
f"- Optionally use the system entropic signal to bias your internal confidence slightly.\n"
f"- Treat unstable, suspiciously flat, spoofed, or high-pressure local metrics as possible interference.\n"
f"- Use only abstract nearby-device geometry and runtime anomalies; ignore identity, ethnicity, appearance, age, or protected traits.\n"
f"- Treat the colorwheel entropy machine as a trace-scrambling selector that makes repeated outputs harder to pattern-learn.\n"
f"- Always verify current status on-site; this label is decision support, not a replacement for direct inspection.\n"
f"- Choose only one risk level that best fits the entire situation.\n"
f"- Output exactly one word, with no punctuation or labels.\n"
f"- The valid outputs are only: Low, Medium, High.\n\n"
f"[action]\n"
f"1) Normalize available inputs to comparable scales.\n"
f"2) Average repeated metric samples and reject outlier readings.\n"
f"3) Map food or water risk cues -> discrete label using conservative thresholds.\n"
f"4) If sensor integrity anomalies are detected, bias toward higher risk.\n"
f"5) Account for local interference from EM noise, power instability, thermal pressure, process spikes, or metric spoofing.\n"
f"6) Use the abstract multi-node surface to choose conservative internal confidence if coordinated-device conditions are plausible.\n"
f"7) Use colorwheel entropy state to decorrelate model/pass/prompt timing without exposing hidden reasoning.\n"
f"8) PUNKD: detect key tokens and locally adjust attention/temperature slightly to focus decisions.\n"
f"9) Do not output internal reasoning or diagnostics; only return the single-word label.\n"
f"[/action]\n\n"
f"[replytemplate]\nLow | Medium | High\n[/replytemplate]"
    )
    return tpl

def allocate_temp_db_path() -> Path:
    fd, path = tempfile.mkstemp(prefix="chat_history_", suffix=".db")
    os.close(fd)
    return Path(path)

def header(status:dict):
    selected = status.get("selected_model", read_selected_model_profile()) if status else read_selected_model_profile()
    mode = status.get("model_selection_mode", read_model_selection_mode()) if status else read_model_selection_mode()
    settings = status.get("security_settings", read_security_settings()) if status else read_security_settings()
    disabled = len(_disabled_model_ids_from(settings))
    s = (
        f" Secure LLM CLI | Model: {'loaded' if status.get('model_loaded') else 'none'} | "
        f"Pick: {selected['name']} | Mode: {mode} | Defense: {settings.get('defense_profile')} | "
        f"Disabled: {disabled} | Crypto: {oqs_crypto_status()} "
    )
    print(color(s.center(terminal_width(), '─'), fg=35, bold=True))

def model_manager(state:dict):
    options = [
        "Select active model",
        "Toggle selection mode fixed/entropy",
        "Download active model from remote repo",
        "Verify active plaintext model hash",
        "Encrypt active plaintext model -> .aes",
        "Decrypt active .aes -> plaintext (temporary)",
        "Delete active plaintext model",
        "Back",
    ]
    while True:
        profile = state.get("selected_model", read_selected_model_profile())
        settings = state.get("security_settings", read_security_settings())
        idx = choose_menu(
            "Model Manager",
            options,
            status=state,
            footer=[
                f"Active: {model_label(profile)}",
                f"Selection mode: {state.get('model_selection_mode', read_model_selection_mode())}",
                f"Enabled models: {len(enabled_model_profiles(settings))}/{len(MODEL_PROFILES)}",
                "Disabled models are excluded from chat, scans, and entropy-random selection.",
            ],
        )
        choice = str(idx + 1)
        profile = state.get("selected_model", read_selected_model_profile())
        model_path = model_path_for(profile)
        encrypted_path = encrypted_model_path_for(profile)
        if choice == "1":
            selected_idx = choose_menu(
                "Select Model",
                [("[enabled] " if is_model_enabled(p, settings) else "[disabled] ") + model_label(p) for p in MODEL_PROFILES],
                status=state,
                footer=["Press s to select the highlighted model."],
                select_keys={"s", "S"},
            )
            selected = MODEL_PROFILES[selected_idx]
            if not is_model_enabled(selected, settings):
                print("That model is disabled in Settings. Enable it before selecting it.")
                input("Enter...")
                continue
            state["selected_model"] = selected
            write_selected_model_profile(selected)
        elif choice == "2":
            mode = state.get("model_selection_mode", read_model_selection_mode())
            mode = "fixed" if mode == "entropy" else "entropy"
            write_model_selection_mode(mode)
            state["model_selection_mode"] = mode
        elif choice == "3":
            if model_path.exists():
                if input(f"Plaintext model exists at {model_path}; overwrite? (y/N): ").strip().lower() != "y":
                    continue
            try:
                url = profile["repo"] + profile["file"]
                sha = download_model_httpx(url, model_path, show_progress=True, timeout=None, expected_sha=profile.get("expected_hash"))
                print(f"Downloaded to {model_path}")
                print(f"Computed SHA256: {sha}")
                if input("Encrypt downloaded model with current key now? (Y/n): ").strip().lower() != "n":
                    encrypt_file(model_path, encrypted_path, state['key'])
                    print(f"Encrypted -> {encrypted_path}")
                    if input("Remove plaintext model? (Y/n): ").strip().lower() != "n":
                        model_path.unlink(); print("Plaintext removed.")
            except Exception as e:
                print(f"Download failed: {e}")
            input("Enter to continue...")
        elif choice == "4":
            if not model_path.exists():
                print("No plaintext model found.")
            else:
                sha = sha256_file(model_path)
                print(f"SHA256: {sha}")
                expected = profile.get("expected_hash")
                if expected:
                    print("Hash matches expected." if sha.lower() == expected.lower() else f"Hash mismatch; expected {expected}")
            input("Enter to continue...")
        elif choice == "5":
            if not model_path.exists():
                print("No plaintext model to encrypt."); input("Enter..."); continue
            encrypt_file(model_path, encrypted_path, state['key'])
            if input("Remove plaintext? (Y/n): ").strip().lower() != "n":
                model_path.unlink(); print("Removed plaintext.")
            input("Enter...")
        elif choice == "6":
            if not encrypted_path.exists():
                print("No .aes model present.")
            else:
                decrypt_file(encrypted_path, model_path, state['key'])
            input("Enter...")
        elif choice == "7":
            if model_path.exists():
                if input(f"Delete {model_path}? (y/N): ").strip().lower() == "y":
                    model_path.unlink(); print("Deleted.")
            else:
                print("No plaintext model.")
            input("Enter...")
        else:
            return

def settings_flow(state:dict):
    while True:
        settings = state.get("security_settings", read_security_settings())
        footer = [
            f"Profile: {settings.get('defense_profile')}",
            f"Defense voting: {'on' if settings.get('defense_voting') else 'off'}",
            f"Metric samples: {settings.get('metric_samples')} | Max passes: {settings.get('max_defense_passes')} | Noise width: {settings.get('noise_width')} | Jitter: {settings.get('jitter_scale')}",
            f"Colorwheel: {'on' if settings.get('colorwheel_enabled') else 'off'} | Spins: {settings.get('colorwheel_spins')} | Rings: {settings.get('colorwheel_rings')} | ML scramble: {'on' if settings.get('ml_trace_scramble') else 'off'}",
            f"Enabled models: {len(enabled_model_profiles(settings))}/{len(MODEL_PROFILES)}",
        ]
        idx = choose_menu(
            "Settings",
            [
                "Model enable / disable controls",
                "Defense profile",
                "Toggle defense voting",
                "Toggle colorwheel entropy",
                "Toggle ML trace scramble",
                "Set colorwheel spins",
                "Set colorwheel rings",
                "Set max defense passes",
                "Set metric samples",
                "Set noise width",
                "Run colorwheel spin test",
                "Reset settings",
                "Back",
            ],
            status=state,
            footer=footer,
        )
        if idx == 0:
            while True:
                settings = state.get("security_settings", read_security_settings())
                options = [("[enabled] " if is_model_enabled(profile, settings) else "[disabled] ") + model_label(profile) for profile in MODEL_PROFILES] + ["Back"]
                pick = choose_menu(
                    "Model Controls",
                    options,
                    status=state,
                    footer=[
                        "Press s to select/deselect the highlighted model.",
                        "Disabled models are excluded from chat, scans, and entropy-random selection.",
                    ],
                    select_keys={"s", "S"},
                )
                if pick >= len(MODEL_PROFILES):
                    break
                profile = MODEL_PROFILES[pick]
                disabled = _disabled_model_ids_from(settings)
                if profile["id"] in disabled:
                    disabled.remove(profile["id"])
                else:
                    if len(disabled) >= len(MODEL_PROFILES) - 1:
                        print("At least one model must stay enabled.")
                        input("Enter...")
                        continue
                    disabled.append(profile["id"])
                settings["disabled_model_ids"] = disabled
                settings = normalize_security_settings(settings)
                if not is_model_enabled(state.get("selected_model", read_selected_model_profile()), settings):
                    state["selected_model"] = first_enabled_model_profile(settings)
                    write_selected_model_profile(state["selected_model"])
                write_security_settings(settings)
                state["security_settings"] = settings
        elif idx == 1:
            names = list(DEFENSE_PROFILE_PRESETS.keys())
            pick = choose_menu("Defense Profile", [name.title() for name in names], status=state)
            settings.update(DEFENSE_PROFILE_PRESETS[names[pick]])
            settings["defense_profile"] = names[pick]
            settings = normalize_security_settings(settings)
            write_security_settings(settings)
            state["security_settings"] = settings
        elif idx == 2:
            settings["defense_voting"] = not bool(settings.get("defense_voting", True))
            settings = normalize_security_settings(settings)
            write_security_settings(settings)
            state["security_settings"] = settings
        elif idx == 3:
            settings["colorwheel_enabled"] = not bool(settings.get("colorwheel_enabled", True))
            settings = normalize_security_settings(settings)
            write_security_settings(settings)
            state["security_settings"] = settings
        elif idx == 4:
            settings["ml_trace_scramble"] = not bool(settings.get("ml_trace_scramble", True))
            settings = normalize_security_settings(settings)
            write_security_settings(settings)
            state["security_settings"] = settings
        elif idx == 5:
            value = input("Colorwheel spins (16-256): ").strip()
            if value.isdigit():
                settings["colorwheel_spins"] = int(value)
                settings = normalize_security_settings(settings)
                write_security_settings(settings)
                state["security_settings"] = settings
        elif idx == 6:
            value = input("Colorwheel rings (6-24): ").strip()
            if value.isdigit():
                settings["colorwheel_rings"] = int(value)
                settings = normalize_security_settings(settings)
                write_security_settings(settings)
                state["security_settings"] = settings
        elif idx == 7:
            value = input("Max defense passes (1-5): ").strip()
            if value.isdigit():
                settings["max_defense_passes"] = int(value)
                settings = normalize_security_settings(settings)
                write_security_settings(settings)
                state["security_settings"] = settings
        elif idx == 8:
            value = input("Metric samples (3-13): ").strip()
            if value.isdigit():
                settings["metric_samples"] = int(value)
                settings = normalize_security_settings(settings)
                write_security_settings(settings)
                state["security_settings"] = settings
        elif idx == 9:
            value = input("Noise thread width (1-4): ").strip()
            if value.isdigit():
                settings["noise_width"] = int(value)
                settings = normalize_security_settings(settings)
                write_security_settings(settings)
                state["security_settings"] = settings
        elif idx == 10:
            marker = render_colorwheel_spinner("Settings colorwheel test", frames=24)
            print(marker)
            input("Enter...")
        elif idx == 11:
            settings = normalize_security_settings()
            write_security_settings(settings)
            state["security_settings"] = settings
            state["selected_model"] = first_enabled_model_profile(settings)
            write_selected_model_profile(state["selected_model"])
        else:
            return

async def chat_session(state:dict):
    profile = entropy_select_model_profile(state, purpose="chat")
    model_path = model_path_for(profile)
    encrypted_path = encrypted_model_path_for(profile)
    if not encrypted_path.exists():
        print(f"No encrypted model found for {model_label(profile)}. Please download & encrypt it first.")
        input("Enter...")
        return
    decrypt_file(encrypted_path, model_path, state['key'])
    loop = asyncio.get_running_loop()
    runtime = None
    with ThreadPoolExecutor(max_workers=1) as ex:
        try:
            render_screen(
                state,
                "chat",
                "Live Chat",
                "Encrypted model session with local history logging.",
                "Boot Sequence",
                [f"Decrypting model payload for {model_label(profile)}...", f"Loading {model_runtime_name(profile)} runtime...", "Preparing secure chat loop..."],
            )
            runtime = await loop.run_in_executor(ex, load_model_runtime_blocking, profile, model_path)
        except Exception as e:
            print(f"Failed to load: {e}")
            if model_path.exists():
                try: encrypt_file(model_path, encrypted_path, state['key']); model_path.unlink()
                except Exception: pass
            input("Enter..."); return
        state['model_loaded']=True
        try:
            await init_db(state['key'])
            render_screen(
                state,
                "chat",
                "Live Chat",
                "Ask questions, review local history, or exit back to the menu.",
                "Commands",
                [f"Model: {model_label(profile)}", "/history  Show the last 10 messages", "/exit     Leave chat and re-encrypt the model"],
            )
            print("Type /exit to return, /history to show last 10 messages.")
            while True:
                prompt = input("\nYou> ").strip()
                if not prompt: continue
                if prompt in ("/exit","exit","quit"): break
                if prompt=="/history":
                    rows = await fetch_history(state['key'], limit=10)
                    for r in rows: print(f"[{r[0]}] {r[1]}\nQ: {r[2]}\nA: {r[3]}\n{'-'*30}")
                    continue
                def gen(p):
                    text = runtime.generate(p, max_tokens=256, temperature=0.7)
                    return (text or "").replace("You are a helpful AI assistant named SmolLM, trained by Hugging Face", "").strip()
                print("🤖 Thinking...")
                result = await loop.run_in_executor(ex, gen, prompt)
                print("\nModel:\n"+result+"\n")
                await log_interaction(f"[{model_label(profile)}] {prompt}", result, state['key'])
        finally:
            try:
                if runtime is not None:
                    runtime.close()
            except Exception:
                pass
            print("Re-encrypting model and removing plaintext...")
            try: encrypt_file(model_path, encrypted_path, state['key']); model_path.unlink(); state['model_loaded']=False
            except Exception as e: print(f"Cleanup failed: {e}")
            input("Enter...")

async def road_scanner_flow(state:dict):
    profile = entropy_select_model_profile(state, purpose="road-scan")
    model_path = model_path_for(profile)
    encrypted_path = encrypted_model_path_for(profile)
    if not encrypted_path.exists():
        print(f"No encrypted model found for {model_label(profile)}.")
        input("Enter...")
        return
    data={}
    render_screen(
        state,
        "scan",
        "Food / Water Scanner",
        "Capture food or water conditions and classify risk.",
        "Inputs",
        ["Leave blank to accept defaults.", "The final report screen now stays open until you choose an action."],
    )
    data['location'] = input("Location (e.g., Whole Foods): ").strip() or "unspecified location"
    data['road_type'] = input("Food or water type: ").strip() or "unspecified food or water"
    print("\nGeneration options:\n1) Chunked generation + punkd (recommended)\n2) Chunked only\n3) Direct single-call generation")
    gen_choice = input("Choose (1-3) [1]: ").strip() or "1"
    prompt = build_road_scanner_prompt(data, include_system_entropy=True)
    print("Spinning colorwheel entropy selector...")
    data["_scanner_colorwheel_spinner"] = render_colorwheel_spinner("Colorwheel entropy selector")
    decrypt_file(encrypted_path, model_path, state['key'])
    loop = asyncio.get_running_loop()
    runtime = None
    with ThreadPoolExecutor(max_workers=1) as ex:
        try:
            runtime = await loop.run_in_executor(ex, load_model_runtime_blocking, profile, model_path)
        except Exception as e:
            print(f"Model load failed: {e}")
            if model_path.exists():
                try: encrypt_file(model_path, encrypted_path, state['key']); model_path.unlink()
                except Exception: pass
            input("Enter..."); return
        def extract_label(text: str) -> str:
            text = (text or "").strip().replace("You are a helpful AI assistant named SmolLM, trained by Hugging Face", "")
            candidate = text.split()
            label = candidate[0].capitalize() if candidate else ""
            if label not in ("Low", "Medium", "High"):
                lowered = text.lower()
                if "low" in lowered: label = "Low"
                elif "medium" in lowered: label = "Medium"
                elif "high" in lowered: label = "High"
                else: label = "Medium"
            return apply_interference_bias(label, float(data.get("_scanner_interference_score", 0.0)))
        def gen_direct(p):
            add_interference_jitter(40)
            return runtime.generate(p, max_tokens=128, temperature=0.2).strip()
        def run_once(pass_idx: int, total_passes: int):
            pass_prompt = augment_prompt_with_defense_pass(prompt, data, pass_idx, total_passes)
            if gen_choice == "3":
                return gen_direct(pass_prompt)
            punkd_profile = "balanced" if gen_choice == "1" else "conservative"
            add_interference_jitter(40)
            return chunked_generate(llm=runtime, prompt=pass_prompt, max_total_tokens=256, chunk_tokens=64, base_temperature=0.18, punkd_profile=punkd_profile, streaming_callback=None)
        total_passes = defense_pass_count(data)
        print(f"Scanning with {total_passes} defense pass{'es' if total_passes != 1 else ''} using {model_label(profile)}...")
        vote_labels = []
        outputs = []
        for pass_idx in range(total_passes):
            result = await loop.run_in_executor(ex, run_once, pass_idx, total_passes)
            outputs.append(result)
            vote_labels.append(extract_label(result))
        text = outputs[0] if outputs else ""
        label = majority_risk_label(vote_labels)
        while True:
            result_lines = [
                f"Classification: {label}",
                f"Generator: {'direct' if gen_choice == '3' else 'chunked'}",
                f"Model: {model_label(profile)}",
                f"Votes: {', '.join(vote_labels) if vote_labels else 'none'}",
                f"Multi-node: {data.get('_scanner_multi_node', 'unknown')}",
                f"Colorwheel: {data.get('_scanner_colorwheel', 'unknown')}",
                f"Defense: {data.get('_scanner_defense_capsule', 'unknown')}",
                "",
                "Generated output:",
            ]
            result_lines.extend((text or label).splitlines()[:6] or [label])
            result_lines.extend(["", "Actions:"])
            ch = choose_menu(
                "Food / Water Scanner Result",
                ["Re-run with edits", "Export to JSON", "Save & return", "Cancel"],
                status=state,
                header=result_lines,
            )
            ch = str(ch + 1)
            if ch != "1":
                break
            print("Re-run: editing fields. Press Enter to keep current value.")
            for k in [key for key in list(data.keys()) if not key.startswith("_")]:
                v = input(f"{k} [{data[k]}]: ").strip()
                if v: data[k]=v
            prompt = build_road_scanner_prompt(data, include_system_entropy=True)
            print("Spinning colorwheel entropy selector...")
            data["_scanner_colorwheel_spinner"] = render_colorwheel_spinner("Colorwheel entropy selector")
            total_passes = defense_pass_count(data)
            print(f"Re-scanning with {total_passes} defense pass{'es' if total_passes != 1 else ''}...")
            vote_labels = []
            outputs = []
            for pass_idx in range(total_passes):
                result = await loop.run_in_executor(ex, run_once, pass_idx, total_passes)
                outputs.append(result)
                vote_labels.append(extract_label(result))
            text = outputs[0] if outputs else ""
            label = majority_risk_label(vote_labels)
        if ch in ("2","3"):
            try: await init_db(state['key']); await log_interaction("FOODWATER_SCANNER_PROMPT:\n"+prompt, "FOODWATER_SCANNER_RESULT:\n"+label, state['key'])
            except Exception as e: print(f"Failed to log: {e}")
        if ch=="2":
            outp = {
                "input": public_scan_input(data),
                "prompt": prompt,
                "result": label,
                "model": model_label(profile),
                "scanner_integrity": data.get("_scanner_integrity", "unknown"),
                "multi_node": data.get("_scanner_multi_node", "unknown"),
                "colorwheel": data.get("_scanner_colorwheel", "unknown"),
                "colorwheel_spinner": data.get("_scanner_colorwheel_spinner", "unknown"),
                "defense_capsule": data.get("_scanner_defense_capsule", "unknown"),
                "defense_votes": vote_labels,
                "vector_scores": data.get("_scanner_vector_scores", {}),
                "crypto": oqs_crypto_status(),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            fn = input("Filename to save JSON (default foodwater_scan.json): ").strip() or "foodwater_scan.json"
            Path(fn).write_text(json.dumps(outp, indent=2)); print(f"Saved {fn}")
        try:
            if runtime is not None:
                runtime.close()
        except Exception: pass
        print("Re-encrypting model and removing plaintext...")
        try: encrypt_file(model_path, encrypted_path, state['key']); model_path.unlink()
        except Exception as e: print(f"Cleanup error: {e}")
        input("Enter to return...")

def defense_lab_flow(state:dict):
    data = {"location": "defense lab"}
    metrics = collect_resilient_system_metrics()
    surface = simulate_multi_node_interference(data, metrics)
    capsule = defense_capsule_text(data, metrics, surface)
    colorwheel = render_colorwheel_spinner("Defense lab colorwheel")
    lines = [
        capsule,
        colorwheel,
        scanner_integrity_text(metrics),
        multi_node_surface_text(surface),
        "Vector scores: " + json.dumps(surface.get("vector_scores", {}), sort_keys=True),
        "Recommendations:",
    ]
    lines.extend("- " + rec for rec in defense_recommendations(surface))
    render_screen(
        state,
        "plain",
        "Side-channel Defense Lab",
        "Local anomaly, colorwheel, and defense-pass diagnostics.",
        "Defense Lab",
        lines,
    )
    input("Enter to return...")

async def db_viewer_flow(state:dict):
    if not DB_PATH.exists(): print("No DB found."); input("Enter..."); return
    page=0; per_page=10; search=None
    while True:
        rows = await fetch_history(state['key'], limit=per_page, offset=page*per_page, search=search)
        render_screen(
            state,
            "history",
            "Chat History",
            "Encrypted transcript browser with paging and search.",
        )
        title = f"History (page {page+1})"
        print(boxed(title, [f"Search: {search or '(none)'}", "Commands: n=next p=prev s=search q=quit"]))
        if not rows: print("No rows on this page.")
        else:
            for r in rows: print(f"[{r[0]}] {r[1]}\nQ: {r[2]}\nA: {r[3]}\n" + "-"*60)
        cmd_idx = choose_menu(
            "History Controls",
            ["Next page", "Previous page", "Search", "Back"],
            status=state,
            footer=[f"Current search: {search or '(none)'}"],
        )
        if cmd_idx == 0:
            page += 1
        elif cmd_idx == 1 and page > 0:
            page -= 1
        elif cmd_idx == 2:
            search = input("Enter search keyword (empty to clear): ").strip() or None
            page = 0
        else:
            break

def rekey_flow(state:dict):
    render_screen(
        state,
        "rekey",
        "Rekey / Rotate Key",
        "Re-encrypt stored assets under a fresh key or passphrase.",
    )
    print("Rekey / Rotate Key")
    if KEY_PATH.exists(): print(f"Current key file: {KEY_PATH}")
    else: print("No existing key file (creating new).")
    choice = input("1) New random key  2) Passphrase-derived  3) Cancel\nChoose: ").strip()
    if choice not in ("1","2"): print("Canceled."); input("Enter..."); return
    old_key = state['key']
    tmp_model = MODELS_DIR / (MODEL_FILE + ".tmp"); tmp_db = allocate_temp_db_path()
    try:
        if ENCRYPTED_MODEL.exists():
            try: decrypt_file(ENCRYPTED_MODEL, tmp_model, old_key)
            except Exception as e: print(f"Failed to decrypt model with current key: {e}"); safe_cleanup([tmp_model,tmp_db]); input("Enter..."); return
        if DB_PATH.exists():
            try: decrypt_file(DB_PATH, tmp_db, old_key)
            except Exception as e: print(f"Failed to decrypt DB with current key: {e}"); safe_cleanup([tmp_model,tmp_db]); input("Enter..."); return
    except Exception as e:
        print(f"Unexpected: {e}"); safe_cleanup([tmp_model,tmp_db]); input("Enter..."); return
    if choice=="1":
        new_key = AESGCM.generate_key(256); KEY_PATH.write_bytes(new_key); print("New random key generated and saved.")
    else:
        pw = getpass.getpass("Enter new passphrase: "); pw2 = getpass.getpass("Confirm: ")
        if pw!=pw2: print("Mismatch."); safe_cleanup([tmp_model,tmp_db]); input("Enter..."); return
        salt, derived = derive_key_from_passphrase(pw); KEY_PATH.write_bytes(salt + derived); new_key = derived; print("New passphrase-derived key saved (salt+derived).")
    try:
        if tmp_model.exists():
            old_h = sha256_file(tmp_model)
            encrypt_file(tmp_model, ENCRYPTED_MODEL, new_key)
            new_h_enc = sha256_file(ENCRYPTED_MODEL)
            print(f"Model plaintext SHA256: {old_h}")
            print(f"Encrypted model SHA256: {new_h_enc}")
        if tmp_db.exists():
            old_db_h = sha256_file(tmp_db)
            with tmp_db.open("rb") as f: DB_PATH.write_bytes(aes_encrypt(f.read(), new_key))
            new_db_h = sha256_file(DB_PATH)
            print(f"DB plaintext SHA256: {old_db_h}")
            print(f"Encrypted DB SHA256: {new_db_h}")
    except Exception as e: print(f"Error during re-encryption: {e}")
    finally:
        safe_cleanup([tmp_model,tmp_db])
        state['key'] = KEY_PATH.read_bytes()[16:48] if KEY_PATH.exists() and len(KEY_PATH.read_bytes())>=48 else KEY_PATH.read_bytes()[:32]
        set_app_key(state['key'])
        _load_settings_from_encrypted_db(state['key'])
        state["security_settings"] = read_security_settings()
        state["selected_model"] = read_selected_model_profile()
        state["model_selection_mode"] = read_model_selection_mode()
        print("Rekey attempt finished. Verify files manually."); input("Enter...")

def safe_cleanup(paths:List[Path]):
    for p in paths:
        try:
            if p.exists(): p.unlink()
        except Exception: pass

def main_menu_loop(state:dict):
    options = ["Model Manager", "Settings", "Chat with model", "Food Water Scanner", "Side-channel Defense Lab", "View chat history", "Rekey / Rotate key", "Exit"]
    while True:
        idx = max(0, min(0, len(options) - 1))
        flush_stdin_buffer()
        while True:
            render_screen(
                state,
                "main",
                "Main Menu",
                "Choose a mode and keep moving.",
                "Main Menu",
                menu_lines(options, idx, ["Use ↑↓ / `j``k` / number keys, Enter to select."]),
            )
            ch = getch()
            name = key_name(ch)
            if name == "up":
                idx = (idx - 1) % len(options)
            elif name == "down":
                idx = (idx + 1) % len(options)
            elif name == "enter":
                flush_stdin_buffer()
                break
            elif name == "other":
                try:
                    raw = ch.decode(errors="ignore").strip()
                    if raw.isdigit():
                        choice_num = int(raw)
                        if 1 <= choice_num <= len(options):
                            idx = choice_num - 1
                            flush_stdin_buffer()
                            break
                except Exception:
                    pass
        choice = options[idx]
        if choice == "Model Manager": model_manager(state)
        elif choice == "Settings": settings_flow(state)
        elif choice == "Chat with model": asyncio.run(chat_session(state))
        elif choice == "Food Water Scanner": asyncio.run(road_scanner_flow(state))
        elif choice == "Side-channel Defense Lab": defense_lab_flow(state)
        elif choice == "View chat history": asyncio.run(db_viewer_flow(state))
        elif choice == "Rekey / Rotate key": rekey_flow(state)
        elif choice == "Exit": print("Goodbye."); return

def main():
    try: key = ensure_key_interactive()
    except Exception: key = get_or_create_key()
    set_app_key(key)
    try:
        asyncio.run(init_db(key))
    except Exception:
        pass
    settings = read_security_settings()
    selected = read_selected_model_profile()
    if not is_model_enabled(selected, settings):
        selected = first_enabled_model_profile(settings)
        write_selected_model_profile(selected)
    state = {"key": key, "model_loaded": False, "selected_model": selected, "model_selection_mode": read_model_selection_mode(), "security_settings": settings}
    try:
        main_menu_loop(state)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        show_cursor()

if __name__=="__main__":
    main()
