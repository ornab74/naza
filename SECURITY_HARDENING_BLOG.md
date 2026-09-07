# Hardening Naza: Why Security Matters for Non-Locality Risk Scanning

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
