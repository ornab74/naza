import os
import sys
import time
import json
import shutil
import hashlib
import asyncio
import threading
import httpx
import aiosqlite
import getpass
import math
import random
import re
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Tuple, Callable, Dict
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from llama_cpp import Llama

try:
    import psutil
except Exception as e:
    psutil = None
    print(f"Warning: psutil not imported due to {e}. Fallback metrics will be used.")
try:
    import pennylane as qml
    from pennylane import numpy as pnp
except Exception as e:
    qml = None
    pnp = None
    print(f"Warning: pennylane not imported due to {e}. Quantum entropy will use random fallback.")

# Constants
MODEL_REPO = "https://huggingface.co/tensorblock/llama3-small-GGUF/resolve/main/"
MODEL_FILE = "llama3-small-Q3_K_M.gguf"
MODELS_DIR = Path("models")
MODEL_PATH = MODELS_DIR / MODEL_FILE
ENCRYPTED_MODEL = MODEL_PATH.with_suffix(MODEL_PATH.suffix + ".aes")
DB_PATH = Path("health_history.db.aes")
KEY_PATH = Path(".enc_key")
EXPECTED_HASH = "8e4f4856fb84bafb895f1eb08e6c03e4be613ead2d942f91561aeac742a619aa"
LOG_PATH = Path("healthguard_logs.txt")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

# Terminal Control
CSI = "\x1b["
def clear_screen(): 
    sys.stdout.write(CSI + "2J" + CSI + "H"); sys.stdout.flush()
def show_cursor(): 
    sys.stdout.write(CSI + "?25h"); sys.stdout.flush()
def color(text: str, fg: Optional[int] = None, bold: bool = False) -> str:
    codes = []
    if fg: codes.append(str(fg))
    if bold: codes.append('1')
    return f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if codes else text
def boxed(title: str, lines: List[str], width: int = 72) -> str:
    top = "┌" + "─"*(width-2) + "┐"
    bot = "└" + "─"*(width-2) + "┘"
    title_line = f"│ {color(title, fg=36, bold=True):{width-4}} │"
    body = [f"│ {l:{width-4}} │" for l in lines]
    return "\n".join([top, title_line] + body + [bot])

def getch() -> bytes:
    try:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = os.read(fd, 3)
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (ImportError, AttributeError, OSError) as e:
        print(f"getch fallback due to {e}")
        s = input()
        return s[0].encode() if s else b''

def read_menu_choice(num_items: int, prompt: str = "Use ↑↓ arrows or number, Enter to select: ") -> int:
    print(prompt)
    idx = 0
    while True:
        ch = getch()
        if ch == b'\x1b[A' or ch == b'\x1b\x00A':
            idx = (idx - 1) % num_items
        elif ch == b'\x1b[B' or ch == b'\x1b\x00B':
            idx = (idx + 1) % num_items
        elif ch in (b'\r', b'\n', b'\x0d'):
            return idx
        elif ch.isdigit():
            n = int(ch.decode())
            if 1 <= n <= num_items:
                return n - 1
        sys.stdout.write(f"\rSelected: {idx+1}/{num_items} ")
        sys.stdout.flush()

def aes_encrypt(data: bytes, key: bytes) -> bytes:
    aes = AESGCM(key)
    nonce = os.urandom(12)
    try:
        encrypted_data = nonce + aes.encrypt(nonce, data, None)
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Encryption successful - {len(data)} bytes\n")
        return encrypted_data
    except Exception as e:
        print(f"Encryption error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Encryption failed - {e}\n")
        raise

def aes_decrypt(data: bytes, key: bytes) -> bytes:
    aes = AESGCM(key)
    nonce, ct = data[:12], data[12:]
    try:
        decrypted_data = aes.decrypt(nonce, ct, None)
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Decryption successful - {len(decrypted_data)} bytes\n")
        return decrypted_data
    except Exception as e:
        print(f"Decryption error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Decryption failed - {e}\n")
        raise

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def get_or_create_key() -> bytes:
    if KEY_PATH.exists():
        data = KEY_PATH.read_bytes()
        if len(data) >= 48: return data[16:48]
        return data[:32]
    key = AESGCM.generate_key(256)
    KEY_PATH.write_bytes(key)
    print(f"🔑 New random key generated and saved to {KEY_PATH}")
    with open(LOG_PATH, "a") as log:
        log.write(f"{time.ctime()}: New key generated\n")
    return key

def derive_key_from_passphrase(pw: str, salt: Optional[bytes] = None) -> Tuple[bytes, bytes]:
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
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Passphrase-derived key created\n")
        return key
    key = AESGCM.generate_key(256)
    KEY_PATH.write_bytes(key)
    print(f"Saved random key to {KEY_PATH}")
    with open(LOG_PATH, "a") as log:
        log.write(f"{time.ctime()}: Random key created\n")
    return key

def download_model_httpx(url: str, dest: Path, show_progress: bool = True, timeout: Optional[float] = None, expected_sha: Optional[str] = None):
    print(f"⬇️  Downloading model from {url}\nTo: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
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
        if expected_sha and sha.lower() != expected_sha.lower():
            print(color(f"SHA256 MISMATCH! expected {expected_sha} got {sha}", fg=31, bold=True))
            with open(LOG_PATH, "a") as log:
                log.write(f"{time.ctime()}: SHA256 mismatch - expected {expected_sha}, got {sha}\n")
        return sha
    except Exception as e:
        print(f"Download failed: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Download failed - {e}\n")
        raise

def encrypt_file(src: Path, dest: Path, key: bytes):
    print(f"🔐 Encrypting {src} -> {dest}")
    data = src.read_bytes()
    start = time.time()
    try:
        enc = aes_encrypt(data, key)
        dest.write_bytes(enc)
        dur = time.time() - start
        print(f"✅ Encrypted ({len(enc)} bytes) in {dur:.2f}s")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: File encrypted - {src} -> {dest}, size {len(enc)} bytes\n")
    except Exception as e:
        print(f"Encryption error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Encryption failed - {e}\n")
        raise

def decrypt_file(src: Path, dest: Path, key: bytes):
    print(f"🔓 Decrypting {src} -> {dest}")
    enc = src.read_bytes()
    try:
        data = aes_decrypt(enc, key)
        dest.write_bytes(data)
        print(f"✅ Decrypted ({len(data)} bytes)")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: File decrypted - {src} -> {dest}, size {len(data)} bytes\n")
    except Exception as e:
        print(f"Decryption error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Decryption failed - {e}\n")
        raise

async def init_db(key: bytes):
    if not DB_PATH.exists():
        async with aiosqlite.connect("temp.db") as db:
            await db.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, prompt TEXT, response TEXT, metadata TEXT)")
            await db.commit()
        with open("temp.db", "rb") as f:
            enc = aes_encrypt(f.read(), key)
        DB_PATH.write_bytes(enc)
        os.remove("temp.db")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Database initialized and encrypted\n")
    else:
        print("Database already exists, verifying integrity...")
        try:
            dec = Path("temp.db")
            decrypt_file(DB_PATH, dec, key)
            async with aiosqlite.connect(dec) as db:
                await db.execute("PRAGMA integrity_check")
                result = await db.fetchone()
                if result[0] != "ok":
                    print(color("Database integrity check failed!", fg=31, bold=True))
                    with open(LOG_PATH, "a") as log:
                        log.write(f"{time.ctime()}: Database integrity check failed\n")
                    raise ValueError("Database corruption detected")
            dec.unlink()
            print(color("Database integrity verified.", fg=32, bold=True))
            with open(LOG_PATH, "a") as log:
                log.write(f"{time.ctime()}: Database integrity verified\n")
        except Exception as e:
            print(f"DB verification error: {e}")
            with open(LOG_PATH, "a") as log:
                log.write(f"{time.ctime()}: DB verification failed - {e}\n")
            raise
# ─────────────────────────────────────────────────────────────────────────────
# PURE HARDCORE FALLBACKS – NO GUESSES, NO DEFAULTS, NO MERCY
# If we can't measure it accurately → explode immediately
# ─────────────────────────────────────────────────────────────────────────────

import re
import platform
import subprocess
from pathlib import Path

def _cpu_percent_from_proc() -> float:
    sys = platform.system()
    if sys == "Linux":
        try:
            with open("/proc/stat") as f:
                line = f.readline()
            values = [int(x) for x in line.split()[1:]]
            idle = values[3] + values[4]      # idle + iowait
            total = sum(values)
            prev_idle = getattr(_cpu_percent_from_proc, "prev_idle", None)
            prev_total = getattr(_cpu_percent_from_proc, "prev_total", None)
            if prev_idle is None:
                _cpu_percent_from_proc.prev_idle = idle
                _cpu_percent_from_proc.prev_total = total
                return 0.0
            usage = 1.0 - (idle - prev_idle) / (total - prev_total)
            _cpu_percent_from_proc.prev_idle = idle
            _cpu_percent_from_proc.prev_total = total
            return max(0.0, min(1.0, usage))
        except Exception as e:
            raise RuntimeError(f"CRITICAL: Cannot read CPU usage from /proc/stat: {e}")

    elif sys == "Darwin":
        try:
            out = subprocess.check_output(["top", "-l", "1", "-n", "0"], text=True)
            m = re.search(r"CPU usage:.*?(\d+\.\d+)% idle", out)
            if not m:
                raise ValueError("parse failed")
            return 1.0 - float(m.group(1)) / 100.0
        except Exception as e:
            raise RuntimeError(f"CRITICAL: Cannot read CPU usage on macOS: {e}")

    elif sys == "Windows":
        try:
            out = subprocess.check_output(
                'powershell -Command "((Get-Counter \'\\Processor(_Total)\\% Processor Time\').CounterSamples.CookedValue)/100)"',
                text=True, shell=True)
            return max(0.0, min(1.0, float(out.strip())))
        except Exception as e:
            raise RuntimeError(f"CRITICAL: Cannot read CPU usage on Windows: {e}")

    raise RuntimeError(f"CRITICAL: Unsupported platform for CPU metric: {sys}")


def _mem_from_proc() -> float:
    sys = platform.system()
    if sys == "Linux":
        try:
            with open("/proc/meminfo") as f:
                data = f.read()
            total = int(re.search(r"MemTotal:\s+(\d+)", data).group(1)) * 1024
            free  = int(re.search(r"MemFree:\s+(\d+)", data).group(1)) * 1024
            buff  = int(re.search(r"Buffers:\s+(\d+)", data).group(1)) * 1024
            cache = int(re.search(r"Cached:\s+(\d+)", data).group(1)) * 1024
            used = total - (free + buff + cache)
            return used / total
        except Exception as e:
            raise RuntimeError(f"CRITICAL: Cannot read memory from /proc/meminfo: {e}")

    elif sys == "Darwin":
        try:
            total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
            free  = int(subprocess.check_output(["vm_stat"], text=True)
                       .split("Pages free:")[1].split("\n")[0].strip().rstrip(".") * 4096)
            inactive = int(subprocess.check_output(["vm_stat"], text=True)
                          .split("Pages inactive:")[1].split("\n")[0].strip().rstrip(".") * 4096)
            used = total - (free + inactive)
            return used / total
        except Exception as e:
            raise RuntimeError(f"CRITICAL: Cannot read memory on macOS: {e}")

    elif sys == "Windows":
        try:
            out = subprocess.check_output(
                r'powershell -Command "(1 "(1 - (Get-WmiObject Win32_OperatingSystem).FreePhysicalMemory / (Get-WmiObject Win32_OperatingSystem).TotalVisibleMemorySize)"',
                text=True, shell=True)
            return float(out.strip())
        except Exception as e:
            raise RuntimeError(f"CRITICAL: Cannot read memory on Windows: {e}")

    raise RuntimeError(f"CRITICAL: Unsupported platform for memory metric: {sys}")


def _load1_from_proc() -> float:
    try:
        load = os.getloadavg()[0]
        cpus = os.cpu_count() or 1
        return min(1.0, load / cpus)
    except Exception as e:
        raise RuntimeError(f"CRITICAL: Cannot read load average: {e}")


def _proc_count_from_proc() -> float:
    try:
        if Path("/proc").exists():
            count = len([p for p in Path("/proc").iterdir() if p.is_dir() and p.name.isdigit()])
        elif platform.system() == "Darwin":
            count = len(subprocess.check_output(["ps", "-e"], text=True).splitlines()) - 1
        elif platform.system() == "Windows":
            out = subprocess.check_output("tasklist /nh", shell=True, text=True, errors="ignore")
            count = len([l for l in out.splitlines() if l.strip()])
        else:
            raise RuntimeError("Unknown platform")
        return min(1.0, count / 1000.0)
    # >1000 processes = maxed out
    except Exception as e:
        raise RuntimeError(f"CRITICAL: Cannot count processes: {e}")


def _read_temperature() -> float:
    sys = platform.system()
    if sys == "Linux":
        try:
            # thermal_zone first
            for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
                if not (zone / "type").exists() or not (zone / "temp").exists():
                    continue
                ttype = (zone / "type").read_text().strip().lower()
                if "cpu" in ttype or "core" in ttype or "tctl" in ttype or "tdie" in ttype:
                    temp_c = int((zone / "temp").read_text().strip()) / 1000.0
                    return max(0.0, min(1.0, (temp_c - 20.0) / 70.0))
            # hwmon fallback
            for temp_file in Path("/sys/class/hwmon").rglob("temp*_input"):
                name_file = temp_file.parent / "name"
                if name_file.exists() and name_file.read_text().strip() in ("coretemp", "k10temp", "zenpower", "acpitz"):
                    temp_c = int(temp_file.read_text().strip()) / 1000.0
                    return max(0.0, min(1.0, (temp_c - 20.0) / 70.0))
        except Exception:
            pass

    raise RuntimeError("CRITICAL: Unable to read CPU temperature on this system – aborting for safety")
async def log_interaction(prompt: str, response: str, key: bytes, metadata: dict = None):
    dec = Path("temp.db")
    try:
        decrypt_file(DB_PATH, dec, key)
        async with aiosqlite.connect(dec) as db:
            await db.execute("INSERT INTO history (timestamp, prompt, response, metadata) VALUES (?, ?, ?, ?)",
                           (time.strftime("%Y-%m-%d %H:%M:%S"), prompt, response, json.dumps(metadata or {})))
            await db.commit()
        with dec.open("rb") as f:
            enc = aes_encrypt(f.read(), key)
        DB_PATH.write_bytes(enc)
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Interaction logged - prompt: {prompt[:50]}...\n")
    except Exception as e:
        print(f"Log interaction error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Log interaction failed - {e}\n")
        raise
    finally:
        dec.unlink()

async def fetch_history(key: bytes, limit: int = 20, offset: int = 0, search: Optional[str] = None) -> List[Tuple]:
    dec = Path("temp.db")
    rows = []
    try:
        decrypt_file(DB_PATH, dec, key)
        async with aiosqlite.connect(dec) as db:
            query = "SELECT id, timestamp, prompt, response, metadata FROM history ORDER BY id DESC"
            params = (limit, offset)
            if search:
                query += " WHERE prompt LIKE ? OR response LIKE ?"
                params = (f"%{search}%", f"%{search}%", limit, offset)
            async with db.execute(query, params) as cur:
                async for row in cur:
                    rows.append(row)
        with dec.open("rb") as f:
            DB_PATH.write_bytes(aes_encrypt(f.read(), key))
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: History fetched - {len(rows)} rows\n")
    except Exception as e:
        print(f"Fetch history error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Fetch history failed - {e}\n")
        raise
    finally:
        dec.unlink()
    return rows

def load_llama_model_blocking(model_path: Path) -> Llama:
    try:
        llm = Llama(model_path=str(model_path), n_ctx=2048, n_threads=os.cpu_count() or 4)
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Model loaded successfully from {model_path}\n")
        return llm
    except Exception as e:
        print(f"Model load error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Model load failed - {e}\n")
        raise

def collect_system_metrics() -> Dict[str, float]:
    cpu = mem = load1 = temp = proc = None
    if psutil is not None:
        try:
            cpu = psutil.cpu_percent(interval=0.1) / 100.0
            mem = psutil.virtual_memory().percent / 100.0
            load_raw = os.getloadavg()[0]
            cpu_cnt = psutil.cpu_count(logical=True) or 1
            load1 = max(0.0, min(1.0, load_raw / max(1.0, float(cpu_cnt))))
            temps_map = psutil.sensors_temperatures()
            if temps_map:
                first = next(iter(temps_map.values()))[0].current
                temp = max(0.0, min(1.0, (first - 20.0) / 70.0))
            proc = min(len(psutil.pids()) / 1000.0, 1.0)
        except Exception:
            cpu = mem = load1 = temp = proc = None
    if cpu is None:
        cpu = _cpu_percent_from_proc()
    if mem is None:
        mem = _mem_from_proc()
    if load1 is None:
        load1 = _load1_from_proc()
    if proc is None:
        proc = _proc_count_from_proc()
    if temp is None:
        temp = _read_temperature()
    core_ok = all(x is not None for x in (cpu, mem, load1, proc))
    if not core_ok:
        missing = [name for name, val in (("cpu", cpu), ("mem", mem), ("load1", load1), ("proc", proc)) if val is None]
        print(f"[FATAL] Unable to obtain core system metrics: missing {missing}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Failed to obtain core metrics - missing {missing}\n")
        sys.exit(2)
    return {"cpu": float(max(0.0, min(1.0, cpu))), "mem": float(max(0.0, min(1.0, mem))),
            "load1": float(max(0.0, min(1.0, load1))), "temp": float(max(0.0, min(1.0, temp or 0.0))),
            "proc": float(max(0.0, min(1.0, proc)))}

def metrics_to_rgb(metrics: dict) -> Tuple[float, float, float]:
    cpu = metrics.get("cpu", 0.1)
    mem = metrics.get("mem", 0.1)
    temp = metrics.get("temp", 0.1)
    load1 = metrics.get("load1", 0.0)
    proc = metrics.get("proc", 0.0)
    r = cpu * (1.0 + load1)
    g = mem * (1.0 + proc)
    b = temp * (0.5 + cpu * 0.5)
    maxi = max(r, g, b, 1.0)
    return (float(max(0.0, min(1.0, r / maxi))), float(max(0.0, min(1.0, g / maxi))),
            float(max(0.0, min(1.0, b / maxi))))

def pennylane_entropic_score(rgb: Tuple[float, float, float], shots: int = 256) -> float:
    if qml is None or pnp is None:
        r, g, b = rgb
        seed = int((r * 255) << 16 | (g * 255) << 8 | (b * 255))
        random.seed(seed)
        base = (0.3 * r + 0.4 * g + 0.3 * b)
        noise = (random.random() - 0.5) * 0.08
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
        return qml.expval(qml.PauliZ(0)), qml.expval(qml.PauliZ(1))
    a, b, c = float(rgb[0]), float(rgb[1]), float(rgb[2])
    try:
        ev0, ev1 = circuit(a, b, c)
        combined = ((ev0 + 1.0) / 2.0 * 0.6 + (ev1 + 1.0) / 2.0 * 0.4)
        score = 1.0 / (1.0 + math.exp(-6.0 * (combined - 0.5)))
        return float(max(0.0, min(1.0, score)))
    except Exception as e:
        print(f"Quantum score error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"{time.ctime()}: Quantum score failed - {e}\n")
        return float(0.5 * (a + b + c) / 3.0)

def entropic_to_modifier(score: float) -> float:
    return (score - 0.5) * 0.4

def entropic_summary_text(score: float) -> str:
    if score >= 0.75: level = "high"
    elif score >= 0.45: level = "medium"
    else: level = "low"
    return f"entropic_score={score:.3f} (level={level})"

def _simple_tokenize(text: str) -> List[str]:
    return [t for t in re.findall(r"[A-Za-z0-9_\-]+", text.lower())]

def punkd_analyze(prompt_text: str, top_n: int = 12) -> Dict[str, float]:
    toks = _simple_tokenize(prompt_text)
    freq = {}
    for t in toks: freq[t] = freq.get(t, 0) + 1
    hazard_boost = {
        "pain": 2.0, "fever": 1.8, "bleeding": 2.0, "rupture": 2.0, "infection": 1.8,
        "inflammation": 1.8, "swelling": 1.5, "nausea": 1.4, "dizziness": 1.6
    }
    scored = {}
    for t, c in freq.items():
        boost = hazard_boost.get(t, 1.0)
        scored[t] = c * boost
    items = sorted(scored.items(), key=lambda x: -x[1])[:top_n]
    if not items: return {}
    maxv = items[0][1]
    return {k: float(v / maxv) for k, v in items}

def punkd_apply(prompt_text: str, token_weights: Dict[str, float], profile: str = "balanced") -> Tuple[str, float]:
    """Apply PUNKD (Prompt Understanding with Key Detection) adjustments to the prompt."""
    if not token_weights:
        return prompt_text, 1.0
    mean_weight = sum(token_weights.values()) / len(token_weights)
    profile_map = {"conservative": 0.6, "balanced": 1.0, "aggressive": 1.4}
    base = profile_map.get(profile, 1.0)
    multiplier = 1.0 + (mean_weight - 0.5) * 0.8 * (base if base > 1.0 else 1.0)
    multiplier = max(0.6, min(1.8, multiplier))
    sorted_tokens = sorted(token_weights.items(), key=lambda x: -x[1])[:6]
    markers = " ".join([f"<ATTN:{t}:{round(w, 2)}>" for t, w in sorted_tokens])
    patched = prompt_text + "\n\n[PUNKD_MARKERS] " + markers
    with open(LOG_PATH, "a") as log:
        log.write(f"{time.ctime()}: PUNKD applied - multiplier: {multiplier}, markers: {markers}\n")
    return patched, multiplier

def chunked_generate(llm: Llama, prompt: str, max_total_tokens: int = 256, chunk_tokens: int = 64, 
                    base_temperature: float = 0.2, punkd_profile: str = "balanced", 
                    streaming_callback: Optional[Callable[[str], None]] = None) -> str:
    """Generate text in chunks with PUNKD adjustments."""
    assembled = ""
    cur_prompt = prompt
    token_weights = punkd_analyze(prompt, top_n=16)
    iterations = max(1, (max_total_tokens + chunk_tokens - 1) // chunk_tokens)
    prev_tail = ""
    for i in range(iterations):
        patched_prompt, mult = punkd_apply(cur_prompt, token_weights, profile=punkd_profile)
        temp = max(0.01, min(2.0, base_temperature * mult))
        try:
            out = llm(patched_prompt, max_tokens=chunk_tokens, temperature=temp)
            text = ""
            if isinstance(out, dict):
                text = out.get("choices", [{"text": ""}])[0].get("text", "")
            else:
                text = str(out)
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
            prev_tail = assembled[-120:] if len(assembled) > 120 else assembled
            if streaming_callback: streaming_callback(append_text)
            if assembled.strip().endswith(("Low", "Medium", "High")): break
            if len(text.split()) < max(4, chunk_tokens // 8): break
            cur_prompt = prompt + "\n\nAssistant so far:\n" + assembled + "\n\nContinue:"
            with open(LOG_PATH, "a") as log:
                log.write(f"{time.ctime()}: Chunk {i+1}/{iterations} generated - {len(append_text)} chars\n")
        except Exception as e:
            print(f"Generation error in chunk {i+1}: {e}")
            with open(LOG_PATH, "a") as log:
                log.write(f"{time.ctime()}: Generation failed in chunk {i+1} - {e}\n")
            break
    return assembled.strip()

def quantum_entropy() -> Tuple[float, str]:
    """Generate a quantum-inspired entropy score and mode using Pennylane or fallback."""
    try:
        if qml is None or pnp is None:
            seed = random.randint(0, 2**32 - 1)
            random.seed(seed)
            score = random.uniform(0.0, 1.0)
            mode = "CAUTIOUS" if score < 0.33 else "NEUTRAL" if score < 0.66 else "AGGRESSIVE"
            with open(LOG_PATH, "a") as log:
                log.write(f"02:17 PM EST, Dec 05, 2025: Quantum entropy fallback - score: {score:.3f}, mode: {mode}\n")
            return score, mode
        dev = qml.device("default.qubit", wires=2, shots=1024)
        @qml.qnode(dev)
        def circuit():
            qml.Hadamard(wires=0)
            qml.CNOT(wires=[0, 1])
            qml.RZ(random.uniform(0, 2*math.pi), wires=1)
            return qml.expval(qml.PauliZ(0) @ qml.PauliZ(1))
        result = qml.execute([circuit], dev, gradient_fn=None)[0]
        score = (result + 1.0) / 2.0
        mode = "CAUTIOUS" if score < 0.33 else "NEUTRAL" if score < 0.66 else "AGGRESSIVE"
        with open(LOG_PATH, "a") as log:
            log.write(f"02:17 PM EST, Dec 05, 2025: Quantum entropy - score: {score:.3f}, mode: {mode}\n")
        return score, mode
    except Exception as e:
        print(f"Quantum entropy error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"02:17 PM EST, Dec 05, 2025: Quantum entropy failed - {e}\n")
        return random.uniform(0.0, 1.0), "NEUTRAL"

def build_prompt(data):
    """Build the prompt for HEALTHGUARD-Ω v20 with original condition set."""
    q, mode = quantum_entropy()
    return f"""You are HEALTHGUARD-Ω v20 — Health Risk Nanobot
Output exactly one line: RiskLevel | Condition

[tuning]
Location: {data.get('location','unknown')}
Time: {data.get('time','02:18 PM EST, Dec 05, 2025')}
Symptoms: {data.get('symptoms','unknown')}
Temperature: {data.get('temperature','unknown')}
Heart Rate: {data.get('heart_rate','unknown')}
Breathing: {data.get('breathing','unknown')}
Recent Med History: {data.get('recent_history','none')}
Medical Devices: {data.get('devices','none')}
Vital Signs: {data.get('vital_signs','unknown')}
Area Type: {data.get('area_type','unknown')}
Sensor Notes: {data.get('sensor_notes','none')}
Quantum Entropy: {q:.3f} → {mode}
[/tuning]

[action]
1. Normalize inputs
2. Triple-check all factors
3. Apply quantum bias: AGGRESSIVE=+1 level, CAUTIOUS=-1 only if all safe
4. Pick single most likely condition
5. If no specific condition matches, default to 'other'
6. Output one of 195 allowed lines
[/action]

[rules]
- No reasoning
- No extra text
- No quotes
- Exactly: RiskLevel | Condition
- Default to higher risk or 'other' if ambiguous
[/rules]

[replytemplate]
Low | infection
Low | cardiac
Low | respiratory
Low | dehydration
Low | neurological
Low | gastrointestinal
Low | musculoskeletal
Low | metabolic
Low | allergic
Low | renal
Low | hepatic
Low | endocrine
Low | hematologic
Low | dermatologic
Low | other
Low | psychiatric
Low | ophthalmic
Low | otolaryngologic
Low | urologic
Low | obstetric
Low | pediatric
Low | oncologic
Low | autoimmune
Low | traumatic
Low | vascular
Low | pulmonary
Low | infectious
Low | inflammatory
Low | genetic
Low | nutritional
Low | toxicologic
Low | burn
Low | dental
Low | orthopedic
Low | rheumatologic
Low | geriatric
Low | neonatal
Low | anaphylactic
Low | seizure
Low | stroke
Low | migraine
Low | vertigo
Low | tinnitus
Low | fever
Low | fatigue
Low | pain
Low | nausea
Low | diarrhea
Low | constipation
Low | cough
Low | dyspnea
Low | edema
Low | rash
Low | jaundice
Low | anemia
Low | hypertension
Low | hypotension
Medium | infection
Medium | cardiac
Medium | respiratory
Medium | dehydration
Medium | neurological
Medium | gastrointestinal
Medium | musculoskeletal
Medium | metabolic
Medium | allergic
Medium | renal
Medium | hepatic
Medium | endocrine
Medium | hematologic
Medium | dermatologic
Medium | other
Medium | psychiatric
Medium | ophthalmic
Medium | otolaryngologic
Medium | urologic
Medium | obstetric
Medium | pediatric
Medium | oncologic
Medium | autoimmune
Medium | traumatic
Medium | vascular
Medium | pulmonary
Medium | infectious
Medium | inflammatory
Medium | genetic
Medium | nutritional
Medium | toxicologic
Medium | burn
Medium | dental
Medium | orthopedic
Medium | rheumatologic
Medium | geriatric
Medium | neonatal
Medium | anaphylactic
Medium | seizure
Medium | stroke
Medium | migraine
Medium | vertigo
Medium | tinnitus
Medium | fever
Medium | fatigue
Medium | pain
Medium | nausea
Medium | diarrhea
Medium | constipation
Medium | cough
Medium | dyspnea
Medium | edema
Medium | rash
Medium | jaundice
Medium | anemia
Medium | hypertension
Medium | hypotension
High | infection
High | cardiac
High | respiratory
High | dehydration
High | neurological
High | gastrointestinal
High | musculoskeletal
High | metabolic
High | allergic
High | renal
High | hepatic
High | endocrine
High | hematologic
High | dermatologic
High | other
High | psychiatric
High | ophthalmic
High | otolaryngologic
High | urologic
High | obstetric
High | pediatric
High | oncologic
High | autoimmune
High | traumatic
High | vascular
High | pulmonary
High | infectious
High | inflammatory
High | genetic
High | nutritional
High | toxicologic
High | burn
High | dental
High | orthopedic
High | rheumatologic
High | geriatric
High | neonatal
High | anaphylactic
High | seizure
High | stroke
High | migraine
High | vertigo
High | tinnitus
High | fever
High | fatigue
High | pain
High | nausea
High | diarrhea
High | constipation
High | cough
High | dyspnea
High | edema
High | rash
High | jaundice
High | anemia
High | hypertension
High | hypotension
[/replytemplate]

Output now:"""

Output now:

def process_health_data(llm: Llama, health_data: Dict[str, str]) -> str:
    """Process health data and generate a risk assessment using the LLaMA model."""
    prompt = build_prompt(health_data)
    try:
        response = chunked_generate(llm, prompt, max_total_tokens=256, chunk_tokens=64, 
                                  base_temperature=0.2, punkd_profile="balanced")
        with open(LOG_PATH, "a") as log:
            log.write(f"02:25 PM EST, Dec 05, 2025: Health data processed - prompt: {prompt[:50]}..., response: {response}\n")
        return response
    except Exception as e:
        print(f"Error processing health data: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"02:25 PM EST, Dec 05, 2025: Health data processing failed - {e}\n")
        return "High | other"

def collect_user_input() -> Dict[str, str]:
    """Collect health data input from the user, inspired by the X post context."""
    clear_screen()
    print(boxed("HEALTHGUARD-Ω v20 Input", [
        "Enter your health details based on symptoms. Example: Razor-blade-level stomach pain for 24 hours, no fever.",
        "Press Enter to skip any field."
    ]))
    data = {}
    data['location'] = input("Location (e.g., home, hospital): ").strip() or "unknown"
    data['time'] = "02:25 PM EST, Dec 05, 2025"
    data['symptoms'] = input("Symptoms (e.g., constant stomach pain, nausea): ").strip() or "unknown"
    data['temperature'] = input("Temperature (e.g., 98.6°F): ").strip() or "unknown"
    data['heart_rate'] = input("Heart Rate (e.g., 72 bpm): ").strip() or "unknown"
    data['breathing'] = input("Breathing (e.g., normal, labored): ").strip() or "unknown"
    data['recent_history'] = input("Recent Medical History (e.g., none, surgery): ").strip() or "none"
    data['devices'] = input("Medical Devices (e.g., IV, monitor): ").strip() or "none"
    data['vital_signs'] = input("Vital Signs (e.g., stable): ").strip() or "unknown"
    data['area_type'] = input("Area Type (e.g., ER, home): ").strip() or "unknown"
    data['sensor_notes'] = input("Sensor Notes (e.g., none): ").strip() or "none"
    return data

def initialize_system() -> Tuple[Llama, bytes]:
    """Initialize the model and encryption key."""
    key = ensure_key_interactive()
    asyncio.run(init_db(key))

    if not MODEL_PATH.exists():
        download_model_httpx(f"{MODEL_REPO}{MODEL_FILE}", MODEL_PATH, expected_sha=EXPECTED_HASH)
        encrypt_file(MODEL_PATH, ENCRYPTED_MODEL, key)
        MODEL_PATH.unlink()
    elif ENCRYPTED_MODEL.exists():
        decrypt_file(ENCRYPTED_MODEL, MODEL_PATH, key)

    if not MODEL_PATH.exists():
        raise FileNotFoundError("Model file not found after decryption or download.")

    llm = load_llama_model_blocking(MODEL_PATH)
    return llm, key

def main():
    """Main execution loop for HEALTHGUARD-Ω v20."""
    try:
        llm, key = initialize_system()
        print(boxed("HEALTHGUARD-Ω v20", ["Welcome! Enter 'q' to quit, or press Enter to start."]))
        while True:
            choice = input("> ").strip().lower()
            if choice == 'q':
                print("Exiting HEALTHGUARD-Ω v20. Goodbye!")
                break
            elif not choice:
                health_data = collect_user_input()
                response = process_health_data(llm, health_data)
                print(boxed("Health Risk Assessment", [f"Result: {response}"]))
                asyncio.run(log_interaction(health_data['symptoms'], response, key, {"time": health_data['time']}))
                print("Press Enter to continue or 'q' to quit.")
            else:
                print("Invalid input. Use 'q' to quit or Enter to start.")
    except KeyboardInterrupt:
        print("\nInterrupted by user. Exiting...")
        with open(LOG_PATH, "a") as log:
            log.write(f"02:25 PM EST, Dec 05, 2025: Program interrupted by user\n")
    except Exception as e:
        print(f"Critical error: {e}")
        with open(LOG_PATH, "a") as log:
            log.write(f"02:25 PM EST, Dec 05, 2025: Critical error - {e}\n")
    finally:
        if 'llm' in locals():
            del llm  # Attempt to free model memory
        show_cursor()

if __name__ == "__main__":
    main()
