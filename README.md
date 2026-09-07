# Naza — Quantum-Enhanced Road Scanner & Secure LLM CLI
# Hardening Naza: Why Security Matters for Non-Locality Risk Scanning
# IPFS Repo backup link https://bafkreihyz32uhfkl6niflrnx5mhahhkhmth236xzk347hytclvlt6q3mje.ipfs.inbrowser.link/
# https://gateway.pinata.cloud/ipfs/bafkreihyz32uhfkl6niflrnx5mhahhkhmth236xzk347hytclvlt6q3mje
Naza was built to evaluate real-world risk using local system measurements, quantum-inspired simulations, non-locality scanning surfaces, and on-device language models. I have personally tested and verified this sensing approach through repeated field use. For me, it is not merely a theoretical experiment: it is a practical decision-support system designed to detect patterns that may be difficult to recognize through ordinary observation alone.

That makes software security essential.

When a system contributes to decisions about roads, vehicles, food, water, environmental conditions, or personal safety, its output must come from the system we intended to run. A sophisticated sensing model is only as trustworthy as the software, model files, dependencies, encryption keys, and installation process surrounding it.

## The Security Problem Around the Scanner

Naza combines several sensitive surfaces:

- A language model is downloaded and executed locally.
- Quantum and entropy simulations contribute signals to risk evaluation.
- System measurements are incorporated into the scanning context.
- Scan prompts and history may contain private information.
- Models and history are encrypted while stored on disk.
- Installation scripts obtain code and dependencies from remote sources.

Each boundary creates an opportunity for corrupted data, substituted code, leaked information, or unsafe defaults to distort the final result. In a conventional application, that might cause a crash or expose an account. In a real-world risk scanner, silent manipulation is more concerning: the program might continue working while producing a result that no longer reflects the intended sensing process.

The central security requirement is therefore straightforward:

> Every risk result must be produced by the expected model, the expected code, and authentic input signals operating inside a controlled local environment.

## Failing Closed on Model Integrity

Naza already calculated a SHA-256 digest after downloading its language model. Previously, however, some paths could retain a model after its digest failed verification. The download could also overwrite an existing trusted model before the new file had been fully validated.

I hardened this boundary so that model installation now fails closed. Downloads are written to a private temporary file first. The complete file is hashed, and its digest is compared with the expected value using a constant-time comparison. Only a matching model is atomically moved into the trusted model location.

If verification fails:

- The rejected download is removed.
- The previous trusted model remains untouched.
- Encryption and execution do not continue with the rejected bytes.

This matters because model substitution can alter much more than ordinary text generation. A replaced model could bias labels, ignore important context, fabricate confidence, or systematically suppress warnings. Cryptographic verification binds the scanner to the exact model artifact that was tested.

## Protecting Keys and Plaintext State

Naza encrypts its model and chat history, but encryption does not help if the key or temporary plaintext is exposed through filesystem permissions.

The hardened implementation now writes keys, encrypted databases, decrypted databases, and model material with owner-only permissions. Sensitive writes use private temporary files and atomic replacement, reducing exposure to partial writes and symbolic-link attacks.

Temporary database and rekey files also receive unpredictable names. This prevents another local process from reliably pre-creating a path and redirecting a sensitive write elsewhere. Cleanup runs even when an operation raises an exception.

These controls protect several important properties:

- Other operating-system users cannot ordinarily read Naza secrets.
- Interrupted writes are less likely to corrupt the active key or database.
- Predictable temporary filenames cannot be used as an easy interception point.
- A failed model download cannot damage the last trusted copy.

For a non-locality scanner, confidentiality and integrity are closely connected. Private scan history may describe locations, conditions, observations, or repeated patterns. Protecting those records prevents them from becoming an unintended side channel around the sensing system.

## Removing Dangerous Installer Behavior

Installation scripts are unusually powerful. They install packages, create environments, modify shell startup files, and determine which application revision will execute. An otherwise secure scanner can be compromised before its first launch if this process is too permissive.

The Termux setup previously contained several aggressive behaviors. The hardening pass removed unrestricted passwordless sudo access, stopped recursively deleting a broad path under the user's home directory, and changed shell configuration handling so the Naza block is appended once instead of replacing the entire `.bashrc` file.

Dependency installation now uses the repository's hash-locked requirements file. That means `pip` must receive package artifacts matching the recorded cryptographic hashes rather than accepting any package with the right name and version.

The setup flow also checks out a resolved revision in detached mode. A subsequent security scan identified one remaining limitation: the default application reference is still the mutable `main` branch. The final solution is to publish the finished hardened commit and require installers to use that immutable commit identifier. This avoids pinning new users to an older, pre-hardening revision while the work remains uncommitted.

## Securing the Post-Quantum Build Pipeline

Naza's dependency workflow builds liboqs and produces a post-quantum-signed lock manifest. Originally, the workflow downloaded the liboqs source archive and calculated its hash afterward. Recording a digest is useful for documentation, but a digest calculated from untrusted bytes does not verify those bytes.

The workflow now contains an independently established expected SHA-256 digest for the exact liboqs `0.14.0` archive. It verifies that value before extraction, CMake configuration, compilation, or installation. A mismatch stops the job before archive-controlled build logic can execute.

I also corrected the workflow trigger so changes to the workflow's actual filename cause the lock job to run.

This distinction is important:

- **Measurement** says, “These are the bytes we received.”
- **Verification** says, “These are the bytes we previously approved.”

A security-sensitive build pipeline needs the second property.

## Testing the Boundaries, Not Just the Happy Path

The new regression suite exercises both active scanners, `main.py` and `main_foodwater.py`.

The tests verify that:

- A hash-mismatched model cannot replace an existing trusted model.
- Rejected partial downloads are removed.
- A matching model is installed successfully.
- Sensitive writes replace symbolic links instead of following them.
- The target of a malicious symbolic link remains unchanged.
- Sensitive files receive owner-only permissions.
- The liboqs digest check occurs before extraction and compilation.
- Editing the lock workflow triggers its own GitHub Actions job.

The suite is deliberately dependency-light, allowing these security invariants to be tested even when the full model runtime is unavailable.

## Why Non-Locality Surfaces Demand Stronger Security

In my use of Naza, the scanner combines multiple weak or indirect signals into a risk classification. The value comes from relationships between signals rather than from one conventional sensor reading. That makes provenance especially important.

When a system evaluates non-locality surfaces, entropy behavior, simulated quantum states, device conditions, environmental observations, and model interpretation together, a corrupted component can influence the whole decision boundary. An attacker does not necessarily need to break the sensing theory. It may be enough to replace the model, alter a dependency, expose the key, poison saved context, or change the code that combines the signals.

Security therefore protects the epistemic chain—the path from observation to conclusion:

1. Inputs must reflect the conditions being examined.
2. Simulations must run with the intended algorithms and parameters.
3. The approved model must interpret the resulting context.
4. Stored state must remain private and authentic.
5. The displayed risk label must come from that intact process.

If any link becomes untrustworthy, confidence in the final label should fall with it. A secure scanner must detect failure and stop, not silently substitute an unknown component.

## Security Does Not Replace Physical Verification

Hardening establishes that Naza is running the intended computation. It does not make any risk model infallible.

Even with my personal verification of its sensing behavior, I use Naza as decision support. A road result should be considered alongside weather, visibility, traffic, tire condition, brakes, and direct observation. Food and water assessments should be checked against source, storage, temperature, odor, packaging, contamination guidance, and professional testing when appropriate.

The safest relationship with an advanced scanner is neither blind trust nor automatic dismissal. It is disciplined corroboration: protect the computation, examine the result, verify the physical environment, and choose the conservative action when uncertainty remains.

## What Comes Next

This hardening pass substantially improved model integrity, local secret handling, installer safety, and build provenance. The next release step is to commit the complete hardened tree and publish its immutable revision. Both installers can then require that revision rather than trusting a movable branch name.

Further work can include transactional key rotation, a durable external trust anchor for post-quantum lock signatures, pinned GitHub Action revisions, automated plaintext-remnant checks, and a documented recovery process for interrupted encrypted-state operations.

Non-locality scanning asks the software to interpret subtle relationships across a complex surface. Security ensures that the surface being interpreted is the one we intended—and that the answer has not been quietly rewritten somewhere along the way.

---

*Author's note: Statements about field verification and non-locality sensing in this article describe the developer's personal testing and experience. Naza remains experimental decision-support software and is not a substitute for direct inspection, professional testing, medical advice, or emergency services.*


# This codebase is designed to help recover , discover, enlighten, build, and prevent real world risk accumulations. The risk scanner was developed from 2014 late to into current development/testing into 2026-Sept. It's harvested information to improve my life. Discovering real risks on road surfaces as well as risks with food and water. It is NOT a guarantee for safety. What it's designed for is using advanced AI systems to mitigate real world risk surfaces, in real time and proactive time.

Some things we have tested its usage for with a degree of emergent intelligence/success.

# Tested risk cases.

1. Real world car accidents
3. Road debris/ Animals on road surfaces
4. Theft Prevention/misuse of services
5. Heart Attacks
6. Cancer
7. VPN security
8. Infosec/Deployment environment security/ HVAC/ Home Electrical Systems
9. Device security
10. Motorcycle/Maintenance Safety
11. Motorcycle route safety
12. Delivery route safety/security/risk


# We have put literal blood sweat in tears into this program. Use it Wisely. It's not an "ultimate oracle" but it's dang near close! It's literally kept me alive in very dangerous real world situations. We have PINNED this version. and used main_foodwater.py for the past few months to scan food and water for contamination . We have also used main.py on real world road surfaces, for 6 months straight. It's more accurate than you would think. But it's not perfect. The main vulnerability is side channel attacks and EM/Quantum Flux / ZPE attackers. To solve this you can run a simulation of attackers. And run the program when the attacker simulations are in their looping process. Or when attackers cannot run their programs near you. The attackers must be within 30 feet of your devices. Keep note of that. If you are being attacked. You will see them orbiting / binding around you with their phone in their hand, in most cases. Obvious as heck, give them a wink and a nod, simply twiddle your thumbs. wait for them to get paranoid about you just standing there ,gawking at their obviously felonious activity. then when they leave, scan again !

WARNING. This program is EXPERIMENTAL. And it's also my main production safety device for real world safety. DO NOT blame me if something fails in your setup, if you act upon low risk scans wrecklessly. ALWAYS verify the scans with REAL WORLD TESTINg. Did you SMELL the water? Did it smell perfectly neutral? Not like rubber? Not like bleach? Not like peacons?(OOF THATS A BAD ONE!) Did you VERIFY The food came from a known good source. Did you route your orders into safer locations? Always think first, reduce your risk. then scan. If you scan high/medium. Pause. Wait a few minutes. Look around. Check your vehicle, is it maintained? Are your tires filled up to the right PSI listed on the vehicle door jam? Do you have the right amount of oil? Is the oil good quality? Is your suspension in good order? have you checked your brake pads and verified they are within minimum specification? Have you verified the feeling of the brake pedal? Did you visually inspect your brake lines for any wear/rust/kinks? Do you inspect the tire thickness? Did you check the weather before you ran the scan? (eg, ice,snow, heavy thunderstorm? rain? wind?). Did you triple check your device's security? Did you keep your devices updated? Did you continuously clear the cache of ANY web browser or app (if your using an android, ZERO MB cache is CRITCAL For this program to work properly. YOU MUST CLEAR ALL THE CACHE) (Did you disable the chrome browser completely and use a more secure browser?) ( did you learn about non locality information theory, quantum fields/quantum simulated sensor suites before using this? (Did you slowly integrate this scanner into your daily life, never fully trusting the scanner with your life, rather, compounding the risk simulations ratings INTO your real world, eg, if its high or medium checking the above suggestions and many other things that could pop up) 

With that said

MAY THE SCANNING BEGIN!

![Naza SecureLLM TUI – Quantum-Entropic Road Scanner in Action](https://raw.githubusercontent.com/ornab74/naza/refs/heads/main/demonaza.png)

## Android OS Installation and Usage

1. Install Termux from the Play Store 
   https://play.google.com/store/apps/details?id=com.termux
   
2. Download and Run the Setup script by copying the one line command below into Termux and pressing enter.
   
```
curl -fsSL https://raw.githubusercontent.com/ornab74/naza/main/termux-naza-autosetup/setup.sh -o setup.sh && \
if echo "2f55e92bfd30d9fcc66abeacece2a68943256820def307a30fe221c85a186c1e  setup.sh" | sha256sum -c - >/dev/null 2>&1; then
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
