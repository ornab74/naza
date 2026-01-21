
# Naza — Quantum-Enhanced Road Scanner & Secure LLM CLI

![Naza SecureLLM TUI – Quantum-Entropic Road Scanner in Action](https://raw.githubusercontent.com/ornab74/naza/refs/heads/main/demonaza.png)

## Android OS Installation and Usage

1. Install Termux from the Play Store 
   https://play.google.com/store/apps/details?id=com.termux
   
2. Download and Run the Setup script by copying the one line command below into Termux and pressing enter.
   
```
curl -fsSL https://raw.githubusercontent.com/ornab74/naza/main/termux-naza-autosetup/setup.sh -o setup.sh && \
if echo "422c2471b038c0c99551d6203a76997c60190ce0572158f17c2ae3187fb0b0a5  setup.sh" | sha256sum -c - >/dev/null 2>&1; then
  echo -e "\nHash verified! Running Naza auto-setup...\n"
  bash setup.sh
  rm -f setup.sh
else
  echo -e "\nHASH VERIFICATION FAILED!\nThe downloaded file has been tampered with or is corrupted.\nAborting for your safety.\n"
  rm -f setup.sh
  exit 1
fi
```

3. After the installation completes. Type exit then enter twice or force quit termux
   
4. Open Termux

5. After Naza boots up, press 1.
   
6. Press enter for each prompt to DL, encrypt, delete plaintext LLM GGUF
    
7. Press option 6
    
8. Press option 3 , Enter your route location and press enter with blank boxes for the rest
    
9. Press enter for default chunked +, punkd generation
    
10. View your risk score low/medium/high
    
11. If the scan shows high... consider the risks and think about pausing your trip. Or cange up your route on google maps, check the weather and your vehicle for issues. Then rerun after 5 or 10 minutes

## About
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
