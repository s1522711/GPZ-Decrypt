import re
import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

BASE_URL = "https://files.radiocitygovernment.com"

def authenticate(session, file_name, credential, field_name):
    file_url = f"{BASE_URL}/f/{file_name}"

    # GET the file page to extract CSRF token
    resp = session.get(file_url)
    resp.raise_for_status()

    match = re.search(r'name=["\']pgz_csrf["\'][^>]*value=["\']([^"\']+)["\']|value=["\']([^"\']+)["\'][^>]*name=["\']pgz_csrf["\']', resp.text)
    if not match:
        raise ValueError("Could not find CSRF token on page")
    csrf = match.group(1) or match.group(2)

    # POST with CSRF + credential
    resp = session.post(file_url, data={"pgz_csrf": csrf, field_name: credential}, allow_redirects=True)
    resp.raise_for_status()

def fetch_key(session, file_name):
    url = f"{BASE_URL}/drm_serve.php?file={file_name}&action=key"
    resp = session.get(url)
    resp.raise_for_status()
    data = resp.json()
    return data["key"], data["nonce"]

def fetch_encrypted(session, file_name, nonce):
    url = f"{BASE_URL}/drm_serve.php?file={file_name}&action=media&nonce={nonce}"
    resp = session.get(url)
    resp.raise_for_status()
    return resp.content

def decrypt(encrypted_data, key_hex):
    key = bytes.fromhex(key_hex)
    iv = encrypted_data[:16]
    ciphertext = encrypted_data[16:]
    cipher = AES.new(key, AES.MODE_CBC, iv)
    return unpad(cipher.decrypt(ciphertext), AES.block_size)

def main():
    print("=== DRM File Decryptor ===")
    file_name = input("File name: ").strip()
    if not file_name:
        print("No file name provided.")
        return
    print("Auth type: [1] file_password  [2] download_code")
    auth_choice = input("Choice (1/2): ").strip()
    if auth_choice == "2":
        field_name = "download_code"
        credential = input("Download code: ").strip()
    else:
        field_name = "file_password"
        credential = input("File password: ").strip()

    output_path = file_name + ".decrypted"

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:149.0) Gecko/20100101 Firefox/149.0",
        "Referer": f"{BASE_URL}/f/{file_name}",
    })

    print("Authenticating...")
    authenticate(session, file_name, credential, field_name)

    print("Fetching key...")
    key_hex, nonce = fetch_key(session, file_name)

    print("Fetching encrypted file...")
    encrypted_data = fetch_encrypted(session, file_name, nonce)

    print("Decrypting...")
    decrypted = decrypt(encrypted_data, key_hex)

    with open(output_path, "wb") as f:
        f.write(decrypted)

    print(f"Done: {len(decrypted)} bytes -> {output_path}")

if __name__ == "__main__":
    main()
