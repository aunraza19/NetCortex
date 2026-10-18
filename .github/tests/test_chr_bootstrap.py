"""Offline tests for CHR lifecycle safety; these do not start a router."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "chr_bootstrap.py"
SPEC = importlib.util.spec_from_file_location("chr_bootstrap", MODULE_PATH)
assert SPEC and SPEC.loader
chr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(chr)


class FakeConsole:
    def __init__(
        self,
        *,
        automatic_password: bool = False,
        license_prompt: bool = False,
        license_display: bool = False,
        echo_secret: bool = False,
        password_mismatch: bool = False,
    ) -> None:
        self.buffer = (
            b"Do you want to see the software license? [Y/n]:\n"
            if license_display
            else b"Do you agree to the terms of this license? [Y/n]:\n"
            if license_prompt
            else b"login:\n"
        )
        self.sent: list[str] = []
        self.closed = False
        self.secret_count = 0
        self.automatic_password = automatic_password
        self.license_prompt = license_prompt
        self.license_display = license_display
        self.display_skipped = False
        self.echo_secret = echo_secret
        self.password_mismatch = password_mismatch
        self.reject_service_command = False
        self.raw_sent: list[bytes] = []

    def settimeout(self, _timeout: float) -> None:
        pass

    def connect(self, _path: str) -> None:
        pass

    def recv(self, _size: int) -> bytes:
        result, self.buffer = self.buffer, b""
        return result

    def sendall(self, data: bytes) -> None:
        self.raw_sent.append(data)
        value = data.decode().strip("\r\n")
        self.sent.append(value)
        prompts = {
            "admin": b"password:\n",
            "/password": b"current password:\n",
            "/ip service set [find name=www] disabled=no rest-plain=yes": (
                b"bad command name\n[admin@MikroTik] >\n"
                if self.reject_service_command
                else b"[admin@MikroTik] >\n"
            ),
        }
        if value.lower() == "n" and self.license_display:
            self.display_skipped = True
            self.buffer = b"Press Enter to continue\n"
        elif value == "" and self.display_skipped:
            self.display_skipped = False
            self.buffer = b"Do you agree to the terms of this license? [Y/n]:\n"
            self.license_prompt = True
        elif value.lower() == "y" and self.license_prompt:
            self.buffer = b"login:\n"
        elif value == "" and self.sent.count("") == 1 and self.automatic_password:
            self.buffer = b"new password:\n"
        elif value == "" and self.sent.count("") == 1:
            self.buffer = b"[admin@MikroTik] >\n"
        elif value == "" and self.sent.count("") == 2:
            self.buffer = b"new password:\n"
        elif value == "test-secret":
            self.secret_count += 1
            if self.password_mismatch and self.secret_count == 2:
                prompt = b"Try again, error: New passwords do not match!\nnew password>\n"
            else:
                prompt = (
                    b"repeat new password:\n" if self.secret_count == 1 else b"[admin@MikroTik] >\n"
                )
            self.buffer = (b"test-secret\r\n" if self.echo_secret else b"") + prompt
        else:
            self.buffer = prompts.get(value, b"")

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> FakeConsole:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class FakeRESTResponse:
    status = 200

    def __enter__(self) -> FakeRESTResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def read(self, _limit: int) -> bytes:
        return json.dumps({"board-name": "CHR", "version": chr.VERSION}).encode()


class BootstrapTests(unittest.TestCase):
    def test_serial_prompt_matching_strips_ansi_colors(self) -> None:
        class ColoredPrompt:
            def settimeout(self, _timeout: float) -> None:
                pass

            def recv(self, _size: int) -> bytes:
                return b"\x1b[32m[admin@MikroTik] >\x1b[0m\r\n"

        self.assertEqual(
            chr._recv_until(
                ColoredPrompt(),
                [("prompt", chr.re.compile(r"\[[^\]]+\]\s*(?:/[^\r\n]*)?[>#]\s*$", chr.re.M))],
                timeout=1,
                transcript=[],
            ),
            "prompt",
        )

    def test_serial_lines_use_single_carriage_return_delimiter(self) -> None:
        class RecordingStream:
            sent = b""

            def sendall(self, data: bytes) -> None:
                self.sent = data

        stream = RecordingStream()
        chr._send_line(stream, "admin")
        self.assertEqual(stream.sent, b"admin\r")

    def test_serial_reader_preserves_prompt_bytes_after_match(self) -> None:
        class BufferedPrompts:
            chunks = [b"login:\r\nnew password>\r\n"]

            def settimeout(self, _timeout: float) -> None:
                pass

            def recv(self, _size: int) -> bytes:
                return self.chunks.pop(0) if self.chunks else b""

        stream = BufferedPrompts()
        pending: list[str] = []
        transcript: list[str] = []
        self.assertEqual(
            chr._recv_until(
                stream,
                [("login", chr.re.compile(r"login:[ \t]*\r?$", chr.re.I | chr.re.M))],
                timeout=1,
                transcript=transcript,
                pending=pending,
            ),
            "login",
        )
        self.assertEqual(
            chr._recv_until(
                stream,
                [("new_password", chr.re.compile(r"new password>[ \t]*\r?$", chr.re.I | chr.re.M))],
                timeout=1,
                transcript=transcript,
                pending=pending,
            ),
            "new_password",
        )

    def test_release_is_pinned_to_official_versioned_url(self) -> None:
        self.assertEqual(chr.VERSION, "7.24.5")
        self.assertEqual(
            chr.IMAGE_URL,
            "https://download.mikrotik.com/routeros/7.24.5/chr-7.24.5.img.zip",
        )

    def test_qemu_only_exposes_management_ports_on_loopback_and_has_serial(self) -> None:
        command = chr.qemu_command(Path("/tmp/netcortex-chr/disk.img"), "qemu")
        joined = " ".join(command)
        self.assertIn("hostfwd=tcp:127.0.0.1:9180-:80", joined)
        self.assertIn("hostfwd=tcp:127.0.0.1:9122-:22", joined)
        self.assertIn("server=on,wait=off", joined)
        self.assertIn("-monitor none", joined)

    def test_provision_sets_new_admin_password_and_enables_rest(self) -> None:
        fake = FakeConsole(echo_secret=True)
        with tempfile.TemporaryDirectory() as temp:
            diagnostic = Path(temp) / "serial.log"
            with (
                patch.object(chr, "SERIAL_LOG_FILE", diagnostic),
                patch.object(chr.socket, "AF_UNIX", 1, create=True),
                patch.object(chr.socket, "socket", return_value=fake),
                patch.object(chr.time, "sleep"),
            ):
                chr.provision_console("test-secret", timeout=10)
            saved = diagnostic.read_text(encoding="utf-8")
            self.assertIn("[REDACTED]", saved)
            self.assertNotIn("test-secret", saved)
        self.assertIn("admin", fake.sent)
        self.assertIn("/password", fake.sent)
        self.assertIn("test-secret", fake.sent)
        self.assertIn("/ip service set [find name=www] disabled=no rest-plain=yes", fake.sent)

    def test_provision_handles_first_login_password_and_license_prompts(self) -> None:
        fake = FakeConsole(automatic_password=True, license_prompt=True)
        with (
            patch.object(chr.socket, "AF_UNIX", 1, create=True),
            patch.object(chr.socket, "socket", return_value=fake),
            patch.object(chr.time, "sleep"),
        ):
            chr.provision_console("test-secret", timeout=10)
        self.assertIn("y", fake.sent)
        self.assertNotIn("/password", fake.sent)
        self.assertEqual(fake.sent.count("test-secret"), 2)

    def test_license_display_is_skipped_then_terms_are_accepted(self) -> None:
        fake = FakeConsole(automatic_password=True, license_display=True)
        with (
            patch.object(chr.socket, "AF_UNIX", 1, create=True),
            patch.object(chr.socket, "socket", return_value=fake),
            patch.object(chr.time, "sleep"),
        ):
            chr.provision_console("test-secret", timeout=10)
        self.assertEqual(fake.sent[:3], ["n", "", "y"])
        self.assertEqual(fake.sent.count("test-secret"), 2)

    def test_provision_fails_when_router_rejects_rest_configuration(self) -> None:
        fake = FakeConsole(echo_secret=True)
        fake.reject_service_command = True
        with tempfile.TemporaryDirectory() as temp:
            diagnostic = Path(temp) / "serial.log"
            with (
                patch.object(chr, "SERIAL_LOG_FILE", diagnostic),
                patch.object(chr.socket, "AF_UNIX", 1, create=True),
                patch.object(chr.socket, "socket", return_value=fake),
                patch.object(chr.time, "sleep"),
                self.assertRaises(chr.BootstrapError),
            ):
                chr.provision_console("test-secret", timeout=10)
            self.assertNotIn("test-secret", diagnostic.read_text(encoding="utf-8"))
            self.assertIn("[REDACTED]", diagnostic.read_text(encoding="utf-8"))

    def test_password_mismatch_fails_immediately_and_saves_redacted_log(self) -> None:
        fake = FakeConsole(automatic_password=True, password_mismatch=True, echo_secret=True)
        with tempfile.TemporaryDirectory() as temp:
            diagnostic = Path(temp) / "serial.log"
            with (
                patch.object(chr, "SERIAL_LOG_FILE", diagnostic),
                patch.object(chr.socket, "AF_UNIX", 1, create=True),
                patch.object(chr.socket, "socket", return_value=fake),
                patch.object(chr.time, "sleep"),
                self.assertRaisesRegex(chr.BootstrapError, "password confirmation"),
            ):
                chr.provision_console("test-secret", timeout=10)
            self.assertEqual(fake.secret_count, 2)
            saved = diagnostic.read_text(encoding="utf-8")
            self.assertIn("New passwords do not match", saved)
            self.assertNotIn("test-secret", saved)

    def test_github_secret_mask_is_emitted_before_it_is_shared(self) -> None:
        with (
            patch.dict(chr.os.environ, {"GITHUB_ACTIONS": "true"}),
            patch("builtins.print") as output,
        ):
            chr._mask_github_secret("random-password")
        output.assert_called_once_with("::add-mask::random-password", flush=True)

    def test_rest_shape_must_be_single_resource_object(self) -> None:
        with patch.object(chr.urllib.request, "urlopen", return_value=FakeRESTResponse()):
            self.assertTrue(
                chr._authenticated_resource(chr.REST_URL + "/system/resource", "admin", "x")
            )

        class WrongShape(FakeRESTResponse):
            def read(self, _limit: int) -> bytes:
                return b'[{"board-name":"CHR"}]'

        with patch.object(chr.urllib.request, "urlopen", return_value=WrongShape()):
            self.assertFalse(
                chr._authenticated_resource(chr.REST_URL + "/system/resource", "admin", "x")
            )

    def test_ready_requires_two_consecutive_resource_probes(self) -> None:
        probes = iter([True, False, True, True])
        with patch.object(chr.time, "sleep"):
            chr.wait_for_rest("admin", "secret", timeout=5, probe=lambda *_args: next(probes))
        self.assertEqual(list(probes), [])

    def test_cleanup_refuses_unowned_pid(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            pid_file = Path(temp) / "qemu.pid"
            pid_file.write_text("999999999", encoding="ascii")
            with patch.object(chr, "PID_FILE", pid_file):
                chr.cleanup()
            self.assertFalse(pid_file.exists())

    def test_process_ownership_requires_qemu_and_owned_disk(self) -> None:
        image = Path("/tmp/netcortex-chr/chr-7.24.5.img")
        self.assertTrue(chr.is_owned_qemu_command(f"qemu-system-x86_64 -drive {image}", image))
        self.assertFalse(chr.is_owned_qemu_command("python worker.py", image))
        self.assertFalse(
            chr.is_owned_qemu_command("qemu-system-x86_64 -drive /tmp/other.img", image)
        )


if __name__ == "__main__":
    unittest.main()
