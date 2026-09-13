# Required Termux keystore + fingerprint unlock

For the Termux + Ubuntu-proot installation, the Android/Termux keystore unlock is **required**.
It is not an optional integration.

`termux-keystore` and `termux-fingerprint` execute on the **Termux host**, not inside Ubuntu proot. The installer creates or verifies the `naza-unlock` RSA key before Ubuntu setup is allowed to continue.

The command enforced by `termux-naza-autosetup/setup.sh` is:

```bash
termux-keystore generate naza-unlock -a RSA -s 2048 -u 10
```

The setup then verifies that `naza-unlock` appears in `termux-keystore list`. If creation or verification fails, setup stops.

At launch, `naza_unlock.sh`:

1. verifies the required keystore alias exists;
2. requests fingerprint authentication through Termux:API;
3. signs a local random challenge with the Android-backed key;
4. derives a short-lived unlock token;
5. allows `naza_boot.sh` to start Naza inside Ubuntu proot.

The Ubuntu side receives the gate token through inherited descriptor 9, leaving
interactive standard input untouched. Normal boot streams the token without
creating a host or guest token file. Both installation and
application sessions use `proot-distro --isolated`; Termux home, shared storage,
and nonessential Android paths are not mounted into the guest. The Android
keystore key itself is never copied into proot.

The private challenge is intentionally stable: its deterministic RSA signature
derives the repeatable passphrase used by fingerprint-gated NKEY4 files. The
challenge is not an authentication token and is kept owner-only. Rotating or
deleting it requires rewrapping the data key first.

The setup and every unlock inspect detailed key metadata and fail closed unless
the alias is RSA-2048 and requires Android user authentication. Core dumps are
disabled and the runtime file-descriptor limit is constrained.

PRoot is compatibility isolation, not a security sandbox: it provides no
separate Android UID, seccomp boundary, or cgroup boundary. A process that has
already compromised the Termux UID remains inside the Termux trust domain. Full
same-UID resistance requires a dedicated Android broker application running as
a separate UID and verifying each launch request itself.
