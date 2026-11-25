#!/usr/bin/env python3
"""Apply or restore a restrained Egmont-inspired GNOME appearance."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from common import ROOT, load_config, run

BACKUP = ROOT / ".local" / "theme-backup.json"
WALLPAPERS = Path.home() / ".local/share/backgrounds/fedora-diy-workstation"


def theme_settings(config, wallpaper_directory=WALLPAPERS):
    theme = config["theme"]
    directory = Path(wallpaper_directory).resolve()
    return [
        ("org.gnome.desktop.interface", "accent-color", theme["accent_color"]),
        ("org.gnome.desktop.interface", "color-scheme", theme["color_scheme"]),
        ("org.gnome.desktop.interface", "font-name", theme["interface_font"]),
        ("org.gnome.desktop.interface", "document-font-name", theme["document_font"]),
        ("org.gnome.desktop.wm.preferences", "titlebar-font", theme["titlebar_font"]),
        ("org.gnome.desktop.background", "picture-uri", (directory / "egmont-clock.jpeg").as_uri()),
        ("org.gnome.desktop.background", "picture-uri-dark", (directory / "egmont-clock.jpeg").as_uri()),
        ("org.gnome.desktop.background", "picture-options", "zoom"),
    ]


def save_originals(settings, backup=BACKUP):
    backup = Path(backup)
    if backup.exists():
        return
    originals = []
    for schema, key, _ in settings:
        value = subprocess.run(["gsettings", "get", schema, key], check=True,
                               text=True, capture_output=True).stdout.strip()
        originals.append({"schema": schema, "key": key, "value": value})
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.parent.chmod(0o700)
    # Keep the initial values across repeat applies, so restore remains useful.
    descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(originals, stream, indent=2)
        stream.write("\n")


def apply_theme(config, *, dry_run=False, backup=BACKUP, wallpaper_directory=WALLPAPERS):
    if not config.get("theme", {}).get("enabled", False):
        print("Appearance customization is disabled in config.toml.")
        return
    settings = theme_settings(config, wallpaper_directory)
    if not dry_run:
        save_originals(settings, backup)
    source = ROOT / "assets/egmont/clock.jpeg"
    destination = Path(wallpaper_directory) / "egmont-clock.jpeg"
    run(["install", "-D", "-m", "644", str(source), str(destination)], dry_run=dry_run)
    for schema, key, value in settings:
        run(["gsettings", "set", schema, key, value], dry_run=dry_run)


def restore_theme(*, dry_run=False, backup=BACKUP):
    backup = Path(backup)
    if not backup.exists():
        raise ValueError("No appearance backup exists; no preferences were changed")
    for original in json.loads(backup.read_text()):
        run(["gsettings", "set", original["schema"], original["key"], original["value"]], dry_run=dry_run)
    # Leave the snapshot intact: repeated restore is harmless.
    print("Original appearance restored." if not dry_run else "Restore dry run complete.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("action", choices=("apply", "restore"))
    args = parser.parse_args()
    try:
        if not args.dry_run and (os.geteuid() == 0 or not os.environ.get("DBUS_SESSION_BUS_ADDRESS")):
            parser.error("Run as your normal user in a GNOME desktop terminal, without sudo")
        if args.action == "apply":
            apply_theme(load_config(args.config), dry_run=args.dry_run)
        else:
            restore_theme(dry_run=args.dry_run)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Appearance change stopped: {error}\n")


if __name__ == "__main__":
    main()
