# SPDX-License-Identifier: GPL-3.0-or-later
"""Command-line interface for the AI Setup page: hardware, microphone, printers."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from dataclasses import asdict
from typing import Any

from .ai_setup import AiSetup, AiSetupError, check_peripherals, detect_hardware, recommend_model


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="spaced-welcome-ai-setup",
        description="Detect hardware, install a local AI model, and test peripherals.",
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--detect-hardware", action="store_true", help="print RAM and GPU details")
    actions.add_argument(
        "--recommend-model", action="store_true", help="print the recommended local Ollama model"
    )
    actions.add_argument("--install-model", metavar="MODEL", help="download a model with Ollama")
    actions.add_argument(
        "--test-microphone", action="store_true", help="record briefly and report the signal level"
    )
    actions.add_argument(
        "--open-sound-settings", action="store_true", help="open the system Sound Settings"
    )
    actions.add_argument(
        "--check-peripherals", action="store_true", help="check for common peripherals"
    )
    actions.add_argument(
        "--find-printers", action="store_true", help="search for printers on the local network"
    )
    actions.add_argument(
        "--open-printer-settings", action="store_true", help="open the system Printer Settings"
    )
    parser.add_argument("--json", action="store_true", help="print result output as JSON")
    parser.add_argument(
        "--events",
        action="store_true",
        help="emit newline-delimited JSON progress while running",
    )
    parser.add_argument(
        "--seconds", type=int, default=3, help="microphone recording duration (default: 3)"
    )
    return parser


def _event_writer(events: bool):
    if events:
        def emit(payload: dict[str, Any]) -> None:
            print(json.dumps(payload, sort_keys=True), flush=True)
        return emit

    def emit(payload: dict[str, Any]) -> None:
        message = payload.get("message")
        if message:
            print(message, flush=True)
    return emit


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    # --json output must be the only thing on stdout; suppress plain-text
    # progress messages when it is requested without --events.
    callback = (lambda _event: None) if args.json and not args.events else _event_writer(args.events)
    setup = AiSetup(callback=callback)
    try:
        if args.detect_hardware:
            profile = detect_hardware()
            if args.json:
                print(json.dumps(asdict(profile), sort_keys=True))
            else:
                gpu = f"{profile.gpu_name} ({profile.gpu_vram_gb}GB VRAM)" if profile.gpu_name else "none"
                print(f"RAM: {profile.ram_gb}GB, GPU: {gpu}")
            return 0

        if args.recommend_model:
            profile = detect_hardware()
            recommendation = recommend_model(profile)
            if args.json:
                print(
                    json.dumps(
                        {
                            "model": recommendation.model,
                            "reason": recommendation.reason,
                            "ram_gb": profile.ram_gb,
                            "gpu_name": profile.gpu_name,
                            "gpu_vram_gb": profile.gpu_vram_gb,
                        },
                        sort_keys=True,
                    )
                )
            else:
                print(f"{recommendation.model}: {recommendation.reason}")
            return 0

        if args.install_model:
            return 0 if setup.install_model(args.install_model) else 1

        if args.test_microphone:
            result = setup.test_microphone(seconds=args.seconds)
            if args.json:
                print(json.dumps(asdict(result), sort_keys=True))
            return 0 if result.ok else 1

        if args.open_sound_settings:
            setup.open_sound_settings()
            return 0

        if args.check_peripherals:
            checks = check_peripherals(
                Path(os.environ.get("SPACED_WELCOME_DEV_ROOT", "/dev")),
                Path(os.environ.get("SPACED_WELCOME_SYS_ROOT", "/sys")),
            )
            if args.json:
                print(json.dumps([asdict(check) for check in checks], sort_keys=True))
            else:
                for check in checks:
                    print(f"{check.name}: {check.detail}")
            return 0

        if args.find_printers:
            printers = setup.find_printers()
            if args.json:
                print(json.dumps([asdict(printer) for printer in printers], sort_keys=True))
            return 0

        if args.open_printer_settings:
            setup.open_printer_settings()
            return 0

        return 2
    except (AiSetupError, OSError, ValueError) as error:
        if args.events:
            print(json.dumps({"event": "task-failure", "message": str(error)}, sort_keys=True))
        else:
            print(f"spaced-welcome-ai-setup: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
