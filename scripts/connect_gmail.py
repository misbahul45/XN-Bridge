"""Human OAuth bootstrap using the installed Gmail provider's existing flow.

Run with .providers/gmail/bin/python. No cloud provisioning or mail mutation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "data/private"
CLIENT = PRIVATE / "gmail-client-secret.json"
CONSOLE = "https://console.cloud.google.com/auth/clients"
READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SAFE_SCOPES = {READONLY, "openid", "https://www.googleapis.com/auth/userinfo.email", "https://www.googleapis.com/auth/userinfo.profile"}


class SetupError(ValueError):
    """Only these authored messages are safe to show in the terminal."""


def read_client(path: Path) -> tuple[bytes, str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise SetupError("Client OAuth harus berupa file biasa")
        raw = handle.read(65537)
    if len(raw) > 65536:
        raise SetupError("File client OAuth terlalu besar")
    try:
        obj = json.loads(raw)
    except ValueError:
        raise SetupError("File client OAuth bukan JSON valid") from None
    kinds = [k for k in ("installed", "web") if isinstance(obj, dict) and isinstance(obj.get(k), dict)]
    if len(kinds) != 1:
        raise SetupError("Gunakan JSON client Google Desktop app atau Web application")
    cfg = obj[kinds[0]]
    if not isinstance(cfg.get("client_id"), str) or not cfg["client_id"].endswith(".apps.googleusercontent.com") or not isinstance(cfg.get("client_secret"), str) or not cfg["client_secret"]:
        raise SetupError("Client ID/secret Google belum lengkap")
    if cfg.get("auth_uri") not in {"https://accounts.google.com/o/oauth2/auth", "https://accounts.google.com/o/oauth2/v2/auth"} or cfg.get("token_uri") != "https://oauth2.googleapis.com/token":
        raise SetupError("Endpoint OAuth harus milik Google; endpoint lain ditolak")
    return raw, kinds[0]


def install_client(source: Path, destination: Path = CLIENT) -> str:
    raw, kind = read_client(source)
    if destination.parent.is_symlink():
        raise SetupError("Direktori private tidak boleh berupa symlink")
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(destination.parent, 0o700)
    if destination.exists() or destination.is_symlink():
        existing, _ = read_client(destination)
        if existing != raw:
            raise SetupError("Client berbeda sudah tersimpan; tidak ditimpa otomatis")
        os.chmod(destination, 0o600)
        return kind
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    return kind


def download_candidate(directory: Path, since: float) -> Path | None:
    paths = [p for p in directory.glob("client_secret*.json") if not p.is_symlink() and p.is_file() and p.stat().st_mtime >= since]
    return paths[0] if len(paths) == 1 else None


def downloads_directory() -> Path:
    try:
        result = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip().startswith("/"):
            return Path(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Downloads"


def write_status(status: str):
    if PRIVATE.is_symlink():
        raise SetupError("Direktori private tidak boleh berupa symlink")
    PRIVATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = PRIVATE / "gmail-connection-status.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump({"status": status, "updated_at": time.time(), "scope": READONLY, "provider": "gmail"}, handle)


def configure_provider():
    os.environ.update({"GOOGLE_CLIENT_SECRET_PATH": str(CLIENT), "WORKSPACE_MCP_CREDENTIALS_DIR": str(PRIVATE / "gmail-tokens"),
                       "WORKSPACE_MCP_CREDENTIAL_STORE_BACKEND": "local_directory", "MCP_ENABLE_OAUTH21": "false"})
    for name in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI", "GOOGLE_SERVICE_ACCOUNT_KEY_FILE", "GOOGLE_SERVICE_ACCOUNT_KEY_JSON"):
        os.environ.pop(name, None)
    # Do not log callback codes, account identities or state from upstream diagnostics.
    logging.disable(logging.CRITICAL)
    from gmail_stdio import configure
    configure()
    from auth.scopes import set_enabled_tools, set_read_only, get_current_scopes
    from auth.permissions import parse_permissions_arg, set_permissions
    set_enabled_tools(["gmail"])
    set_read_only(True)
    set_permissions(parse_permissions_arg(["gmail:readonly"]))
    scopes = set(get_current_scopes())
    if READONLY not in scopes or not scopes <= SAFE_SCOPES:
        raise SetupError("Provider meminta scope di luar Gmail baca-saja")
    return sorted(scopes)


async def authorize(timeout: int, email: str | None) -> bool:
    from auth.credential_store import get_credential_store
    from auth.google_auth import start_auth_flow
    from auth.oauth_callback_server import ensure_stdio_oauth_callback_available, cleanup_oauth_callback_server
    from auth.oauth_config import get_oauth_redirect_uri
    from main import resolve_stdio_callback_port

    resolve_stdio_callback_port()
    ok, _ = await asyncio.to_thread(ensure_stdio_oauth_callback_available)
    if not ok:
        raise SetupError("Callback loopback tidak tersedia; tutup sesi OAuth lain lalu ulangi")
    try:
        message = await start_auth_flow(email, "Gmail", get_oauth_redirect_uri())
        match = re.search(r"https://accounts\.google\.com/[^\s<>\)]+", message)
        if not match:
            raise SetupError("Google OAuth belum dapat dimulai; periksa client/API/redirect di Google Console")
        print("\nSelesaikan login dan izin di browser Google. Jika tab tidak terbuka, buka URL ini di browser pribadi:\n" + match.group(0), flush=True)
        print("Hanya Gmail baca-saja. Tidak ada email yang dikirim. Menunggu callback...", flush=True)
        write_status("AWAITING_CONSENT")
        store = get_credential_store()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            users = store.list_users()
            if email:
                users = [u for u in users if u.casefold() == email.casefold()]
            if len(users) == 1:
                credential = store.get_credential(users[0])
                if credential and set(credential.scopes or []) <= SAFE_SCOPES:
                    from googleapiclient.discovery import build
                    from google_auth_httplib2 import AuthorizedHttp
                    from httplib2 import Http
                    service = build("gmail", "v1", http=AuthorizedHttp(credential, http=Http(timeout=20)), cache_discovery=False)
                    try:
                        result = await asyncio.to_thread(lambda: service.users().messages().list(userId="me", q="newer_than:1d", maxResults=1).execute())
                    finally:
                        service.close()
                    if not isinstance(result, dict):
                        raise SetupError("Respons verifikasi Gmail tidak valid")
                    subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "xnbridge.cli", "catalog", "health", "--server", "gmail", "--status", "OK", "--detail", "Owner OAuth completed and one read-only metadata request succeeded"], cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
                    write_status("CONNECTED_READONLY")
                    print("Gmail tersambung. Permintaan metadata baca-saja berhasil; tidak ada isi pesan ditampilkan.", flush=True)
                    return True
            await asyncio.sleep(1)
        write_status("CONSENT_TIMEOUT")
        print("Batas waktu izin habis. Jalankan ulang saat siap; tidak ada pengiriman email.", flush=True)
        return False
    finally:
        cleanup_oauth_callback_server()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Sambungkan Gmail lokal melalui OAuth Google resmi, baca-saja")
    parser.add_argument("--client", type=Path, help="JSON client Google; isinya tidak dicetak")
    parser.add_argument("--check", action="store_true", help="validasi kesiapan lokal tanpa login/browser/jaringan")
    parser.add_argument("--open-console", action="store_true")
    parser.add_argument("--watch-downloads", action="store_true", help="impor hanya satu client_secret*.json baru yang diunduh selama sesi ini")
    parser.add_argument("--wait-for-client", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--email", help="opsional: batasi akun yang diverifikasi")
    args = parser.parse_args(argv)
    if not 0 <= args.wait_for_client <= 1800 or not 1 <= args.timeout <= 900:
        parser.error("wait-for-client harus 0..1800; timeout 1..900 detik")
    os.umask(0o077)
    started = time.time()
    try:
        if args.client:
            install_client(args.client.expanduser())
        if not CLIENT.is_file():
            print("Client OAuth Google belum tersedia. Tidak ada kunci/client universal untuk semua aplikasi.")
            print("1. Di Google Console pilih project milik Anda dan aktifkan Gmail API.")
            print("2. Konfigurasikan consent, tambahkan akun sendiri sebagai test user bila perlu.")
            print("3. Buat client OAuth Desktop app lalu unduh JSON client ke Downloads.")
            print("   Atau simpan JSON langsung ke: " + str(CLIENT))
            print("Google Console: " + CONSOLE, flush=True)
            if args.check:
                return 2
            write_status("WAITING_CLIENT")
            if args.open_console:
                webbrowser.open(CONSOLE)
            deadline = time.monotonic() + args.wait_for_client
            downloads = downloads_directory() if args.watch_downloads else None
            while not CLIENT.is_file() and time.monotonic() < deadline:
                candidate = download_candidate(downloads, started) if downloads else None
                if candidate:
                    install_client(candidate)
                    print("Client Google baru diimpor ke penyimpanan private.", flush=True)
                    break
                time.sleep(1)
            if not CLIENT.is_file():
                write_status("CLIENT_REQUIRED")
                print("Client belum tersedia dalam batas waktu. Jalankan wizard lagi setelah client siap.", flush=True)
                return 2
        kind = install_client(CLIENT)
        if kind == "web":
            raise SetupError("Wizard interaktif memakai client Desktop app; client Web memerlukan redirect terdaftar yang sesuai")
        scopes = configure_provider()
        if args.check:
            print(json.dumps({"status": "READY_FOR_CONSENT", "client_type": kind, "scopes": scopes}))
            return 0
        return 0 if asyncio.run(authorize(args.timeout, args.email)) else 3
    except Exception as error:
        # Error messages from our validators contain no credential values.
        print("Penyiapan belum selesai: " + (str(error) if isinstance(error, SetupError) else type(error).__name__), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Penyiapan dihentikan. Tidak ada email dikirim.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
