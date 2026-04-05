# DRM Bypass POC — ProGrade Zenith File Server

## Summary

The ProGrade Zenith (PGZ) file serving platform at `files.radiocitygovernment.com` implements a
client-side DRM scheme that is trivially bypassable. The encryption key for every protected file
is served directly to any authenticated browser session. An attacker who knows the file name and
either a file password or a download code can download and permanently decrypt any protected file
in a single script with no specialised tooling.

A nonce-binding patch has been applied (audit recommendation #2) that enforces sequential
pairing between the key fetch and media fetch and prevents replay. It does not close the root
vulnerability — the client still receives both the key and the ciphertext, and the PoC handles
the nonce transparently.

---

## Vulnerability

### Root Cause: Key and Ciphertext Served to the Same Client

The DRM model assumes the browser will decrypt content in JavaScript and render it through a
locked-down canvas element, preventing saving. However, the server cannot enforce this — it has
no way to prevent a non-browser client from consuming both endpoints and writing the plaintext to
disk.

The two vulnerable endpoints, both accessible with only a valid session cookie:

| Endpoint | Purpose | Returns |
|---|---|---|
| `GET /drm_serve.php?file={name}&action=key` | Deliver decryption key + single-use nonce | `{"key": "<hex>", "nonce": "<hex>"}` |
| `GET /drm_serve.php?file={name}&action=media&nonce={nonce}` | Deliver ciphertext | Raw encrypted binary |

Serving the key and the ciphertext to the same party is the fundamental flaw. No DRM scheme is
secure if the client holds both.

---

## Attack Flow

```
1. GET  /f/{file}                             — Load the access form, scrape pgz_csrf token
2. POST /f/{file}                             — Submit pgz_csrf + credential → receive PGZ_SESSION cookie
3. GET  /drm_serve.php?...&action=key         — Receive {"key": "<hex>", "nonce": "<hex>"}
4. GET  /drm_serve.php?...&action=media       — Pass nonce from step 3; server validates with
         &nonce={nonce}                          hash_equals, unsets it from session, returns ciphertext
5. Decrypt locally                            — IV = first 16 bytes of ciphertext; remainder is payload
6. Write plaintext to disk
```

The nonce adds a sequencing constraint (step 3 must precede step 4) but does not change the
outcome: the attacker performs steps 3 and 4 in order and receives the same key + ciphertext as
before. The PoC handles this automatically — `fetch_key` returns both `key` and `nonce`, which
`fetch_encrypted` passes as the `&nonce=` query parameter.

### Authentication Credential Types

The POST in step 2 accepts two mutually exclusive credential fields depending on how the file was shared:

| Field name | Used when |
|---|---|
| `file_password` | File is protected by a numeric/alphanumeric password |
| `download_code` | File is shared via a one-time or reusable download code |

The CSRF scrape and session cookie mechanism is identical in both cases — only the POST field name differs.

Steps 5–6 are performed entirely offline once the session cookie is obtained.

---

## Encryption Scheme

The server uses **AES-256-CBC**:

- **Key**: 256-bit, hex-encoded, returned verbatim in the key endpoint JSON
- **IV**: prepended as the first 16 bytes of the encrypted file
- **Padding**: PKCS#7

The `nonce` field in the key response must be passed as `&nonce=` when fetching the media endpoint.
It is validated server-side with `hash_equals` and immediately consumed (unset from session),
preventing replay. It plays no role in the AES decryption itself.

---

## Client-Side "Protections" — Why They Fail

The viewer page (`/v/{file}`) deploys several JavaScript mitigations. None of them are
meaningful against this attack because the attack never loads the page.

| Protection | Implementation | Why it fails |
|---|---|---|
| Canvas rendering | Draws video frames to `<canvas>`, never adds `<video>` to DOM | Irrelevant; we never render anything |
| `URL.createObjectURL` override | Blocks new blob URLs after init | Irrelevant; no browser involved |
| DevTools size heuristic | Compares `outerWidth` vs `innerWidth` | JavaScript running in a browser tab |
| Right-click / keyboard blocks | `contextmenu`, `keydown` event listeners | JavaScript running in a browser tab |
| Watermark overlay | Embeds IP + timestamp in a `<div>` | Never rendered |
| `getDisplayMedia` block | Overrides screen capture API | Browser API; irrelevant to script |

All protections are enforced by JavaScript delivered **to** the client. A Python HTTP client
ignores all of it.

---

## Proof of Concept

`main.py` in this repository demonstrates the full attack in ~75 lines of Python.

**Dependencies:**

```bash
pip install requests pycryptodome
```

**Usage (file password):**

```
$ python main.py
=== DRM File Decryptor ===
File name: south-park
Auth type: [1] file_password  [2] download_code
Choice (1/2): 1
File password: 9874
Authenticating...
Fetching key...
Fetching encrypted file...
Decrypting...
Done: 48302847 bytes -> south-park.decrypted
```

**Usage (download code):**

```
$ python main.py
=== DRM File Decryptor ===
File name: south-park
Auth type: [1] file_password  [2] download_code
Choice (1/2): 2
Download code: ABC123
Authenticating...
Fetching key...
Fetching encrypted file...
Decrypting...
Done: 48302847 bytes -> south-park.decrypted
```

---

## Impact

- Any file on the platform is permanently decryptable by anyone who knows the file name and either a file password or download code.
- The decrypted file is a standard media file (MP4, PDF, etc.) with no residual DRM.
- The attack requires no browser, no browser extension, and no memory dumping.
- It is not detectable by the server — the four requests (page load, auth POST, key fetch, media fetch) are indistinguishable from a legitimate viewer session, including the nonce handshake.

---

## Recommended Fixes

### Applied — does not fix the vulnerability

**Nonce binding** (`drm_serve.php`): a single-use nonce is now generated at key-fetch time and
required on the subsequent media fetch. It is validated with `hash_equals` and unset from the
session immediately, preventing standalone replay of the media endpoint and enforcing sequential
pairing. This is the right hardening for the endpoints in isolation, but it cannot protect against
an attacker who simply calls both endpoints in order — which is exactly what the PoC does.

### Required to close the vulnerability

1. **Move decryption server-side.** This is the only fix that actually works. The server should
   decrypt the file and stream the plaintext bytes directly to the client over TLS, never exposing
   the key or the raw ciphertext. The client receives only the content it is authorised to view,
   in the session it authenticated, and cannot retain a re-decryptable copy.

2. **If client-side decryption cannot be removed**, adopt a hardware-backed DRM system (Widevine
   L1/L3, Apple FairPlay) where the Content Decryption Module runs in a trusted execution
   environment isolated from JavaScript. These systems are explicitly designed for the threat model
   where the client is untrusted. Rolling a custom AES scheme with a key endpoint is not a
   substitute.

3. **Segment delivery with short-lived per-segment keys.** As a partial mitigation if neither
   option above is feasible, stream small time-limited encrypted chunks rather than delivering the
   full key + full ciphertext in two requests. An attacker who captures one segment does not obtain
   the full file. This raises the cost of the attack but does not eliminate it — a patient attacker
   who captures every segment can still reconstruct the plaintext.

None of the JavaScript-based mitigations address the root cause and should not be treated as a
meaningful security control.
