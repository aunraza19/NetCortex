"""Run MikroTik CHR (free license) locally as NetCortex's test router.

    uv run python infra/chr/chr.py start   # boot (first run: provision + save a baseline)
    uv run python infra/chr/chr.py reset   # restore the baseline disk and boot again
    uv run python infra/chr/chr.py stop
    uv run python infra/chr/chr.py status

The image pin, QEMU flags and serial-console provisioning follow the partner's CI script
(.github/scripts/chr_bootstrap.py). Differences: the serial console is a TCP socket (works
on Windows), acceleration is KVM on Linux and TCG otherwise (WHPX loses the NICs), there are three
NICs (ether1 primary uplink, ether2 backup uplink, ether3 LAN), and the admin password comes
from CHR_PASSWORD in .env. Everything listens on 127.0.0.1 only. Disks live in var/chr/.
"""

import argparse
import hashlib
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import httpx
from netcortex_core import get_settings

VERSION = "7.24.5"
IMAGE_URL = f"https://download.mikrotik.com/routeros/{VERSION}/chr-{VERSION}.img.zip"
IMAGE_SHA256 = "16f07222a3213352c9c4fbea4f4dec6a8ffb78fdc0fa5e398c23103ed357c6eb"

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "var" / "chr"
IMAGE_ZIP = WORK / f"chr-{VERSION}.img.zip"
PRISTINE = WORK / f"chr-{VERSION}.img"  # as downloaded, never written
DISK = WORK / "chr.qcow2"  # the running router's disk (overlay on PRISTINE)
BASELINE = WORK / "baseline.qcow2"  # DISK right after provisioning + baseline.rsc
PID_FILE = WORK / "qemu.pid"
LOG_FILE = WORK / "qemu.log"
BASELINE_RSC = Path(__file__).with_name("baseline.rsc")

REST_PORT, SSH_PORT, SERIAL_PORT = 9180, 9122, 9123
REST_URL = f"http://127.0.0.1:{REST_PORT}"
BOOT_TIMEOUT_S = 300

ANSI = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-Z\\-_])")


class ChrError(RuntimeError):
    pass


# --- Image ----------------------------------------------------------------------------


def ensure_image() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    if not IMAGE_ZIP.exists():
        print(f"Downloading CHR {VERSION} ...", flush=True)
        with urllib.request.urlopen(IMAGE_URL, timeout=60) as response:
            IMAGE_ZIP.write_bytes(response.read())
    if hashlib.sha256(IMAGE_ZIP.read_bytes()).hexdigest() != IMAGE_SHA256:
        IMAGE_ZIP.unlink()
        raise ChrError("CHR image does not match the pinned SHA-256; deleted it")
    if not PRISTINE.exists():
        with zipfile.ZipFile(IMAGE_ZIP) as bundle:
            [name] = [n for n in bundle.namelist() if n.endswith(".img")]
            PRISTINE.write_bytes(bundle.read(name))


# --- QEMU -----------------------------------------------------------------------------


def qemu_binary(name: str) -> str:
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if found:
        return found
    windows = Path(r"C:\Program Files\qemu") / f"{name}.exe"
    if windows.exists():
        return str(windows)
    raise ChrError(
        f"{name} not found; install QEMU (winget install SoftwareFreedomConservancy.QEMU)"
    )


def accelerators() -> list[list[str]]:
    """Acceleration options to try, fastest first."""
    if sys.platform == "win32":
        # WHPX boots RouterOS 7.24.5 but it detects no PCI NICs (virtio or e1000), so
        # nothing is reachable. TCG works and boots in about 30 s.
        return [["-accel", "tcg"]]
    if Path("/dev/kvm").exists():
        return [["-accel", "kvm", "-cpu", "host"], ["-accel", "tcg"]]
    return [["-accel", "tcg"]]


def qemu_command(accel: list[str]) -> list[str]:
    command = [qemu_binary("qemu-system-x86_64"), "-M", "q35", "-m", "256", "-smp", "1", *accel]
    command += ["-drive", f"file={DISK},format=qcow2,if=virtio"]
    forwards = f"hostfwd=tcp:127.0.0.1:{REST_PORT}-:80,hostfwd=tcp:127.0.0.1:{SSH_PORT}-:22"
    command += ["-netdev", f"user,id=net0,{forwards}", "-device", "virtio-net-pci,netdev=net0"]
    for nic in (1, 2):  # ether2 (backup uplink) and ether3 (LAN): isolated, config only
        command += ["-netdev", f"user,id=net{nic},restrict=on"]
        command += ["-device", f"virtio-net-pci,netdev=net{nic}"]
    command += ["-display", "none", "-monitor", "none", "-no-reboot"]
    command += ["-chardev", f"socket,id=s0,host=127.0.0.1,port={SERIAL_PORT},server=on,wait=off"]
    command += ["-serial", "chardev:s0"]
    return command


def launch() -> None:
    """Start QEMU in the background, trying each accelerator until one stays up."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    for accel in accelerators():
        log = LOG_FILE.open("ab")
        process = subprocess.Popen(
            qemu_command(accel), stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=flags, start_new_session=sys.platform != "win32",
        )  # fmt: skip
        time.sleep(3)
        if process.poll() is None:
            PID_FILE.write_text(str(process.pid))
            print(f"QEMU started ({' '.join(accel[1:2])}), pid {process.pid}", flush=True)
            return
        print(f"QEMU exited with {' '.join(accel[1:2])}; trying the next accelerator", flush=True)
    raise ChrError(f"QEMU would not start; see {LOG_FILE}")


def qemu_running() -> bool:
    if not PID_FILE.exists():
        return False
    pid = PID_FILE.read_text().strip()
    if sys.platform == "win32":
        found = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=False,
        ).stdout  # fmt: skip
        return "qemu-system-x86_64" in found
    return Path(f"/proc/{pid}").exists()


def kill_qemu() -> None:
    if qemu_running():
        pid = PID_FILE.read_text().strip()
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, check=False)
        else:
            subprocess.run(["kill", pid], check=False)
    PID_FILE.unlink(missing_ok=True)


# --- RouterOS -------------------------------------------------------------------------


def credentials() -> tuple[str, str]:
    settings = get_settings()
    if settings.chr_password is None:
        raise ChrError("Set CHR_PASSWORD in .env (a local-only value) before starting CHR")
    return settings.chr_username or "admin", settings.chr_password.get_secret_value()


def rest_ready(username: str, password: str) -> bool:
    try:
        response = httpx.get(
            f"{REST_URL}/rest/system/resource", auth=(username, password), timeout=3
        )
        return response.status_code == 200 and bool(response.json().get("board-name"))
    except (httpx.HTTPError, ValueError):
        return False


def wait_for_rest(username: str, password: str, timeout_s: float = BOOT_TIMEOUT_S) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if rest_ready(username, password):
            return
        time.sleep(2)
    raise ChrError("CHR REST API did not answer in time")


def wait_until_settled(username: str, password: str, timeout_s: float = 120) -> None:
    """Wait until the config stops changing. RouterOS adds default items (for example a
    /system keymat-provider entry) a little after boot, which would spoil export diffs."""
    deadline = time.monotonic() + timeout_s
    previous, stable_polls = None, 0
    while time.monotonic() < deadline:
        export = run_script(username, password, "/export terse")
        current = [line for line in export.splitlines() if not line.startswith("#")]
        stable_polls = stable_polls + 1 if current == previous else 0
        if stable_polls >= 3:
            return
        previous = current
        time.sleep(3)
    print("warning: CHR config still changing after boot", flush=True)


def run_script(username: str, password: str, script: str) -> str:
    response = httpx.post(
        f"{REST_URL}/rest/execute",
        auth=(username, password),
        json={"script": script, "as-string": ""},
        timeout=30,
    )
    if response.status_code != 200:
        raise ChrError(f"RouterOS rejected the script: {response.text[:300]}")
    return response.json().get("ret", "")


def provision(password: str, timeout_s: float = BOOT_TIMEOUT_S) -> None:
    """First boot: log in on the serial console, set the admin password, enable REST."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            console = socket.create_connection(("127.0.0.1", SERIAL_PORT), timeout=2)
            break
        except OSError:
            if time.monotonic() > deadline:
                raise ChrError("serial console did not open") from None
            time.sleep(0.5)
    with console:
        _expect(console, r"login:\s*$", deadline)
        _send(console, "admin")
        _expect(console, r"password:\s*$", deadline)
        _send(console, "")  # CHR ships with an empty admin password
        seen = _expect(console, r"\[y/n\]:?\s*$|new password>?\s*$", deadline)
        if re.search(r"\[y/n\]", seen, re.I):
            _send(console, "n")
            seen = _expect(console, r"new password>?\s*$|enter to continue", deadline)
            if re.search(r"enter to continue", seen, re.I):
                _send(console, "")
                _expect(console, r"new password>?\s*$", deadline)
        _send(console, password)
        _expect(console, r"repeat new password>?\s*$", deadline)
        _send(console, password)
        _expect(console, r"\] >\s*$", deadline)
        _send(console, "/ip service set [find name=www] disabled=no rest-plain=yes")
        buffer = _expect(console, r"\] >\s*$", deadline)
        if re.search(r"bad command|syntax error|failure:", buffer, re.I):
            raise ChrError("RouterOS rejected enabling the www (REST) service")


def _send(console: socket.socket, line: str) -> None:
    console.sendall(line.encode() + b"\r")


def _expect(console: socket.socket, pattern: str, deadline: float) -> str:
    buffer = ""
    regex = re.compile(pattern, re.I | re.M)
    while time.monotonic() < deadline:
        console.settimeout(1)
        try:
            chunk = console.recv(4096)
        except TimeoutError:
            continue
        buffer += ANSI.sub("", chunk.decode("utf-8", errors="replace")).replace("\r", "")
        if regex.search(buffer):
            return buffer
    raise ChrError(f"timed out on the serial console waiting for /{pattern}/")


def apply_baseline(username: str, password: str) -> None:
    lines = [
        line.strip()
        for line in BASELINE_RSC.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    run_script(username, password, "\n".join(lines))


def shutdown(username: str, password: str) -> None:
    """Power off cleanly so RouterOS flushes its config to disk; kill if it hangs."""
    try:
        httpx.post(f"{REST_URL}/rest/system/shutdown", auth=(username, password), timeout=5)
    except httpx.HTTPError:
        pass  # the connection often drops as it powers off
    deadline = time.monotonic() + 60
    while qemu_running() and time.monotonic() < deadline:
        time.sleep(1)
    kill_qemu()


# --- Commands -------------------------------------------------------------------------


def start() -> None:
    username, password = credentials()
    if qemu_running() and rest_ready(username, password):
        print(f"CHR is already running: {REST_URL}")
        return
    kill_qemu()
    ensure_image()
    started = time.monotonic()
    if not BASELINE.exists():
        print("First start: provisioning CHR and saving a baseline ...", flush=True)
        DISK.unlink(missing_ok=True)
        subprocess.run(
            [qemu_binary("qemu-img"), "create", "-q", "-f", "qcow2", "-b", PRISTINE.name,
             "-F", "raw", str(DISK)],
            check=True, cwd=WORK,
        )  # fmt: skip
        launch()
        provision(password)
        wait_for_rest(username, password)
        apply_baseline(username, password)
        wait_until_settled(username, password)
        shutdown(username, password)
        shutil.copyfile(DISK, BASELINE)
    elif not DISK.exists():
        shutil.copyfile(BASELINE, DISK)
    launch()
    wait_for_rest(username, password)
    wait_until_settled(username, password)
    print(f"CHR is up after {time.monotonic() - started:.0f}s: {REST_URL} (SSH on {SSH_PORT})")


def reset() -> None:
    username, password = credentials()
    if not BASELINE.exists():
        raise ChrError("No baseline yet; run start first")
    if qemu_running():
        shutdown(username, password)
    shutil.copyfile(BASELINE, DISK)
    print("Restored the baseline disk", flush=True)
    start()


def stop() -> None:
    username, password = credentials()
    if qemu_running():
        shutdown(username, password)
    print("CHR stopped")


def status() -> None:
    username, password = credentials()
    running = qemu_running()
    print(f"QEMU running: {running}; REST answering: {running and rest_ready(username, password)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local CHR test router.")
    parser.add_argument("command", choices=["start", "reset", "stop", "status"])
    command = parser.parse_args().command
    try:
        {"start": start, "reset": reset, "stop": stop, "status": status}[command]()
    except ChrError as exc:
        print(f"CHR error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
