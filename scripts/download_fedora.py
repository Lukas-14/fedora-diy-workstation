#!/usr/bin/env python3
"""Download a resumable Workstation ISO; verify signature, signer, size and hash."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from urllib.parse import urlparse

from common import ROOT, load_config, run


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def verify_file(path, settings):
    path = Path(path)
    if path.stat().st_size != settings["size_bytes"]:
        raise ValueError(f"Incomplete image: {path}")
    if sha256(path) != settings["sha256"]:
        raise ValueError(f"Image checksum mismatch: {path}; retained for inspection")


def verify_signed_checksum(checksum, keys, image_name, settings):
    # Do not import keys into the user's personal keyring.
    with tempfile.TemporaryDirectory(prefix="fedora-signature-") as temporary:
        payload = Path(temporary) / "verified-checksums"
        result = subprocess.run([
            "gpgv", "--homedir", temporary, "--status-fd", "1", "--keyring", str(Path(keys).resolve()),
            "--output", str(payload), str(Path(checksum).resolve()),
        ], check=True, text=True, capture_output=True)
        signatures = re.findall(r"(?m)^\[GNUPG:\] VALIDSIG ([0-9A-F]+) .*$", result.stdout)
        # Fedora signs with its release primary key. A different trusted key is rejected.
        if settings["signing_fingerprint"] not in signatures:
            raise ValueError("Checksum signature is not from the configured Fedora release key")
        expected_line = f"SHA256 ({image_name}) = {settings['sha256']}"
        if expected_line not in payload.read_text().splitlines():
            raise ValueError("Signed checksum does not match the configured ISO and hash")


def fetch(url, destination, *, resume=False):
    command = ["curl", "--fail", "--location", "--proto", "=https", "--proto-redir", "=https",
               "--connect-timeout", "15", "--retry", "5", "--retry-all-errors", "--retry-delay", "5",
               "--speed-limit", "1024", "--speed-time", "60"]
    if resume:
        command += ["--continue-at", "-"]
    run(command + ["--output", str(destination), url])


def download(settings, directory, *, verify_only=False):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    image_name = Path(urlparse(settings["image_url"]).path).name
    image = directory / image_name
    checksum = directory / Path(urlparse(settings["checksum_url"]).path).name
    keys = directory / "fedora.gpg"
    if not verify_only:
        fetch(settings["checksum_url"], checksum)
        fetch(settings["keys_url"], keys)
    verify_signed_checksum(checksum, keys, image_name, settings)
    if image.exists():
        verify_file(image, settings)
        print(f"Already downloaded and verified: {image}")
        return image
    if verify_only:
        raise FileNotFoundError(image)
    partial = image.with_suffix(image.suffix + ".part")
    if partial.exists() and partial.stat().st_size > settings["size_bytes"]:
        raise ValueError("Partial image is larger than expected; move it aside before retrying")
    if not partial.exists() or partial.stat().st_size < settings["size_bytes"]:
        fetch(settings["image_url"], partial, resume=True)
    verify_file(partial, settings)
    partial.replace(image)
    print(f"Verified Fedora image: {image}")
    return image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--output", type=Path, default=ROOT / "downloads")
    parser.add_argument("--verify-only", action="store_true", help="Verify an existing ISO and signature without network access")
    args = parser.parse_args()
    for binary in ("gpgv",) if args.verify_only else ("curl", "gpgv"):
        if not shutil.which(binary):
            parser.error(f"Install {binary} before running this command")
    try:
        download(load_config(args.config)["fedora"], args.output, verify_only=args.verify_only)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Download stopped: {error}\n")


if __name__ == "__main__":
    main()
