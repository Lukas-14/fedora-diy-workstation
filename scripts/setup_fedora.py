#!/usr/bin/env python3
"""Apply the public workstation configuration after installing Fedora Workstation."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess

from common import ROOT, load_config, run


def commands(config):
    yield ["sudo", "dnf", "install", "-y", *config["workstation"]["packages"]]
    if config["workstation"]["start_syncthing"]:
        yield ["systemctl", "--user", "enable", "--now", "syncthing.service"]
    yield ["gsettings", "set", "org.gnome.desktop.peripherals.touchpad", "natural-scroll",
           str(config["desktop"]["natural_scroll"]).lower()]
    yield ["gsettings", "set", "org.gnome.desktop.wm.preferences", "button-layout",
           config["desktop"]["button_layout"]]
    if config["peer"]["install_jami"]:
        yield ["sudo", "dnf", "install", "-y", "flatpak"]
        yield ["flatpak", "remote-add", "--user", "--if-not-exists", "flathub", "https://flathub.org/repo/flathub.flatpakrepo"]
        yield ["flatpak", "install", "--user", "--noninteractive", "flathub", "net.jami.Jami"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without changing the computer")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        if not args.dry_run:
            if os.geteuid() == 0:
                parser.error("Run as your desktop user, without sudo; only package installation uses sudo")
            os_release = Path("/etc/os-release").read_text().splitlines()
            if 'ID=fedora' not in os_release and 'ID="fedora"' not in os_release:
                parser.error("This setup targets Fedora Workstation; use --dry-run to inspect it elsewhere")
            if Path("/run/ostree-booted").exists():
                parser.error("This script targets DNF-based Workstation, not Silverblue/Atomic")
            if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
                parser.error("Run from a terminal inside your GNOME desktop session")
            if not shutil.which("gsettings"):
                parser.error("GNOME gsettings is required")
        for command in commands(config):
            run(command, dry_run=args.dry_run)
        print("Setup complete." if not args.dry_run else "Dry run complete; nothing changed.")
        print("Syncthing UI: http://127.0.0.1:8384 (pair devices manually).")
        print("Optional local co-editing lab: python3 scripts/lab.py up")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Setup stopped: {error}\n")


if __name__ == "__main__":
    main()
