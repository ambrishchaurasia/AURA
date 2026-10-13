"""System-tray launcher for AURA voice control.

    pythonw -m automation.mcp.tray                run in the tray, no console window
    python -m automation.mcp.tray --startup on    start with Windows (`off` removes it)

The tray menu pauses listening or quits. Output goes to %LOCALAPPDATA%\\AURA\\voice.log.
"""
import argparse
import asyncio
import os
import pathlib
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[2]
SHORTCUT = pathlib.Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup/AURA.lnk"


def set_startup(on):
    if not on:
        SHORTCUT.unlink(missing_ok=True)
        return
    import win32com.client
    link = win32com.client.Dispatch("WScript.Shell").CreateShortcut(str(SHORTCUT))
    link.TargetPath = str(pathlib.Path(sys.executable).with_name("pythonw.exe"))
    link.Arguments = "-m automation.mcp.tray"
    link.WorkingDirectory = str(ROOT)
    link.Save()


def main():
    parser = argparse.ArgumentParser(description="AURA voice control in the system tray")
    parser.add_argument("--startup", choices=["on", "off"], help="add or remove the start-with-Windows shortcut and exit")
    args = parser.parse_args()
    if args.startup:
        set_startup(args.startup == "on")
        print(f"Start with Windows: {args.startup} ({SHORTCUT})")
        return

    log_dir = pathlib.Path(os.environ.get("AURA_DATA_DIR") or pathlib.Path(os.environ["LOCALAPPDATA"]) / "AURA")
    log_dir.mkdir(parents=True, exist_ok=True)
    sys.stdout = sys.stderr = open(log_dir / "voice.log", "a", buffering=1, encoding="utf-8")

    import pystray
    from PIL import Image, ImageDraw
    from automation.mcp import voice

    image = Image.new("RGBA", (64, 64))
    ImageDraw.Draw(image).ellipse((8, 8, 56, 56), fill="#6c5ce7")
    listening = threading.Event()
    listening.set()
    icon = pystray.Icon("AURA", image, 'AURA: say "hey aura"', pystray.Menu(
        pystray.MenuItem("Listening", lambda: listening.clear() if listening.is_set() else listening.set(),
                         checked=lambda item: listening.is_set()),
        pystray.MenuItem("Quit", lambda: icon.stop())))

    def work():
        try:
            asyncio.run(voice.serve(enabled=listening.is_set))
        except Exception as error:
            print(f"Voice loop stopped: {error!r}")
            icon.notify(f"AURA stopped: {error}")

    threading.Thread(target=work, daemon=True).start()
    icon.run()


if __name__ == "__main__":
    main()
