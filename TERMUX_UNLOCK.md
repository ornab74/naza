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

The Ubuntu side receives the token through the private `~/.naza` bind mount. The Android keystore key itself is not copied into proot.
