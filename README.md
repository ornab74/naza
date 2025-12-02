
# Naza — Quantum-Enhanced Road Scanner & Secure LLM CLI
# Install
```
#!/data/data/com.termux/files/usr/bin/bash
# --------------------------------------------------------
# Termux setup: older proot-distro commit + Ubuntu 24.04 + Python + Naza
# Auto-start main.py mandatory
# --------------------------------------------------------

# 1️⃣ Update Termux and install all required dependencies
pkg update -y && pkg upgrade -y
pkg install bash bzip2 coreutils curl file findutils gawk gzip ncurses-utils \
proot sed tar util-linux xz-utils git -y

# 2️⃣ Remove old proot-distro or Ubuntu installations
proot-distro remove ubuntu 2>/dev/null
rm -rf $HOME/proot-distro 2>/dev/null

# 3️⃣ Clone the older proot-distro commit
cd $HOME
git clone https://github.com/termux/proot-distro.git
cd proot-distro
git checkout ca53fee288be8f46ee0e4fc8ee23934023472054

# 4️⃣ Install proot-distro from source
chmod +x install.sh
./install.sh

# 5️⃣ Install Ubuntu (default in this commit)
proot-distro install ubuntu

# 6️⃣ Create temporary folder to prevent hang issues
export PROOT_TMP_DIR=$HOME/tmp
mkdir -p $PROOT_TMP_DIR

# 7️⃣ Login as root and install packages, create sudo user with random password
proot-distro login ubuntu -- <<'EOF'
apt update && apt upgrade -y
apt install sudo python3 python3-venv python3-pip git -y

# Generate random password for sudouser
PASSWORD=$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c16)
echo "sudouser:$PASSWORD" | chpasswd

# Store password in environment variable
echo "export NAZA_USER_PASSWORD=$PASSWORD" >> /root/.bashrc

# Create sudo user and allow passwordless sudo
adduser --gecos "" sudouser
echo "sudouser ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers
usermod -aG sudo sudouser
EOF

# 8️⃣ Login as root and set up Naza as sudouser
proot-distro login ubuntu -- <<'EOF'
su - sudouser -c '
mkdir -p ~/naza
cd ~/naza

# Clone Naza repository
git clone https://github.com/ornab74/naza.git .

# Create Python virtual environment
python3 -m venv ~/naza/venv
source ~/naza/venv/bin/activate

# Upgrade pip and install requirements
pip install --upgrade pip
if [ -f requirements.txt ]; then
    pip install -r requirements.txt
fi
'
EOF

# 9️⃣ Mandatory auto-start script
AUTO_START="$HOME/start_naza.sh"
cat > $AUTO_START <<'EOF'
#!/data/data/com.termux/files/usr/bin/bash
# Auto-start Naza with pseudo-TTY
proot-distro login ubuntu -- <<'INNER'
su - sudouser -c '
source ~/naza/venv/bin/activate
cd ~/naza
script -q /dev/null python3 main.py
'
INNER
EOF

chmod +x $AUTO_START

# 10️⃣ Force auto-start when Termux launches
grep -qxF "$HOME/start_naza.sh" ~/.bashrc || echo "$HOME/start_naza.sh" >> ~/.bashrc

echo "✅ Ubuntu 24.04 + Python + Naza setup complete!"
echo "Random password for sudouser stored in NAZA_USER_PASSWORD environment variable."
echo "Naza will auto-start every time Termux launches."

```
Naza is a secure, encrypted CLI system for AI-assisted road risk assessment, integrating LLaMA models, system-aware entropic scoring, and optional PennyLane quantum-inspired processing.

This system also logs encrypted chat history and allows modular extension for other intelligence tasks, e.g., food & water supply analysis (main_foodwater.py).

---

## Features

1. **Road Scanner (main.py)**  
   - Inputs: Location, road type, weather, traffic, obstacles, sensor notes  
   - Outputs: Single-word risk label: Low | Medium | High  
   - Chunked text generation + PUNKD token-weight adjustments  
   - Quantum-inspired entropic system scoring to bias predictions  

2. **LLM Chat & Model Manager**  
   - Interactive AI chat with encrypted LLaMA models  
   - Download, verify, encrypt/decrypt models (.aes)  
   - Encrypted SQLite database for history  

3. **System Metrics & Entropic Scoring**  
   - Metrics: CPU, memory, 1-min load, processes, temperature  
   - Optional PennyLane quantum evaluation  

4. **Security**  
   - AES-256 encryption for models and database  
   - Key rotation (random or passphrase-derived)  
   - Encrypted logs prevent plaintext leakage  

---

## System Overview & Equations

### 1. System Metrics Collection

Normalized system metrics:  

$$
\text{cpu} = \frac{\text{cpu\_usage}}{100},\quad
\text{mem} = \frac{\text{mem\_used}}{\text{mem\_total}},\quad
\text{load1} = \frac{\text{load\_avg}_1}{N_\text{cpu}},\quad
\text{proc} = \frac{N_\text{processes}}{1000},\quad
\text{temp} = \frac{T - 20}{70} \in [0,1]
$$

Where $N_\text{cpu}$ is the number of cores and 1000 is a normalization factor for process counts.

### 2. Metrics → RGB Mapping

Transforms system metrics into pseudo-color vector for quantum-inspired scoring:  

$$
\begin{align}
r &= \frac{\text{cpu} \cdot (1 + \text{load1})}{\max(1.0, \text{max}(r,g,b))} \\
g &= \frac{\text{mem} \cdot (1 + \text{proc})}{\max(1.0, \text{max}(r,g,b))} \\
b &= \frac{\text{temp} \cdot (0.5 + 0.5 \cdot \text{cpu})}{\max(1.0, \text{max}(r,g,b))}
\end{align}
$$

### 3. PennyLane Entropic Score

For RGB vector, the QNode circuit generates expectation values:  

$$
\text{circuit}(\theta) = \text{expval}(\sigma_z^{(0)}), \text{expval}(\sigma_z^{(1)})
$$

Combined into a scalar entropic score:  

$$
S_\text{entropy} = \frac{1}{1 + e^{-6\left[0.6\frac{\text{ev0}+1}{2} + 0.4\frac{\text{ev1}+1}{2} - 0.5\right]}}
$$

If PennyLane is unavailable, a pseudo-random approximation is used:  

$$
S_\text{entropy} \approx 0.3 r + 0.4 g + 0.3 b + \epsilon
$$

$\epsilon$ is small noise to simulate uncertainty.

### 4. PUNKD Token-Weight Adjustment

Tokens in the prompt are analyzed for hazard relevance:  

$$
w_t = c_t \cdot b_t
$$

- $c_t$ = frequency of token  
- $b_t$ = hazard boost ($b_t = 1$ default, $>1$ for risky tokens like ice, flood)  

Prompt temperature multiplier:  

$$
T_\text{eff} = T_\text{base} \cdot \left[1 + ( \bar{w} - 0.5 ) \cdot 0.8 \cdot \text{profile\_factor} \right]
$$

Where $\bar{w}$ = mean token weight, profile_factor adjusts aggressiveness.

### 5. Road Scanner Prompt Logic

1. Normalize input features  
2. Adjust risk confidence by system entropy  
3. Apply PUNKD attention to hazard tokens  
4. Chunked generation ensures safe iterative output  
5. Select one-word label:  

$$
\text{Risk} \in \{ \text{Low}, \text{Medium}, \text{High} \}
$$

### 6. AES Encryption

Encrypted models and database use AES-GCM 256-bit:  

$$
\text{ciphertext} = \text{AESGCM}_{k}(\text{nonce}, \text{plaintext})
$$

Key derivation from passphrase (optional) uses PBKDF2-HMAC-SHA256:  

$$
k = \text{PBKDF2HMAC}(\text{passphrase}, \text{salt}, 200{,}000 \text{ iterations})
$$

---

## Installation (Termux + Proot Ubuntu)

```
pkg update -y && pkg upgrade -y
pkg install -y proot-distro git python clang libcrypt-dev cmake sudo

proot-distro install ubuntu-22.04
proot-distro login ubuntu-22.04

apt install -y python3-venv build-essential libssl-dev cmake
python3 -m venv ~/naza_env
source ~/naza_env/bin/activate

git clone https://gitlab.com/barkzero1/naza.git
cd naza
pip install --upgrade pip
pip install httpx aiosqlite cryptography llama-cpp-python psutil pennylane numpy
```

Create sudo user:  

```
adduser <username>
usermod -aG sudo <username>
```

---

## Usage

### 1. Road Scanner

```
python main.py
```

- Input scene and sensor data  
- Choose generation: chunked + PUNKD (recommended), chunked, or direct  
- Receive Low | Medium | High label  
- Optionally export JSON and log encrypted history  

### 2. Chat / Model Management

- Interactive chat  
- Download / encrypt / decrypt models  
- Rotate AES keys  

### 3. System & Quantum Scoring

- Automatically collects CPU, memory, load, temp, process count  
- Converts metrics → RGB → entropic score → bias to model confidence  

---

## Advanced Notes

- Model plaintext never persists; automatically re-encrypted after use  
- Chunked generation mitigates hallucinations and enforces PUNKD attention  
- Quantum-inspired entropic score provides a real-time system-aware signal  
- AES-GCM encryption ensures authenticated confidentiality  
