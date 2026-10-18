#!/usr/bin/env python3
"""Download, boot, provision, and validate the pinned CHR used by CI."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

VERSION = "7.24.5"
IMAGE_URL = f"https://download.mikrotik.com/routeros/{VERSION}/chr-{VERSION}.img.zip"
IMAGE_SHA256 = "16f07222a3213352c9c4fbea4f4dec6a8ffb78fdc0fa5e398c23103ed357c6eb"
WORK_DIR = Path("/tmp/netcortex-chr")
IMAGE_ZIP = WORK_DIR / f"chr-{VERSION}.img.zip"
IMAGE = WORK_DIR / f"chr-{VERSION}.img"
PID_FILE = WORK_DIR / "qemu.pid"
LOG_FILE = WORK_DIR / "qemu.log"
SERIAL_LOG_FILE = WORK_DIR / "serial.log"
CONSOLE_SOCKET = WORK_DIR / "serial.sock"
REST_URL = "http://127.0.0.1:9180/rest"
ANSI_ESCAPE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 180
BOOT_TIMEOUT_SECONDS = 360


class BootstrapError(RuntimeError):
    """Raised when the isolated CHR cannot be prepared safely."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_image(path: Path, expected: str = IMAGE_SHA256) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise BootstrapError("CHR image SHA-256 pin is not finalized")
    actual = sha256_file(path)
    if not secrets.compare_digest(actual, expected):
        raise BootstrapError(f"CHR image digest mismatch: got {actual}")


def download_image(destination: Path = IMAGE_ZIP) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        verify_image(destination)
        return
    request = urllib.request.Request(IMAGE_URL, headers={"User-Agent": "NetCortex-CI/1.0"})
    temporary = destination.with_suffix(destination.suffix + ".part")
    try:
        deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SECONDS
        with urllib.request.urlopen(request, timeout=15) as response:
            declared_size = response.headers.get("Content-Length")
            if declared_size and int(declared_size) > MAX_DOWNLOAD_BYTES:
                raise BootstrapError("CHR artifact exceeds the configured size limit")
            digest = hashlib.sha256()
            size = 0
            with temporary.open("wb") as output:
                while True:
                    if time.monotonic() >= deadline:
                        raise BootstrapError("CHR image download exceeded its finite time budget")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise BootstrapError("CHR artifact exceeds the configured size limit")
                    digest.update(chunk)
                    output.write(chunk)
            if not secrets.compare_digest(digest.hexdigest(), IMAGE_SHA256):
                raise BootstrapError(f"CHR image digest mismatch: got {digest.hexdigest()}")
            temporary.replace(destination)
    except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
        raise BootstrapError(f"Unable to download pinned CHR image: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)


def extract_image(archive: Path = IMAGE_ZIP, destination: Path = IMAGE) -> Path:
    verify_image(archive)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as bundle:
        candidates = [item for item in bundle.infolist() if item.filename.endswith(".img")]
        if len(candidates) != 1:
            raise BootstrapError("Pinned CHR zip must contain exactly one .img file")
        candidate = candidates[0]
        if candidate.file_size > 512 * 1024 * 1024:
            raise BootstrapError("CHR disk image exceeds the configured size limit")
        with bundle.open(candidate) as source, destination.open("wb") as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
    return destination


def acceleration(kvm_path: Path = Path("/dev/kvm")) -> list[str]:
    if platform.system() == "Linux" and kvm_path.exists() and os.access(kvm_path, os.W_OK):
        return ["-accel", "kvm", "-cpu", "host"]
    return ["-accel", "tcg,tb-size=256"]


def qemu_command(image: Path, qemu: str = "qemu-system-x86_64") -> list[str]:
    return [
        qemu,
        "-M",
        "q35",
        "-m",
        "256",
        "-smp",
        "1",
        *acceleration(),
        "-drive",
        f"file={image},format=raw,if=virtio",
        "-netdev",
        "user,id=net0,hostfwd=tcp:127.0.0.1:9180-:80,hostfwd=tcp:127.0.0.1:9122-:22",
        "-device",
        "virtio-net-pci,netdev=net0",
        "-display",
        "none",
        "-chardev",
        f"socket,id=serial0,path={CONSOLE_SOCKET},server=on,wait=off",
        "-serial",
        "chardev:serial0",
        "-monitor",
        "none",
        "-no-reboot",
    ]


def is_owned_qemu_command(command: str, image: Path = IMAGE) -> bool:
    return "qemu-system-x86_64" in command and str(image) in command


def _recv_until(
    stream: socket.socket,
    patterns: list[tuple[str, re.Pattern[str]]],
    timeout: float,
    transcript: list[str],
) -> str:
    deadline = time.monotonic() + timeout
    buffer = ""
    while time.monotonic() < deadline:
        stream.settimeout(min(1.0, max(0.1, deadline - time.monotonic())))
        try:
            chunk = stream.recv(4096)
        except TimeoutError:
            continue
        if not chunk:
            continue
        decoded = ANSI_ESCAPE.sub("", chunk.decode("utf-8", errors="replace"))
        buffer += decoded
        transcript.append(decoded)
        for label, pattern in patterns:
            if pattern.search(buffer):
                return label
        if len(buffer) > 16000:
            buffer = buffer[-8000:]
    raise BootstrapError("Timed out waiting for RouterOS serial prompt")


def _send_line(stream: socket.socket, line: str) -> None:
    stream.sendall(line.encode("utf-8") + b"\r\n")


def provision_console(password: str, timeout: int = 120) -> None:
    """Set the first-login admin password and enable HTTP REST for loopback CI."""
    deadline = time.monotonic() + timeout
    transcript: list[str] = []
    patterns = [
        (
            "command_error",
            re.compile(r"(?:bad command name|expected end of command|syntax error|failure:)", re.I),
        ),
        (
            "license_display",
            re.compile(r"do you want to see.*software license.*\[y/n\]\s*:?", re.I),
        ),
        (
            "license_continue",
            re.compile(r"press (?:the )?enter to continue\s*:?", re.I),
        ),
        (
            "license_agreement",
            re.compile(
                r"(?:do you agree.*(?:\[y/n\]|yes/no)|"
                r"(?:license|licence).*(?:accept|agree).*(?:\[y/n\]|yes/no))",
                re.I,
            ),
        ),
        ("login", re.compile(r"login:\s*$", re.I | re.M)),
        ("repeat_password", re.compile(r"repeat(?:\s+new)? password:?\s*>?\s*$", re.I | re.M)),
        ("new_password", re.compile(r"new password:?\s*>?\s*$", re.I | re.M)),
        ("current_password", re.compile(r"current password:?\s*>?\s*$", re.I | re.M)),
        ("password", re.compile(r"(?:^|\n)password:\s*$", re.I | re.M)),
        ("prompt", re.compile(r"\[[^\]]+\]\s*(?:/[^\r\n]*)?[>#]\s*$", re.M)),
    ]
    try:
        while time.monotonic() < deadline:
            try:
                stream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                stream.settimeout(1)
                stream.connect(str(CONSOLE_SOCKET))
                break
            except (FileNotFoundError, ConnectionRefusedError, TimeoutError, OSError):
                stream.close()
                time.sleep(0.25)
        else:
            raise BootstrapError("RouterOS serial console socket did not appear")

        with stream:
            logged_in = False
            sent_login = False
            sent_blank_password = False
            sent_old_password = False
            sent_new_password = False
            sent_repeat_password = False
            requested_password_change = False
            sent_license_display = False
            sent_license_continue = False
            sent_license_accept = False
            while time.monotonic() < deadline:
                remaining = max(1, int(deadline - time.monotonic()))
                # TCG can take longer than 20 seconds to reach the first login prompt.
                # Keep waiting, but never extend beyond the caller's overall deadline.
                prompt = _recv_until(stream, patterns, remaining, transcript)
                if prompt == "command_error":
                    raise BootstrapError("RouterOS rejected a serial provisioning command")
                if prompt == "license_display" and not sent_license_display:
                    _send_line(stream, "n")
                    sent_license_display = True
                elif prompt == "license_continue" and not sent_license_continue:
                    _send_line(stream, "")
                    sent_license_continue = True
                elif prompt == "license_agreement" and not sent_license_accept:
                    _send_line(stream, "y")
                    sent_license_accept = True
                elif prompt == "login" and not sent_login:
                    _send_line(stream, "admin")
                    sent_login = True
                elif prompt == "password" and not sent_blank_password:
                    _send_line(stream, "")
                    sent_blank_password = True
                elif prompt == "current_password" and not sent_old_password:
                    _send_line(stream, "")
                    sent_old_password = True
                elif prompt == "new_password" and not sent_new_password:
                    _send_line(stream, password)
                    sent_new_password = True
                elif prompt == "repeat_password" and not sent_repeat_password:
                    _send_line(stream, password)
                    sent_repeat_password = True
                elif prompt == "prompt":
                    if sent_repeat_password:
                        logged_in = True
                        break
                    if sent_new_password:
                        raise BootstrapError(
                            "RouterOS returned to the prompt before password confirmation"
                        )
                    if not requested_password_change:
                        _send_line(stream, "/password")
                        requested_password_change = True
                        continue
                    raise BootstrapError("RouterOS did not request a new admin password")
                elif prompt == "login" and sent_login:
                    raise BootstrapError("RouterOS rejected initial console login")
            if not logged_in:
                raise BootstrapError("RouterOS serial login/provisioning timed out")

            for command in ("/ip service set [find name=www] disabled=no rest-plain=yes",):
                _send_line(stream, command)
                outcome = _recv_until(stream, patterns[:1] + [patterns[-1]], 15, transcript)
                if outcome == "command_error":
                    raise BootstrapError("RouterOS rejected the www REST service configuration")
    except BootstrapError:
        _write_serial_diagnostics(transcript, password)
        raise
    except OSError as exc:
        _write_serial_diagnostics(transcript, password)
        raise BootstrapError(f"RouterOS serial console failed ({type(exc).__name__})") from exc


def _write_serial_diagnostics(transcript: list[str], secret: str) -> None:
    SERIAL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    sanitized = "".join(transcript).replace(secret, "[REDACTED]")
    SERIAL_LOG_FILE.write_text(sanitized, encoding="utf-8")


def _authenticated_resource(url: str, username: str, password: str, timeout: float = 3.0) -> bool:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    token = (username + ":" + password).encode("utf-8")
    import base64

    request.add_header("Authorization", "Basic " + base64.b64encode(token).decode("ascii"))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return False
            body = json.loads(response.read(256 * 1024))
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return False
    return (
        isinstance(body, dict)
        and isinstance(body.get("board-name"), str)
        and bool(body["board-name"])
    )


def wait_for_rest(
    username: str,
    password: str,
    timeout: int = BOOT_TIMEOUT_SECONDS,
    probe: Callable[[str, str, str], bool] = _authenticated_resource,
) -> None:
    deadline = time.monotonic() + timeout
    consecutive = 0
    while time.monotonic() < deadline:
        if probe(REST_URL + "/system/resource", username, password):
            consecutive += 1
            if consecutive == 2:
                return
        else:
            consecutive = 0
        time.sleep(2)
    raise BootstrapError("CHR REST did not return two consecutive authenticated resource objects")


def _write_github_env(password: str) -> None:
    env_path = os.environ.get("GITHUB_ENV")
    if not env_path:
        return
    with Path(env_path).open("a", encoding="utf-8") as output:
        output.write("CHR_REST_URL=" + REST_URL + "\n")
        output.write("CHR_REST_USERNAME=admin\n")
        output.write("CHR_REST_PASSWORD=" + password + "\n")


def _mask_github_secret(password: str) -> None:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::add-mask::{password}", flush=True)


def start() -> None:
    if platform.system() != "Linux":
        raise BootstrapError("CHR bootstrap currently requires a Linux runner")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        cleanup()
    download_image()
    extract_image()
    qemu = shutil.which("qemu-system-x86_64")
    if not qemu:
        raise BootstrapError("qemu-system-x86_64 is required; install qemu-system-x86")
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    log = LOG_FILE.open("ab", buffering=0)
    process = subprocess.Popen(
        qemu_command(IMAGE, qemu),
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    PID_FILE.write_text(str(process.pid), encoding="ascii")
    password = secrets.token_urlsafe(32)
    _mask_github_secret(password)
    try:
        provision_console(password)
        wait_for_rest("admin", password)
        _write_github_env(password)
        print("CHR authenticated REST endpoint is ready at " + REST_URL)
    except Exception:
        cleanup()
        raise


def cleanup() -> None:
    if not PID_FILE.exists():
        return
    try:
        pid = int(PID_FILE.read_text(encoding="ascii").strip())
    except (ValueError, OSError):
        PID_FILE.unlink(missing_ok=True)
        raise BootstrapError("Refusing cleanup: invalid CHR PID file") from None
    if pid <= 1:
        raise BootstrapError("Refusing cleanup: unsafe CHR PID")
    cmdline = Path(f"/proc/{pid}/cmdline")
    if not cmdline.exists():
        PID_FILE.unlink(missing_ok=True)
        return
    command = cmdline.read_bytes().replace(b"\0", b" ").decode("utf-8", errors="replace")
    if not is_owned_qemu_command(command):
        raise BootstrapError("Refusing cleanup: PID does not match the owned CHR QEMU command")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not cmdline.exists():
            break
        time.sleep(0.2)
    else:
        os.kill(pid, signal.SIGKILL)
    PID_FILE.unlink(missing_ok=True)
    CONSOLE_SOCKET.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("start", "cleanup"))
    args = parser.parse_args()
    try:
        if args.action == "start":
            start()
        else:
            cleanup()
    except BootstrapError as exc:
        print(f"CHR bootstrap error: {exc}", file=sys.stderr)
        print(f"Diagnostics retained at {LOG_FILE} and {SERIAL_LOG_FILE}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
