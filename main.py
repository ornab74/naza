import os, sys, time, json, shutil, hashlib, asyncio, threading, httpx, aiosqlite, getpass, math, random, re, tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, List, Tuple, Callable, Dict
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from llama_cpp import Llama

try:
    import psutil
except Exception:
    psutil = None
try:
    import pennylane as qml
    from pennylane import numpy as pnp
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
EXPECTED_HASH = "8e4f4856fb84bafb895f1eb08e6c03e4be613ead2d942f91561aeac742a619aa"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

CSI = "\x1b["


def clear_screen():
    sys.stdout.write(CSI + "2J" + CSI + "H")


def show_cursor():
    sys.stdout.write(CSI + "?25h")


def color(text, fg=None, bold=False):
    codes = []
    if fg:
        codes.append(str(fg))
    if bold:
        codes.append("1")
    if not codes:
        return text
    return f"\x1b[{';'.join(codes)}m{text}\x1b[0m"


def boxed(title: str, lines: List[str], width: int = 72):
    top = "┌" + "─" * (width - 2) + "┐"
    bot = "└" + "─" * (width - 2) + "┘"
    title_line = f"│ {color(title, fg=36, bold=True):{width-4}} │"
    body = []
    for l in lines:
        if len(l) > width - 4:
            chunks = [l[i:i + width - 4] for i in range(0, len(l), width - 4)]
        else:
            chunks = [l]
        for c in chunks:
            body.append(f"│ {c:{width-4}} │")
    return "\n".join([top, title_line] + body + [bot])


def getch():
    try:
        import tty, termios
    except Exception:
        return sys.stdin.read(1).encode()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 3)
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_menu_choice(num_items: int, prompt="Use ↑↓ arrows or number, Enter to select: ") -> int:
    print(prompt)
    try:
        idx = 0
        while True:
            ch = getch()
            if not ch:
                continue
            if ch == b'\x1b[A' or ch == b'\x1b\x00A':
                idx = (idx - 1) % num_items
            elif ch == b'\x1b[B' or ch == b'\x1b\x00B':
                idx = (idx + 1) % num_items
            elif ch in (b'\r', b'\n', b'\x0d'):
                return idx
            else:
                try:
                    s = ch.decode(errors='ignore')
                    if s.strip().isdigit():
                        n = int(s.strip())
                        if 1 <= n <= num_items:
                            return n - 1
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
                    return n - 1


def aes_encrypt(data: bytes, key: bytes) -> bytes:
    aes = AESGCM(key)
    nonce = os.urandom(12)
    return nonce + aes.encrypt(nonce, data, None)


def aes_decrypt(data: bytes, key: bytes) -> bytes:
    aes = AESGCM(key)
    nonce, ct = data[:12], data[12:]
    return aes.decrypt(nonce, ct, None)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def get_or_create_key() -> bytes:
    if KEY_PATH.exists():
        d = KEY_PATH.read_bytes()
        if len(d) >= 48:
            return d[16:48]
        return d[:32]
    key = AESGCM.generate_key(256)
    KEY_PATH.write_bytes(key)
    print(f"🔑 New random key generated and saved to {KEY_PATH}")
    return key


def derive_key_from_passphrase(pw: str, salt: Optional[bytes] = None) -> Tuple[bytes, bytes]:
    if salt is None:
        salt = os.urandom(16)
    kdf_der = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000
    )
    derived = kdf_der.derive(pw.encode("utf-8"))
    return salt, derived


def ensure_key_interactive() -> bytes:
    if KEY_PATH.exists():
        data = KEY_PATH.read_bytes()
        if len(data) >= 48:
            return data[16:48]
        if len(data) >= 32:
            return data[:32]

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


def download_model_httpx(url: str, dest: Path, show_progress=True, timeout=None, expected_sha: Optional[str] = None):
    print(f"⬇️  Downloading model from {url}\nTo: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        h = hashlib.sha256()
        with dest.open("wb") as f:
            for chunk in r.iter_bytes(chunk_size=8192):
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if total and show_progress:
                    pct = done / total * 100
                    bar = int(pct // 2)
                    sys.stdout.write(
                        f"\r[{('#' * bar).ljust(50)}] {pct:5.1f}% ({done//1024}KB/{total//1024}KB)"
                    )
                    sys.stdout.flush()
    if show_progress:
        print("\n✅ Download complete.")
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
    data = src.read_bytes()
    start = time.time()
    enc = aes_encrypt(data, key)
    dest.write_bytes(enc)
    dur = time.time() - start
    print(f"✅ Encrypted ({len(enc)} bytes) in {dur:.2f}s")


def decrypt_file(src: Path, dest: Path, key: bytes):
    print(f"🔓 Decrypting {src} -> {dest}")
    enc = src.read_bytes()
    data = aes_decrypt(enc, key)
    dest.write_bytes(data)
    print(f"✅ Decrypted ({len(data)} bytes)")


async def init_db(key: bytes):
    if not DB_PATH.exists():
        temp_path = allocate_temp_db_path()
        async with aiosqlite.connect(temp_path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS history "
                "(id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, prompt TEXT, response TEXT)"
            )
            await db.commit()
        try:
            with temp_path.open("rb") as f:
                enc = aes_encrypt(f.read(), key)
            DB_PATH.write_bytes(enc)
        finally:
            safe_cleanup([temp_path])


async def log_interaction(prompt: str, response: str, key: bytes):
    dec = allocate_temp_db_path()
    try:
        decrypt_file(DB_PATH, dec, key)
        async with aiosqlite.connect(dec) as db:
            await db.execute(
                "INSERT INTO history (timestamp, prompt, response) VALUES (?, ?, ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"), prompt, response)
            )
            await db.commit()
        with dec.open("rb") as f:
            enc = aes_encrypt(f.read(), key)
        DB_PATH.write_bytes(enc)
    finally:
        safe_cleanup([dec])


async def fetch_history(key: bytes, limit: int = 20, offset: int = 0, search: Optional[str] = None):
    dec = allocate_temp_db_path()
    rows = []
    try:
        decrypt_file(DB_PATH, dec, key)
        async with aiosqlite.connect(dec) as db:
            if search:
                q = f"%{search}%"
                async with db.execute(
                    "SELECT id,timestamp,prompt,response FROM history "
                    "WHERE prompt LIKE ? OR response LIKE ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (q, q, limit, offset)
                ) as cur:
                    async for r in cur:
                        rows.append(r)
            else:
                async with db.execute(
                    "SELECT id,timestamp,prompt,response FROM history ORDER BY id DESC LIMIT ? OFFSET ?",
                    (limit, offset)
                ) as cur:
                    async for r in cur:
                        rows.append(r)
        with dec.open("rb") as f:
            DB_PATH.write_bytes(aes_encrypt(f.read(), key))
        return rows
    finally:
        safe_cleanup([dec])


def load_llama_model_blocking(model_path: Path) -> Llama:
    return Llama(model_path=str(model_path), n_ctx=2048, n_threads=4)


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
            temps_map = psutil.sensors_temperatures()
            if temps_map:
                first_group = next(iter(temps_map.values()))
                if first_group:
                    first = first_group[0].current
                    temp = max(0.0, min(1.0, (first - 20.0) / 70.0))
                else:
                    temp = 0.0
            else:
                temp = 0.0
        except Exception:
            temp = 0.0
    except Exception as exc:
        raise RuntimeError(f"Unable to obtain psutil system metrics: {exc}") from exc

    return {
        "cpu": float(max(0.0, min(1.0, cpu))),
        "mem": float(max(0.0, min(1.0, mem))),
        "load1": float(max(0.0, min(1.0, load1))),
        "temp": float(max(0.0, min(1.0, temp))),
    }


def metrics_to_rgb(metrics: dict) -> Tuple[float, float, float]:
    cpu = metrics.get("cpu", 0.1)
    mem = metrics.get("mem", 0.1)
    temp = metrics.get("temp", 0.1)
    load1 = metrics.get("load1", 0.0)

    r = cpu * (1.0 + load1)
    g = mem * (1.0 + load1 * 0.5)
    b = temp * (0.5 + cpu * 0.5)

    maxi = max(r, g, b, 1.0)
    r, g, b = r / maxi, g / maxi, b / maxi
    return (
        float(max(0.0, min(1.0, r))),
        float(max(0.0, min(1.0, g))),
        float(max(0.0, min(1.0, b))),
    )


def pennylane_entropic_score(rgb: Tuple[float, float, float], shots: int = 256) -> float:
    if qml is None or pnp is None:
        r, g, b = rgb

        ri = int(r * 255) & 0xFF
        gi = int(g * 255) & 0xFF
        bi = int(b * 255) & 0xFF

        seed = (ri << 16) | (gi << 8) | bi
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


def entropic_summary_text(score: float) -> str:
    if score >= 0.75:
        level = "high"
    elif score >= 0.45:
        level = "medium"
    else:
        level = "low"
    return f"entropic_score={score:.3f} (level={level})"


def entropic_to_temp_nudge(score: float, base_temperature: float = 0.18) -> float:
    centered = score - 0.5
    nudge = centered * 0.08
    temp = base_temperature + nudge
    return max(0.12, min(0.22, temp))


def normalize_label(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "Medium"

    candidate = text.split()[0].capitalize()
    if candidate in ("Low", "Medium", "High"):
        return candidate

    lowered = text.lower()
    if "low" in lowered:
        return "Low"
    if "medium" in lowered:
        return "Medium"
    if "high" in lowered:
        return "High"

    return "Medium"


def generate_one_label(
    llm: Llama,
    prompt: str,
    base_temperature: float = 0.18,
    max_tokens: int = 32
) -> Tuple[str, Dict[str, float]]:
    metrics = collect_system_metrics()
    rgb = metrics_to_rgb(metrics)
    score = pennylane_entropic_score(rgb)
    temp = entropic_to_temp_nudge(score, base_temperature=base_temperature)

    out = llm(prompt, max_tokens=max_tokens, temperature=temp)

    text = ""
    if isinstance(out, dict):
        try:
            text = out.get("choices", [{"text": ""}])[0].get("text", "")
        except Exception:
            text = out.get("text", "")
    else:
        text = str(out)

    label = normalize_label(text)
    meta = {
        "entropy_score": score,
        "temperature": temp,
    }
    return label, meta


def consensus_generate(
    llm: Llama,
    prompt: str,
    runs: int = 5,
    base_temperature: float = 0.18,
    max_tokens: int = 32
) -> Dict[str, object]:
    votes = {"Low": 0, "Medium": 0, "High": 0}
    samples = []

    for _ in range(runs):
        label, meta = generate_one_label(
            llm=llm,
            prompt=prompt,
            base_temperature=base_temperature,
            max_tokens=max_tokens,
        )
        votes[label] += 1
        samples.append({
            "label": label,
            "entropy_score": round(meta["entropy_score"], 4),
            "temperature": round(meta["temperature"], 4),
        })

    winner = max(votes.items(), key=lambda kv: kv[1])[0]

    ordered = sorted(
        votes.items(),
        key=lambda kv: (-kv[1], ["Low", "Medium", "High"].index(kv[0]))
    )
    top_label, top_votes = ordered[0]
    second_votes = ordered[1][1]

    tied = top_votes == second_votes

    if tied:
        priority = {"Low": 0, "Medium": 1, "High": 2}
        winner = max(
            [k for k, v in votes.items() if v == top_votes],
            key=lambda x: priority[x]
        )

    return {
        "winner": winner,
        "votes": votes,
        "samples": samples,
        "runs": runs,
        "tied": tied,
    }


def chunked_generate(
    llm: Llama,
    prompt: str,
    max_total_tokens: int = 256,
    chunk_tokens: int = 64,
    base_temperature: float = 0.18,
    streaming_callback: Optional[Callable[[str], None]] = None
) -> str:
    assembled = ""
    cur_prompt = prompt
    iterations = max(1, (max_total_tokens + chunk_tokens - 1) // chunk_tokens)
    prev_tail = ""

    metrics = collect_system_metrics()
    rgb = metrics_to_rgb(metrics)
    score = pennylane_entropic_score(rgb)
    temp = entropic_to_temp_nudge(score, base_temperature=base_temperature)

    for _ in range(iterations):
        out = llm(cur_prompt, max_tokens=chunk_tokens, temperature=temp)

        text = ""
        if isinstance(out, dict):
            try:
                text = out.get("choices", [{"text": ""}])[0].get("text", "")
            except Exception:
                text = out.get("text", "")
        else:
            try:
                text = str(out)
            except Exception:
                text = ""

        text = (text or "").strip()
        if not text:
            break

        overlap = 0
        max_ol = min(30, len(prev_tail), len(text))
        for olen in range(max_ol, 0, -1):
            if prev_tail.endswith(text[:olen]):
                overlap = olen
                break

        append_text = text[overlap:] if overlap else text
        assembled += append_text
        prev_tail = assembled[-120:] if len(assembled) > 120 else assembled

        if streaming_callback:
            streaming_callback(append_text)

        final_candidate = normalize_label(assembled)
        if final_candidate in ("Low", "Medium", "High") and any(
            marker in assembled.lower() for marker in ("low", "medium", "high")
        ):
            break

        if len(text.split()) < max(4, chunk_tokens // 8):
            break

        cur_prompt = prompt + "\n\nAssistant so far:\n" + assembled + "\n\nContinue:"

    return assembled.strip()


def single_call_generate(
    llm: Llama,
    prompt: str,
    base_temperature: float = 0.18,
    max_tokens: int = 128
) -> str:
    metrics = collect_system_metrics()
    rgb = metrics_to_rgb(metrics)
    score = pennylane_entropic_score(rgb)
    temp = entropic_to_temp_nudge(score, base_temperature=base_temperature)

    out = llm(prompt, max_tokens=max_tokens, temperature=temp)

    text = ""
    if isinstance(out, dict):
        try:
            text = out.get("choices", [{"text": ""}])[0].get("text", "")
        except Exception:
            text = out.get("text", "")
    else:
        text = str(out)

    return (text or "").strip().replace(
        "You are a helpful AI assistant named SmolLM, trained by Hugging Face", ""
    ).strip()


def run_scan_mode(
    llm: Llama,
    prompt: str,
    mode: str,
    base_temperature: float = 0.18
) -> Tuple[str, str, Optional[Dict[str, object]]]:
    consensus_info = None

    if mode == "2":
        result = single_call_generate(
            llm=llm,
            prompt=prompt,
            base_temperature=base_temperature,
            max_tokens=128
        )
        label = normalize_label(result)
        return label, result, consensus_info

    if mode == "3":
        consensus_info = consensus_generate(
            llm=llm,
            prompt=prompt,
            runs=5,
            base_temperature=base_temperature,
            max_tokens=32
        )
        label = consensus_info["winner"]
        result = label
        return label, result, consensus_info

    if mode == "4":
        consensus_info = consensus_generate(
            llm=llm,
            prompt=prompt,
            runs=5,
            base_temperature=base_temperature,
            max_tokens=32
        )
        label = consensus_info["winner"]

        if consensus_info["votes"][label] < 3:
            chunked_result = chunked_generate(
                llm=llm,
                prompt=prompt,
                max_total_tokens=256,
                chunk_tokens=64,
                base_temperature=base_temperature,
                streaming_callback=None
            )
            chunked_label = normalize_label(chunked_result)
            priority = {"Low": 0, "Medium": 1, "High": 2}
            label = max([label, chunked_label], key=lambda x: priority[x])

        result = label
        return label, result, consensus_info

    result = chunked_generate(
        llm=llm,
        prompt=prompt,
        max_total_tokens=256,
        chunk_tokens=64,
        base_temperature=base_temperature,
        streaming_callback=None
    )
    label = normalize_label(result)
    return label, result, consensus_info


def build_road_scanner_prompt(data: dict, include_system_entropy: bool = True) -> str:
    entropy_text = "entropic_score=unknown"
    metrics_line = "sys_metrics: disabled"

    if include_system_entropy:
        try:
            metrics = collect_system_metrics()
            rgb = metrics_to_rgb(metrics)
            score = pennylane_entropic_score(rgb)
            entropy_text = entropic_summary_text(score)
            metrics_line = (
                "sys_metrics: cpu={cpu:.2f},mem={mem:.2f},load={load1:.2f},temp={temp:.2f}"
            ).format(
                cpu=metrics.get("cpu", 0.0),
                mem=metrics.get("mem", 0.0),
                load1=metrics.get("load1", 0.0),
                temp=metrics.get("temp", 0.0),
            )
        except Exception:
            metrics_line = "sys_metrics: unavailable"
            entropy_text = "entropic_score=unavailable"

    tpl = (
        f"You are a hypertime nanobot specialized Food Risk Classification AI trained to evaluate real-world food scenes.\n"
        f"Analyze the environmental and triple check for accurate intelligent reply and use accurate nosonar system simulator and sensor data and determine the overall food risk level.\n"
        f"Your reply must be only one word: Low, Medium, or High.\n\n"
        f"[tuning]\n"
        f"Scene details:\n"
        f"Location: {data.get('location', 'unspecified location')}\n"
        f"Food or Water Type: {data.get('road_type', 'unknown')}\n"
        f"Condition: {data.get('weather', 'unknown')}\n"
        f"Temp: {data.get('traffic', 'unknown')}\n"
        f"Cooked, Frozen Or Uncooked: {data.get('obstacles', 'none')}\n"
        f"Sensor notes: {data.get('sensor_notes', 'none')}\n"
        f"{metrics_line}\n"
        f"Quantum data: {entropy_text}\n"
        f"[/tuning]\n\n"
        f"Follow these strict rules when forming your decision:\n"
        f"- Think through all scene factors internally but do not show reasoning.\n"
        f"- Evaluate type, storage state, temp, preparation, and condition holistically.\n"
        f"- Optionally use the system entropic signal to bias your internal confidence slightly.\n"
        f"- Choose only one risk level that best fits the entire situation.\n"
        f"- Output exactly one word, with no punctuation or labels.\n"
        f"- The valid outputs are only: Low, Medium, High.\n\n"
        f"[action]\n"
        f"1) Normalize sensor inputs to comparable scales.\n"
        f"2) Check spoilage, temperature exposure, sealing state, and contamination clues.\n"
        f"3) Map environmental risk cues to a discrete label using conservative thresholds.\n"
        f"4) If sensor integrity anomalies are detected, bias toward higher risk.\n"
        f"5) Do not output internal reasoning or diagnostics; only return the single-word label.\n"
        f"[/action]\n\n"
        f"[replytemplate]\nLow | Medium | High\n[/replytemplate]"
    )
    return tpl


def allocate_temp_db_path() -> Path:
    fd, path = tempfile.mkstemp(prefix="chat_history_", suffix=".db")
    os.close(fd)
    return Path(path)


def header(status: dict):
    s = f" Secure LLM CLI — Model: {'loaded' if status.get('model_loaded') else 'none'} | Key: {'present' if status.get('key') else 'missing'} "
    print(color(s.center(80, '─'), fg=35, bold=True))


def model_manager(state: dict):
    while True:
        clear_screen()
        header(state)
        lines = [
            "1) Download model from remote repo (httpx)",
            "2) Verify plaintext model hash (compute SHA256)",
            "3) Encrypt plaintext model -> .aes",
            "4) Decrypt .aes -> plaintext (temporary)",
            "5) Delete plaintext model",
            "6) Back"
        ]
        print(boxed("Model Manager", lines))
        choice = input("Choose (1-6): ").strip()

        if choice == "1":
            if MODEL_PATH.exists():
                if input("Plaintext model exists; overwrite? (y/N): ").strip().lower() != "y":
                    continue
            try:
                url = MODEL_REPO + MODEL_FILE
                sha = download_model_httpx(
                    url,
                    MODEL_PATH,
                    show_progress=True,
                    timeout=None,
                    expected_sha=EXPECTED_HASH
                )
                print(f"Downloaded to {MODEL_PATH}")
                print(f"Computed SHA256: {sha}")
                if input("Encrypt downloaded model with current key now? (Y/n): ").strip().lower() != "n":
                    encrypt_file(MODEL_PATH, ENCRYPTED_MODEL, state["key"])
                    print(f"Encrypted -> {ENCRYPTED_MODEL}")
                    if input("Remove plaintext model? (Y/n): ").strip().lower() != "n":
                        MODEL_PATH.unlink()
                        print("Plaintext removed.")
            except Exception as e:
                print(f"Download failed: {e}")
            input("Enter to continue...")

        elif choice == "2":
            if not MODEL_PATH.exists():
                print("No plaintext model found.")
            else:
                print(f"SHA256: {sha256_file(MODEL_PATH)}")
            input("Enter to continue...")

        elif choice == "3":
            if not MODEL_PATH.exists():
                print("No plaintext model to encrypt.")
                input("Enter...")
                continue
            encrypt_file(MODEL_PATH, ENCRYPTED_MODEL, state["key"])
            if input("Remove plaintext? (Y/n): ").strip().lower() != "n":
                MODEL_PATH.unlink()
                print("Removed plaintext.")
            input("Enter...")

        elif choice == "4":
            if not ENCRYPTED_MODEL.exists():
                print("No .aes model present.")
            else:
                decrypt_file(ENCRYPTED_MODEL, MODEL_PATH, state["key"])
            input("Enter...")

        elif choice == "5":
            if MODEL_PATH.exists():
                if input(f"Delete {MODEL_PATH}? (y/N): ").strip().lower() == "y":
                    MODEL_PATH.unlink()
                    print("Deleted.")
            else:
                print("No plaintext model.")
            input("Enter...")

        elif choice == "6":
            return
        else:
            print("Invalid.")


async def chat_session(state: dict):
    if not ENCRYPTED_MODEL.exists():
        print("No encrypted model found. Please download & encrypt first.")
        input("Enter...")
        return

    decrypt_file(ENCRYPTED_MODEL, MODEL_PATH, state["key"])
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor(max_workers=1) as ex:
        try:
            print("Loading model...")
            llm = await loop.run_in_executor(ex, load_llama_model_blocking, MODEL_PATH)
        except Exception as e:
            print(f"Failed to load: {e}")
            if MODEL_PATH.exists():
                try:
                    encrypt_file(MODEL_PATH, ENCRYPTED_MODEL, state["key"])
                    MODEL_PATH.unlink()
                except Exception:
                    pass
            input("Enter...")
            return

        state["model_loaded"] = True
        try:
            await init_db(state["key"])
            print("Type /exit to return, /history to show last 10 messages.")
            while True:
                prompt = input("\nYou> ").strip()
                if not prompt:
                    continue
                if prompt in ("/exit", "exit", "quit"):
                    break
                if prompt == "/history":
                    rows = await fetch_history(state["key"], limit=10)
                    for r in rows:
                        print(f"[{r[0]}] {r[1]}\nQ: {r[2]}\nA: {r[3]}\n{'-' * 30}")
                    continue

                def gen(p):
                    out = llm(p, max_tokens=256, temperature=0.7)
                    text = ""
                    if isinstance(out, dict):
                        try:
                            text = out.get("choices", [{"text": ""}])[0].get("text", "")
                        except Exception:
                            text = out.get("text", "")
                    else:
                        text = str(out)
                    text = (text or "").strip()
                    text = text.replace("You are a helpful AI assistant named SmolLM, trained by Hugging Face", "").strip()
                    return text

                print("🤖 Thinking...")
                result = await loop.run_in_executor(ex, gen, prompt)
                print("\nModel:\n" + result + "\n")
                await log_interaction(prompt, result, state["key"])

        finally:
            try:
                del llm
            except Exception:
                pass
            print("Re-encrypting model and removing plaintext...")
            try:
                encrypt_file(MODEL_PATH, ENCRYPTED_MODEL, state["key"])
                MODEL_PATH.unlink()
                state["model_loaded"] = False
            except Exception as e:
                print(f"Cleanup failed: {e}")
            input("Enter...")


async def road_scanner_flow(state: dict):
    if not ENCRYPTED_MODEL.exists():
        print("No encrypted model found.")
        input("Enter...")
        return

    data = {}

    clear_screen()
    header(state)
    print(boxed("Road Scanner - Step 1/6", ["Leave blank for defaults"]))
    data["location"] = input("Location (e.g., whole foods'): ").strip() or "unspecified location"
    data["road_type"] = input("food or water type: ").strip() or "unknown"
    data["weather"] = input("Condition: ").strip() or "unknown"
    data["traffic"] = input("Temperture: ").strip() or "unknown"
    data["obstacles"] = input("Cooked Frozen Or uncooked: ").strip() or "none"
    data["sensor_notes"] = input("Sensor notes: ").strip() or "none"

    print(
        "\nGeneration options:\n"
        "1) Chunked generation (entropy temp nudge)\n"
        "2) Direct single-call generation\n"
        "3) Multi-generation consensus [default]\n"
        "4) Multi-generation consensus + chunked fallback"
    )
    gen_choice = input("Choose (1-4) [3]: ").strip() or "3"

    prompt = build_road_scanner_prompt(data, include_system_entropy=True)

    decrypt_file(ENCRYPTED_MODEL, MODEL_PATH, state["key"])
    loop = asyncio.get_running_loop()

    with ThreadPoolExecutor(max_workers=1) as ex:
        try:
            llm = await loop.run_in_executor(ex, load_llama_model_blocking, MODEL_PATH)
        except Exception as e:
            print(f"Model load failed: {e}")
            if MODEL_PATH.exists():
                try:
                    encrypt_file(MODEL_PATH, ENCRYPTED_MODEL, state["key"])
                    MODEL_PATH.unlink()
                except Exception:
                    pass
            input("Enter...")
            return

        try:
            print("Scanning...")
            label, result, consensus_info = await loop.run_in_executor(
                ex,
                lambda: run_scan_mode(
                    llm=llm,
                    prompt=prompt,
                    mode=gen_choice,
                    base_temperature=0.18
                )
            )

            print("\n--- Road Scanner Result ---\n")
            if label == "Low":
                print(color(label, fg=32, bold=True))
            elif label == "Medium":
                print(color(label, fg=33, bold=True))
            else:
                print(color(label, fg=31, bold=True))

            if consensus_info:
                print(f"\nVotes: {consensus_info['votes']}")
                for i, sample in enumerate(consensus_info["samples"], 1):
                    print(
                        f"  Run {i}: {sample['label']} "
                        f"(entropy={sample['entropy_score']}, temp={sample['temperature']})"
                    )

            print("\nOptions: 1) Re-run with edits  2) Export to JSON  3) Save & return  4) Cancel")
            ch = input("Choose (1-4): ").strip()

            if ch == "1":
                print("Re-run: editing fields. Press Enter to keep current value.")
                for k in list(data.keys()):
                    v = input(f"{k} [{data[k]}]: ").strip()
                    if v:
                        data[k] = v

                prompt = build_road_scanner_prompt(data, include_system_entropy=True)
                print("Re-scanning...")

                label, result, consensus_info = await loop.run_in_executor(
                    ex,
                    lambda: run_scan_mode(
                        llm=llm,
                        prompt=prompt,
                        mode=gen_choice,
                        base_temperature=0.18
                    )
                )

                print("\n--- Updated Result ---\n")
                if label == "Low":
                    print(color(label, fg=32, bold=True))
                elif label == "Medium":
                    print(color(label, fg=33, bold=True))
                else:
                    print(color(label, fg=31, bold=True))

                if consensus_info:
                    print(f"\nVotes: {consensus_info['votes']}")
                    for i, sample in enumerate(consensus_info["samples"], 1):
                        print(
                            f"  Run {i}: {sample['label']} "
                            f"(entropy={sample['entropy_score']}, temp={sample['temperature']})"
                        )

            if ch in ("2", "3"):
                try:
                    await init_db(state["key"])
                    await log_interaction(
                        "ROAD_SCANNER_PROMPT:\n" + prompt,
                        "ROAD_SCANNER_RESULT:\n" + label,
                        state["key"]
                    )
                except Exception as e:
                    print(f"Failed to log: {e}")

            if ch == "2":
                outp = {
                    "input": data,
                    "prompt": prompt,
                    "result": label,
                    "raw_result": result,
                    "consensus_info": consensus_info,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                fn = input("Filename to save JSON (default road_scan.json): ").strip() or "road_scan.json"
                Path(fn).write_text(json.dumps(outp, indent=2))
                print(f"Saved {fn}")

        finally:
            try:
                del llm
            except Exception:
                pass
            print("Re-encrypting model and removing plaintext...")
            try:
                encrypt_file(MODEL_PATH, ENCRYPTED_MODEL, state["key"])
                MODEL_PATH.unlink()
            except Exception as e:
                print(f"Cleanup error: {e}")
            input("Enter to return...")


async def db_viewer_flow(state: dict):
    if not DB_PATH.exists():
        print("No DB found.")
        input("Enter...")
        return

    page = 0
    per_page = 10
    search = None

    while True:
        rows = await fetch_history(state["key"], limit=per_page, offset=page * per_page, search=search)
        clear_screen()
        header(state)
        title = f"History (page {page+1})"
        print(boxed(title, [f"Search: {search or '(none)'}", "Commands: n=next p=prev s=search q=quit"]))
        if not rows:
            print("No rows on this page.")
        else:
            for r in rows:
                print(f"[{r[0]}] {r[1]}\nQ: {r[2]}\nA: {r[3]}\n" + "-" * 60)

        cmd = input("cmd (n/p/s/q): ").strip().lower()
        if cmd == "n":
            page += 1
        elif cmd == "p" and page > 0:
            page -= 1
        elif cmd == "s":
            search = input("Enter search keyword (empty to clear): ").strip() or None
            page = 0
        else:
            break


def rekey_flow(state: dict):
    print("Rekey / Rotate Key")
    if KEY_PATH.exists():
        print(f"Current key file: {KEY_PATH}")
    else:
        print("No existing key file (creating new).")

    choice = input("1) New random key  2) Passphrase-derived  3) Cancel\nChoose: ").strip()
    if choice not in ("1", "2"):
        print("Canceled.")
        input("Enter...")
        return

    old_key = state["key"]
    tmp_model = MODELS_DIR / (MODEL_FILE + ".tmp")
    tmp_db = allocate_temp_db_path()

    try:
        if ENCRYPTED_MODEL.exists():
            try:
                decrypt_file(ENCRYPTED_MODEL, tmp_model, old_key)
            except Exception as e:
                print(f"Failed to decrypt model with current key: {e}")
                safe_cleanup([tmp_model, tmp_db])
                input("Enter...")
                return

        if DB_PATH.exists():
            try:
                decrypt_file(DB_PATH, tmp_db, old_key)
            except Exception as e:
                print(f"Failed to decrypt DB with current key: {e}")
                safe_cleanup([tmp_model, tmp_db])
                input("Enter...")
                return

    except Exception as e:
        print(f"Unexpected: {e}")
        safe_cleanup([tmp_model, tmp_db])
        input("Enter...")
        return

    if choice == "1":
        new_key = AESGCM.generate_key(256)
        KEY_PATH.write_bytes(new_key)
        print("New random key generated and saved.")
    else:
        pw = getpass.getpass("Enter new passphrase: ")
        pw2 = getpass.getpass("Confirm: ")
        if pw != pw2:
            print("Mismatch.")
            safe_cleanup([tmp_model, tmp_db])
            input("Enter...")
            return
        salt, derived = derive_key_from_passphrase(pw)
        KEY_PATH.write_bytes(salt + derived)
        new_key = derived
        print("New passphrase-derived key saved (salt+derived).")

    try:
        if tmp_model.exists():
            old_h = sha256_file(tmp_model)
            encrypt_file(tmp_model, ENCRYPTED_MODEL, new_key)
            new_h_enc = sha256_file(ENCRYPTED_MODEL)
            print(f"Model plaintext SHA256: {old_h}")
            print(f"Encrypted model SHA256: {new_h_enc}")

        if tmp_db.exists():
            old_db_h = sha256_file(tmp_db)
            with tmp_db.open("rb") as f:
                DB_PATH.write_bytes(aes_encrypt(f.read(), new_key))
            new_db_h = sha256_file(DB_PATH)
            print(f"DB plaintext SHA256: {old_db_h}")
            print(f"Encrypted DB SHA256: {new_db_h}")

    except Exception as e:
        print(f"Error during re-encryption: {e}")
    finally:
        safe_cleanup([tmp_model, tmp_db])
        raw = KEY_PATH.read_bytes()
        state["key"] = raw[16:48] if len(raw) >= 48 else raw[:32]
        print("Rekey attempt finished. Verify files manually.")
        input("Enter...")


def safe_cleanup(paths: List[Path]):
    for p in paths:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass


def main_menu_loop(state: dict):
    options = ["Model Manager", "Chat with model", "Road Scanner", "View chat history", "Rekey / Rotate key", "Exit"]
    while True:
        clear_screen()
        header(state)
        print()
        print(boxed("Main Menu", [f"{i+1}) {opt}" for i, opt in enumerate(options)]))
        idx = read_menu_choice(len(options))
        choice = options[idx]

        if choice == "Model Manager":
            model_manager(state)
        elif choice == "Chat with model":
            asyncio.run(chat_session(state))
        elif choice == "Road Scanner":
            asyncio.run(road_scanner_flow(state))
        elif choice == "View chat history":
            asyncio.run(db_viewer_flow(state))
        elif choice == "Rekey / Rotate key":
            rekey_flow(state)
        elif choice == "Exit":
            print("Goodbye.")
            return


def main():
    try:
        key = ensure_key_interactive()
    except Exception:
        key = get_or_create_key()

    state = {"key": key, "model_loaded": False}

    try:
        asyncio.run(init_db(state["key"]))
    except Exception:
        pass

    try:
        main_menu_loop(state)
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        show_cursor()


if __name__ == "__main__":
    main()
