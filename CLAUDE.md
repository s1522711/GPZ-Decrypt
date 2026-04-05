# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the tool

```bash
uv run main.py
```

Or via the installed script entry point:

```bash
uv run PGZ-Decrypt
```

## Architecture

This is a single-file POC (`main.py`) with four stages that run sequentially within one `requests.Session`:

1. **`authenticate`** — GETs the file page to scrape the `pgz_csrf` token, then POSTs it back with the credential (`file_password` or `download_code`) to establish a `PGZ_SESSION` cookie.
2. **`fetch_key`** — GETs `drm_serve.php?action=key`; returns both the AES-256 hex key and a single-use nonce from the JSON response.
3. **`fetch_encrypted`** — GETs `drm_serve.php?action=media&nonce={nonce}`; the nonce is validated and consumed server-side, so key fetch must precede media fetch.
4. **`decrypt`** — AES-256-CBC; IV is the first 16 bytes of the returned binary, remainder is PKCS#7-padded ciphertext.

The session cookie is the only auth mechanism between steps — all four requests must share the same `requests.Session`.

## Target

`BASE_URL = "https://files.radiocitygovernment.com"` — defined at the top of `main.py`.
