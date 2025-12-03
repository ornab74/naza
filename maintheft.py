import os, sys, time, json, hashlib, asyncio, httpx, aiosqlite, getpass, re, math
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from llama_cpp import Llama

try:
    import psutil
except:
    psutil = None
try:
    import pennylane as qml
except:
    qml = None

MODEL_REPO = "https://huggingface.co/tensorblock/llama3-small-GGUF/resolve/main/"
MODEL_FILE = "llama3-small-Q3_K_M.gguf"
MODELS_DIR = Path("models")
MODEL_PATH = MODELS_DIR / MODEL_FILE
ENCRYPTED_MODEL = MODEL_PATH.with_suffix(".gguf.aes")
DB_PATH = Path("history.db.aes")
KEY_PATH = Path(".enc_key")
MODELS_DIR.mkdir(parents=True, exist_ok=True)

def clear():
    os.system("clear" if os.name == "posix" else "cls")

def color(t, c=None, b=False):
    codes = []
    if c: codes.append(str(c))
    if b: codes.append("1")
    return f"\x1b[{';'.join(codes)}m{t}\x1b[0m" if codes else t

def aes_encrypt(d, k):
    n = os.urandom(12)
    return n + AESGCM(k).encrypt(n, d, None)

def aes_decrypt(d, k):
    return AESGCM(k).decrypt(d[:12], d[12:], None)

def get_key():
    if KEY_PATH.exists():
        data = KEY_PATH.read_bytes()
        return data[16:48] if len(data) >= 48 else data[:32]
    choice = input("No key found → 1) Random  2) Passphrase: ").strip()
    if choice == "2":
        p1 = getpass.getpass("Passphrase: ")
        p2 = getpass.getpass("Confirm: ")
        if p1 != p2:
            print(color("Mismatch", 196))
            sys.exit(1)
        salt = os.urandom(16)
        key = PBKDF2HMAC(hashes.SHA256(), 32, salt, 600000).derive(p1.encode())
        KEY_PATH.write_bytes(salt + key)
    else:
        key = AESGCM.generate_key(256)
        KEY_PATH.write_bytes(key)
    print(color(f"Key ready → {KEY_PATH}", 82))
    return key

def encrypt_file(src: Path, dst: Path, key: bytes):
    dst.write_bytes(aes_encrypt(src.read_bytes(), key))

def decrypt_file(src: Path, dst: Path, key: bytes):
    dst.write_bytes(aes_decrypt(src.read_bytes(), key))

def quantum_entropy():
    cpu = mem = temp = 0.5
    if psutil:
        cpu = psutil.cpu_percent(0.1)/100
        mem = psutil.virtual_memory().percent/100
        t = psutil.sensors_temperatures()
        if t: temp = next((x.current for v in t.values() for x in v), 50)/100
    r,g,b = cpu*1.4, mem*1.3, temp*2.0
    mx = max(r,g,b,1)
    r,g,b = r/mx, g/mx, b/mx
    if not qml:
        s = 0.5 + 0.3*math.sin(r*12.34 + g*56.78 + b*91.01)
        return round(s,4), "AGGRESSIVE" if s>0.68 else "CAUTIOUS" if s<0.38 else "NEUTRAL"
    dev = qml.device("default.qubit", wires=2, shots=1024)
    @qml.qnode(dev)
    def c():
        qml.RX(r*math.pi,0); qml.RY(g*math.pi,1); qml.CNOT([0,1]); qml.RZ(b*math.pi,1)
        return qml.expval(qml.PauliZ(0)@qml.PauliZ(1))
    ev = c()
    score = 0.5 + 0.5*(1.0 - abs(ev))
    mode = "AGGRESSIVE" if score>0.68 else "CAUTIOUS" if score<0.38 else "NEUTRAL"
    return round(score,4), mode

def build_prompt(data):
    q, mode = quantum_entropy()
    return f"""You are THEFTWATCH-Ω v20 — Theft Risk Nanobot
Output exactly one line: RiskLevel | Target

[tuning]
Location: {data.get('location','unknown')}
Time: {data.get('time','unknown')}
Lighting: {data.get('lighting','unknown')}
Foot traffic: {data.get('foot_traffic','unknown')}
Parking density: {data.get('parking','unknown')}
CCTV: {data.get('cctv','unknown')}
Security: {data.get('security','none')}
Recent incidents: {data.get('recent_incidents','none')}
Visible valuables: {data.get('valuables','none')}
Area type: {data.get('area_type','unknown')}
Sensor notes: {data.get('sensor_notes','none')}
Quantum Entropy: {q} → {mode}
[/tuning]

[action]
1. Normalize inputs
2. Triple-check all factors
3. Apply quantum bias: AGGRESSIVE=+1 level, CAUTIOUS=-1 only if all safe
4. Pick single most likely target
5. Output one of 15 allowed lines
[/action]

[rules]
- No reasoning
- No extra text
- No quotes
- Exactly: RiskLevel | Target
- Default to higher risk
[/rules]

[replytemplate]
Low | vehicle
Low | electronics
Low | tools
Low | phone
Low | other
Medium | vehicle
Medium | electronics
Medium | tools
Medium | phone
Medium | other
High | vehicle
High | electronics
High | tools
High | phone
High | other
[/replytemplate]

Output now:"""

def chunked_generate(llm: Llama, prompt: str) -> str:
    full = ""
    cur = prompt
    for _ in range(4):
        out = llm(cur, max_tokens=64, temperature=0.01, stop=["\n", "<"], echo=False)
        text = out["choices"][0]["text"] if isinstance(out, dict) and "choices" in out else str(out)
        text = text.strip()
        if not text: break
        added = text
        if len(full) > 20 and text.startswith(full[-20:]):
            added = text[20:]
        full += added
        if re.search(r"\b(High|Medium|Low)\s*\|\s*(vehicle|electronics|tools|phone|other)\b", full, re.I):
            break
        cur = prompt + "\nSo far: " + full + "\nContinue:"
    return full.strip()

async def log(key, prompt, result):
    tmp = Path("tmp.db")
    if DB_PATH.exists():
        decrypt_file(DB_PATH, tmp, key)
    else:
        tmp.touch()
    async with aiosqlite.connect(tmp) as db:
        await db.execute("CREATE TABLE IF NOT EXISTS h(id INTEGER PRIMARY KEY, ts TEXT, p TEXT, r TEXT)")
        await db.execute("INSERT INTO h(ts,p,r) VALUES(?,?,?)",
                        (time.strftime("%Y-%m-%d %H:%M:%S"), prompt[-600:], result))
        await db.commit()
    encrypt_file(tmp, DB_PATH, key)
    tmp.unlink(missing_ok=True)

async def theft_scanner(state):
    if not ENCRYPTED_MODEL.exists():
        print(color("No encrypted model!", 196)); input(); return
    clear()
    print(color("THEFTWATCH-Ω v20 — URBAN THEFT CLASSIFIER", 196, True))
    print(color("Quantum + Chunked Generation", 33))
    data = {}
    fields = ["location","time","lighting","foot_traffic","parking","cctv",
              "security","recent_incidents","valuables","area_type","sensor_notes"]
    for f in fields:
        v = input(f"{f.replace('_',' ').title()}: ").strip()
        data[f] = v or "unknown"
    decrypt_file(ENCRYPTED_MODEL, MODEL_PATH, state["key"])
    llm = Llama(str(MODEL_PATH), n_ctx=2048, n_threads=os.cpu_count() or 4)
    print(color("Analyzing...", 226), end="")
    raw = await asyncio.get_event_loop().run_in_executor(None, chunked_generate, llm, build_prompt(data))
    print(color("DONE", 82))
    m = re.search(r"\b(Low|Medium|High)\s*\|\s*(vehicle|electronics|tools|phone|other)\b", raw, re.I)
    level, target = ("Medium", "other")
    if m:
        level, target = m.group(1).capitalize(), m.group(2).lower()
    c = 196 if level == "High" else 208 if level == "Medium" else 46
    print(color(f"\nRISK → {level} | {target}", c, True))
    await log(state["key"], build_prompt(data), f"{level} | {target}")
    del llm
    encrypt_file(MODEL_PATH, ENCRYPTED_MODEL, state["key"])
    MODEL_PATH.unlink(missing_ok=True)
    input(color("\nDone. Press Enter...", 240))

def download_and_secure():
    clear()
    print(color("MODEL DOWNLOAD & SECURE", 196, True))
    if MODEL_PATH.exists():
        if input(color("Plaintext model exists. Overwrite? y/N: ", 226)).strip().lower() != "y":
            input(); return
    if ENCRYPTED_MODEL.exists():
        print(color("Encrypted model already exists.", 208))
        if input(color("Redownload and re-encrypt? y/N: ", 226)).strip().lower() != "y":
            input(); return

    url = MODEL_REPO + MODEL_FILE
    print(color("Downloading model...", 226))
    with httpx.stream("GET", url, follow_redirects=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        done = 0
        with MODEL_PATH.open("wb") as f:
            for chunk in r.iter_bytes(8192):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done / total
                    bar = int(50 * pct)
                    print(f"\r[{color('█'*bar, 82)}{' '*(50-bar)}] {pct*100:5.1f}%", end="", flush=True)
    print(color("\nDownload complete", 82))

    print(color("Encrypting model...", 226))
    encrypt_file(MODEL_PATH, ENCRYPTED_MODEL, KEY)
    print(color("Encrypted → " + str(ENCRYPTED_MODEL), 82))

    print(color("Deleting plaintext model...", 196))
    try:
        MODEL_PATH.unlink()
        print(color("Plaintext deleted. No trace left.", 82))
    except:
        print(color("Warning: Could not delete plaintext!", 196))

    input(color("\nModel secured. Press Enter...", 240))

def main():
    global KEY
    KEY = get_key()
    state = {"key": KEY}
    asyncio.run(log(KEY, "system", "init"))
    while True:
        clear()
        print(color("┌────────────────────────────────────────┐", 36))
        print(color("│        THEFTWATCH-Ω v20                │", 36, True))
        print(color("└────────────────────────────────────────┘", 36))
        print("1) Download & Secure Model (delete plaintext)")
        print("2) Run Theft Scanner (quantum + chunked)")
        print("3) Exit")
        c = input(color("\n→ ", 226)).strip()
        if c == "1":
            download_and_secure()
        elif c == "2":
            asyncio.run(theft_scanner(state))
        elif c in ("3", "q", "exit"):
            break

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(color("\nShutdown", 196))
