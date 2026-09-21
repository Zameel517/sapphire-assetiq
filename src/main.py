"""
main.py
=======
Entry point. This is what PyInstaller packages into SapphireAssetIQ.exe.

Usage:
    SapphireAssetIQ.exe               scan in the background, no window at all --
                                        AD logon scripts and scheduled tasks
                                        (exit code 0 = saved)
    SapphireAssetIQ.exe --window      open the window and scan (testing, or by hand)
    python main.py --cli [--local]      progress and results in the console

The window is off by default so the EXE can be deployed through Active Directory
without anything appearing on the user's screen. --silent still does exactly what
the default does, so logon scripts written before this change keep working.

Results go to the Google Sheet only. The program writes no data files on the
machine; the single log per run lives in %LOCALAPPDATA%\\Sapphire AssetIQ\\logs.
config.json and service_account.json are read from inside the EXE, or from the
folder the program sits in, which wins -- see utils/paths.py.
"""

import argparse
import os
import sys
import traceback
from datetime import datetime

from app_info import APP_NAME, APP_VERSION
from scan_runner import ScanOptions, plan_run, run_scan
from utils.console import should_pause
from utils.logger import get_logger
from utils.paths import log_dir


def parse_args():
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--config", help="Path to config.json (default: next to the program)")
    parser.add_argument("--company", help="Override Company for this run")
    parser.add_argument("--location", help="Override Location for this run")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--window", "--gui", action="store_true",
                      help="Open the window and scan (the window is off by default)")
    mode.add_argument("--silent", action="store_true",
                      help="No window and no output -- the default; kept so older logon scripts still work")
    mode.add_argument("--cli", action="store_true",
                      help="Show progress and results in the console instead of the window")
    parser.add_argument("--no-console", action="store_true",
                        help="With --cli: hide the banner and summary table")
    pause = parser.add_mutually_exclusive_group()
    pause.add_argument("--pause", action="store_true",
                       help="With --cli: always wait for Enter before closing")
    pause.add_argument("--no-pause", action="store_true",
                       help="With --cli: never wait for Enter before closing")
    return parser.parse_args()


def _options(args) -> ScanOptions:
    return ScanOptions(config=args.config, company=args.company,
                       location=args.location)


def _logger():
    return get_logger(log_dir=log_dir())


def run_silent(args) -> int:
    options = _options(args)
    result = run_scan(options, _logger())
    return 0 if result.saved else 1


def run_cli(args) -> int:
    _attach_parent_console()
    from output.local_export import print_console_summary
    options = _options(args)
    plan = plan_run(options)
    if not args.no_console:
        _print_banner(plan)
    result = run_scan(options, _logger())
    if not args.no_console:
        print_console_summary(result.record)
        sys.stdout.flush()
    return 0 if result.saved else 1


def run_window(args) -> int:
    from gui.app import launch
    code = launch(_options(args))
    return run_silent(args) if code is None else code      # no desktop: scan silently


def _print_banner(plan):
    print("=" * 60)
    print(f" {APP_NAME.upper()}   v{APP_VERSION}")
    print("=" * 60)
    print(f" Computer : {os.environ.get('COMPUTERNAME', 'unknown')}")
    print(f" Saves to : the central Google Sheet (nothing is written on this PC)")
    print(f" Config   : {plan.config_path}  ({plan.config_source})")
    print(f" Log      : {log_dir()}")
    print(f" Started  : {datetime.now():%Y-%m-%d %H:%M:%S}")
    print("-" * 60, flush=True)   # before any log line, even when output is captured


def _attach_parent_console():
    """The EXE is a windowed program with no console of its own. With --cli from a
    terminal, borrow that terminal's console for the output."""
    if sys.stdout is not None or os.name != "nt":
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):          # ATTACH_PARENT_PROCESS
            sys.stdout = sys.stderr = open("CONOUT$", "w", encoding="utf-8", buffering=1)
    except Exception:
        pass


def _report_fatal(exc: Exception):
    """A windowed EXE has nowhere to print, so a crash is also written to a log file."""
    message = f"FATAL ERROR: {exc.__class__.__name__}: {exc}"
    if sys.stderr is not None:
        print(message, file=sys.stderr)
    try:
        with open(os.path.join(log_dir(), "fatal_errors.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}\n{traceback.format_exc()}\n")
    except OSError:
        pass


if __name__ == "__main__":
    args = parse_args()
    try:
        if args.cli:
            exit_code = run_cli(args)
        elif args.window:
            exit_code = run_window(args)
        else:
            exit_code = run_silent(args)          # default: background, nothing on screen
    except Exception as exc:
        _report_fatal(exc)
        exit_code = 1
    if args.cli and should_pause(force=args.pause, never=args.no_pause):
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    sys.exit(exit_code)
