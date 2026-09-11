# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware-aware local AI setup: model choice, microphone, peripherals, printers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import os
from pathlib import Path
import re
import shutil
import subprocess
import wave
from typing import Any


EventCallback = Callable[[dict[str, Any]], None]


class AiSetupError(RuntimeError):
    """An actionable failure while probing hardware or running a helper tool."""


# Smallest-to-largest local models, mirroring the tiers Voice2Text AI documents
# in its README. Each tier is keyed by the minimum GB of *usable* memory (GPU
# VRAM when a GPU is present, otherwise system RAM) it should be offered at.
MODEL_TIERS: tuple[tuple[float, str, str], ...] = (
    (0.0, "qwen2:0.5b", "Fastest replies on minimal or shared hardware (~350MB download)."),
    (8.0, "qwen2:7b", "A balanced model for a typical desktop or laptop."),
    (17.0, "qwen3.6:27b", "The best local quality; needs a GPU with 17GB+ VRAM."),
)

OLLAMA_INSTALL_COMMAND = "curl -fsSL https://ollama.com/install.sh | sh"

# Ollama draws its download progress with terminal control codes even when its
# output is a pipe, so they have to come back out before the text reaches a
# GTK label.
_TERMINAL_CONTROL = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b[()][A-Z0-9]|\x1b[=>]|[\r\x07]")


def clean_progress_line(line: str) -> str:
    """Strip terminal control codes from one line of a helper's progress output."""
    return _TERMINAL_CONTROL.sub("", line).strip()


@dataclass(frozen=True)
class HardwareProfile:
    ram_gb: float
    gpu_name: str | None
    gpu_vram_gb: float

    @property
    def budget_gb(self) -> float:
        """The GB of memory that should drive the local model recommendation."""

        return self.gpu_vram_gb if self.gpu_name else self.ram_gb


@dataclass(frozen=True)
class ModelRecommendation:
    model: str
    reason: str
    profile: HardwareProfile


@dataclass(frozen=True)
class PeripheralCheck:
    name: str
    present: bool
    detail: str


@dataclass(frozen=True)
class PrinterInfo:
    uri: str
    make_and_model: str


@dataclass(frozen=True)
class MicrophoneResult:
    ok: bool
    peak_level: float
    message: str


@dataclass
class AiSetupModel:
    """GTK-independent progress model for AI setup tasks, used by the UI and its tests."""

    details: list[str] = field(default_factory=list)
    summary: str = "Ready"

    def apply(self, event: dict[str, Any]) -> None:
        kind = str(event.get("event", "detail"))
        message = str(event.get("message", "")).strip()
        if kind in {"task-start", "task-success", "task-failure", "summary"} and message:
            self.summary = message
        elif message:
            self.summary = message
        if message:
            self.details.append(message)


def _read_ram_gb(meminfo_path: str | os.PathLike[str]) -> float:
    try:
        text = Path(meminfo_path).read_text(encoding="utf-8")
    except OSError:
        return 0.0
    match = re.search(r"^MemTotal:\s+(\d+)\s*kB", text, re.MULTILINE)
    if not match:
        return 0.0
    return round(int(match.group(1)) / (1024 * 1024), 1)


def _detect_gpu(nvidia_smi: str) -> tuple[str | None, float]:
    binary = shutil.which(nvidia_smi)
    if not binary:
        return None, 0.0
    try:
        result = subprocess.run(
            [binary, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, 0.0
    if result.returncode != 0:
        return None, 0.0
    first_line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not first_line:
        return None, 0.0
    name, _, memory = first_line.rpartition(",")
    name = name.strip()
    try:
        vram_mib = float(memory.strip())
    except ValueError:
        return None, 0.0
    return (name or None), round(vram_mib / 1024, 1)


def detect_hardware() -> HardwareProfile:
    meminfo_path = os.environ.get("SPACED_WELCOME_MEMINFO", "/proc/meminfo")
    nvidia_smi = os.environ.get("SPACED_WELCOME_NVIDIA_SMI", "nvidia-smi")
    ram_gb = _read_ram_gb(meminfo_path)
    gpu_name, gpu_vram_gb = _detect_gpu(nvidia_smi)
    return HardwareProfile(ram_gb=ram_gb, gpu_name=gpu_name, gpu_vram_gb=gpu_vram_gb)


def recommend_model(profile: HardwareProfile) -> ModelRecommendation:
    chosen = MODEL_TIERS[0]
    for tier in MODEL_TIERS:
        if profile.budget_gb >= tier[0]:
            chosen = tier
    _, model, reason = chosen
    return ModelRecommendation(model=model, reason=reason, profile=profile)


def _glob_check(name: str, root: Path, pattern: str) -> PeripheralCheck:
    try:
        matches = sorted(path.name for path in root.glob(pattern))
    except OSError:
        matches = []
    present = bool(matches)
    detail = f"detected ({', '.join(matches)})" if present else "not detected"
    return PeripheralCheck(name=name, present=present, detail=detail)


def check_peripherals(dev_root: Path, sys_root: Path) -> list[PeripheralCheck]:
    return [
        _glob_check("Webcam", dev_root, "video*"),
        _glob_check("Bluetooth", sys_root / "class/bluetooth", "*"),
        _glob_check("Battery", sys_root / "class/power_supply", "BAT*"),
        _glob_check("Wi-Fi", sys_root / "class/net", "wl*"),
    ]


class AiSetup:
    """Runs the local-AI setup helpers, emitting structured progress events."""

    def __init__(self, callback: EventCallback | None = None) -> None:
        self.callback = callback or (lambda _event: None)
        self.ollama = os.environ.get("SPACED_WELCOME_OLLAMA", "ollama")
        self.arecord = os.environ.get("SPACED_WELCOME_ARECORD", "arecord")
        self.parecord = os.environ.get("SPACED_WELCOME_PARECORD", "parecord")
        self.lpinfo = os.environ.get("SPACED_WELCOME_LPINFO", "lpinfo")
        self.sbin_path = os.environ.get(
            "SPACED_WELCOME_SBIN_PATH", "/usr/local/sbin:/usr/sbin:/sbin"
        )
        self.sound_settings = os.environ.get(
            "SPACED_WELCOME_SOUND_SETTINGS", "mate-volume-control"
        )
        self.printer_settings = os.environ.get(
            "SPACED_WELCOME_PRINTER_SETTINGS", "system-config-printer"
        )
        self.dev_root = Path(os.environ.get("SPACED_WELCOME_DEV_ROOT", "/dev"))
        self.sys_root = Path(os.environ.get("SPACED_WELCOME_SYS_ROOT", "/sys"))

    def emit(self, event: str, **values: Any) -> None:
        payload: dict[str, Any] = {"event": event}
        payload.update({key: value for key, value in values.items() if value is not None})
        self.callback(payload)

    # -- Hardware and the local AI model -----------------------------------

    def ollama_available(self) -> bool:
        return shutil.which(self.ollama) is not None

    def install_model(self, model: str) -> bool:
        if not self.ollama_available():
            message = (
                "Ollama is not installed. Install it first, then run this step again:\n"
                f"{OLLAMA_INSTALL_COMMAND}"
            )
            self.emit("task-failure", message=message)
            return False
        self.emit("task-start", message=f"Downloading {model} with Ollama…")
        try:
            with subprocess.Popen(
                [self.ollama, "pull", model],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            ) as process:
                assert process.stdout is not None
                last_line = ""
                for raw_line in process.stdout:
                    line = clean_progress_line(raw_line)
                    if line and line != last_line:
                        self.emit("detail", message=line)
                        last_line = line
                returncode = process.wait()
        except OSError as error:
            self.emit("task-failure", message=f"Could not start Ollama: {error}")
            return False
        if returncode != 0:
            self.emit("task-failure", message=f"Could not download {model}")
            return False
        self.emit("task-success", message=f"{model} is ready to use")
        return True

    # -- Microphone and sound ------------------------------------------------

    def test_microphone(self, seconds: int = 3) -> MicrophoneResult:
        recorder = self._recorder()
        if recorder is None:
            message = (
                "Neither arecord nor parecord is installed; cannot test the "
                "microphone. Install alsa-utils or pulseaudio-utils, then try again."
            )
            self.emit("task-failure", message=message)
            return MicrophoneResult(ok=False, peak_level=0.0, message=message)
        self.emit("task-start", message=f"Recording {seconds}s from the default microphone…")
        recording = Path(f"/tmp/spaced-welcome-mic-test-{os.getpid()}.wav")
        failure = recorder(seconds, recording)
        if failure is not None:
            recording.unlink(missing_ok=True)
            self.emit("task-failure", message=failure)
            return MicrophoneResult(ok=False, peak_level=0.0, message=failure)
        try:
            peak_level = self._peak_level(recording)
        finally:
            recording.unlink(missing_ok=True)
        if peak_level < 0.01:
            message = (
                "No signal was detected. Check that the correct microphone is "
                "selected and unmuted in Sound Settings, then try again."
            )
            self.emit("task-failure", message=message)
            return MicrophoneResult(ok=False, peak_level=peak_level, message=message)
        message = f"Microphone is working (peak level {peak_level:.0%})"
        self.emit("task-success", message=message)
        return MicrophoneResult(ok=True, peak_level=peak_level, message=message)

    def _recorder(self) -> Callable[[int, Path], str | None] | None:
        """Pick a recording backend: ALSA first, then PulseAudio/PipeWire."""
        if shutil.which(self.arecord):
            return self._record_with_arecord
        if shutil.which(self.parecord):
            return self._record_with_parecord
        return None

    def _record_with_arecord(self, seconds: int, recording: Path) -> str | None:
        try:
            result = subprocess.run(
                [
                    self.arecord,
                    "-d",
                    str(seconds),
                    "-f",
                    "S16_LE",
                    "-r",
                    "16000",
                    "-c",
                    "1",
                    "-q",
                    str(recording),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=seconds + 15,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            return f"Could not record from the microphone: {error}"
        if result.returncode != 0 or not recording.exists():
            return f"Recording failed: {result.stdout.strip() or 'unknown error'}"
        return None

    def _record_with_parecord(self, seconds: int, recording: Path) -> str | None:
        # parecord has no duration flag, so it records until it is stopped.
        # SIGTERM (not SIGKILL) is what lets it finalize the WAV header, so the
        # recording stays readable; running the full duration is the good path.
        try:
            process = subprocess.Popen(
                [
                    self.parecord,
                    "--file-format=wav",
                    "--format=s16le",
                    "--rate=16000",
                    "--channels=1",
                    str(recording),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        except OSError as error:
            return f"Could not record from the microphone: {error}"
        try:
            output, _ = process.communicate(timeout=seconds)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.communicate(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
        else:
            # Exiting early means it never recorded for the requested time.
            return f"Recording failed: {output.strip() or 'unknown error'}"
        if not recording.exists():
            return "Recording failed: no audio was captured"
        return None

    @staticmethod
    def _peak_level(recording: Path) -> float:
        with wave.open(str(recording), "rb") as handle:
            frames = handle.readframes(handle.getnframes())
            width = handle.getsampwidth()
        if not frames or width != 2:
            return 0.0
        peak = 0
        for offset in range(0, len(frames) - 1, 2):
            sample = int.from_bytes(frames[offset : offset + 2], "little", signed=True)
            peak = max(peak, abs(sample))
        return round(peak / 32768, 4)

    def open_sound_settings(self) -> None:
        try:
            subprocess.Popen(
                [self.sound_settings],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise AiSetupError(f"Could not open Sound Settings: {error}") from error

    # -- Peripherals ----------------------------------------------------------

    def check_peripherals(self) -> list[PeripheralCheck]:
        checks = check_peripherals(self.dev_root, self.sys_root)
        for check in checks:
            self.emit("detail", message=f"{check.name}: {check.detail}")
        return checks

    # -- Printers ---------------------------------------------------------------

    def _resolve_lpinfo(self) -> str | None:
        """Find lpinfo, which Debian ships in /usr/sbin -- off a desktop user's PATH."""
        found = shutil.which(self.lpinfo)
        if found is not None:
            return found
        return shutil.which(self.lpinfo, path=self.sbin_path)

    def find_printers(self) -> list[PrinterInfo]:
        lpinfo = self._resolve_lpinfo()
        if lpinfo is None:
            message = "lpinfo is not installed; cannot search for printers"
            self.emit("task-failure", message=message)
            return []
        self.emit("task-start", message="Searching the local network for printers…")
        try:
            result = subprocess.run(
                [lpinfo, "-v"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            self.emit("task-failure", message=f"Printer search failed: {error}")
            return []
        printers: list[PrinterInfo] = []
        for line in result.stdout.splitlines():
            _device_class, _separator, uri = line.strip().partition(" ")
            uri = uri.strip()
            # With no devices found, lpinfo -v still lists the bare backend
            # names ("network socket"), which are not printers. Only a real
            # device URI carries a scheme separator.
            scheme, separator, _rest = uri.partition("://")
            if not separator or scheme not in {"dnssd", "socket", "ipp", "ipps", "lpd"}:
                continue
            printers.append(PrinterInfo(uri=uri, make_and_model=uri.split("/")[-1] or uri))
        if printers:
            self.emit("task-success", message=f"Found {len(printers)} network printer(s)")
        else:
            self.emit("detail", message="No network printers were found")
        return printers

    def open_printer_settings(self) -> None:
        try:
            subprocess.Popen(
                [self.printer_settings],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise AiSetupError(f"Could not open Printer Settings: {error}") from error


# Kept in the application so the continued-setup tutorials work offline.
TUTORIALS = (
    (
        "Pick a coordinated desktop theme",
        "Open the MATE Appearance settings and choose a theme. Spaced Linux ships "
        "matching GTK, icon, wallpaper, and Compiz presets so switching a theme "
        "restyles the whole desktop at once, not just window colors.\n\n"
        "Changes apply immediately; try a few before settling on one.",
        "https://github.com/crhy/spaced/blob/main/docs/MATE-theming.md",
    ),
    (
        "Protect your system with snapshots",
        "Spaced Linux creates a Timeshift snapshot named \"Fresh install\" after "
        "the first boot of the installed system. Open Timeshift from the System "
        "menu to review it, create new snapshots before risky changes, and "
        "restore one if an update or experiment goes wrong.",
        "https://github.com/teejee2008/timeshift",
    ),
    (
        "Tune Compiz desktop effects",
        "Compiz is the window manager and compositor. Open CompizConfig Settings "
        "Manager to adjust animations, the workspace cube, window rules, and "
        "accessibility options beyond the defaults.",
        "https://github.com/crhy/spaced/blob/main/docs/DESIGN.md",
    ),
    (
        "Keep graphics drivers current",
        "Use the Video Drivers action on the Set Up page any time to check for "
        "and install verified NVIDIA or AMD drivers, with automatic rollback if "
        "a driver install does not boot cleanly.",
        "https://github.com/crhy/spaced/blob/main/docs/NVIDIA-RECOVERY.md",
    ),
    (
        "Browse the full application catalog",
        "SpacedBazaar lists every signed Spaced GitHub application and all of "
        "Flathub. Use it any time after Welcome to add more software beyond the "
        "curated suggestions here.",
        "https://github.com/crhy/spacedbazaar",
    ),
)
