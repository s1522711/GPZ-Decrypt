# DRM Bypass POC — ProGrade Zenith File Server

## Summary

The ProGrade Zenith (PGZ) file serving platform at `files.radiocitygovernment.com` implements a
client-side DRM scheme that is trivially bypassable. The encryption key for every protected file
is served directly to any authenticated browser session via an unauthenticated-by-design API
endpoint. An attacker who knows the file name and either a file password or a download code can
download and permanently decrypt any protected file in a single script with no specialised tooling.

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
| `GET /drm_serve.php?file={name}&action=key` | Deliver decryption key | `{"key": "<hex>", "nonce": "<hex>"}` |
| `GET /drm_serve.php?file={name}&action=media` | Deliver ciphertext | Raw encrypted binary |

Serving the key and the ciphertext to the same party is the fundamental flaw. No DRM scheme is
secure if the client holds both.

---

## Attack Flow

```
1. GET  /f/{file}              — Load the access form, scrape pgz_csrf token
2. POST /f/{file}              — Submit pgz_csrf + credential (see below) → receive PGZ_SESSION cookie
3. GET  /drm_serve.php?...key  — Receive AES-256 key in plaintext JSON
4. GET  /drm_serve.php?...media — Receive AES-256-CBC encrypted file
5. Decrypt locally             — IV = first 16 bytes of ciphertext; remainder is payload
6. Write plaintext to disk
```

### Authentication Credential Types

The POST in step 2 accepts two mutually exclusive credential fields depending on how the file was shared:

| Field name | Used when |
|---|---|
| `file_password` | File is protected by a numeric/alphanumeric password |
| `download_code` | File is shared via a one-time or reusable download code |

The CSRF scrape and session cookie mechanism is identical in both cases — only the POST field name differs.

Steps 3–6 are performed entirely offline once the session cookie is obtained.

---

## Encryption Scheme

The server uses **AES-256-CBC**:

- **Key**: 256-bit, hex-encoded, returned verbatim in the key endpoint JSON
- **IV**: prepended as the first 16 bytes of the encrypted file
- **Padding**: PKCS#7

The `nonce` field in the key response is unused by the decryption process.

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
- It is not detectable by the server — the requests are indistinguishable from legitimate viewer requests.

---

## Recommended Fixes

1. **Never send the key to the client.** Decrypt server-side and stream the plaintext, or use a
   proper DRM system (Widevine, FairPlay) that keeps keys in a hardware-backed trusted execution
   environment.

2. **Bind the key to a single-use token.** If client-side decryption must be used, issue a
   short-lived, single-use key token tied to the session and media item, and expire it after first
   use.

3. **Segment delivery.** Stream small encrypted chunks with per-chunk keys rather than delivering
   the entire key + ciphertext at once. This limits the window of exposure, though it does not
   eliminate it.

None of the JavaScript-based mitigations address the root cause and should not be treated as a
meaningful security control.
