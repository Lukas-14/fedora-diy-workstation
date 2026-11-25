#!/usr/bin/env python3
"""Run a DIY collaboration lab on the test computer, using rootless Podman or Docker."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time

from common import ROOT, load_config, run

PROJECT = "fedora-diy-workstation"
LOCAL = ROOT / ".local"


def compose_document(settings):
    cloud_port, office_port = settings["cloud_port"], settings["office_port"]
    return {
        "services": {
            "db": {
                "image": settings["postgres_image"],
                "environment": {"POSTGRES_DB": "nextcloud", "POSTGRES_USER": "nextcloud",
                                "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:?Run lab.py init first}"},
                "volumes": ["database:/var/lib/postgresql/data"],
                "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U nextcloud -d nextcloud"],
                                "interval": "5s", "timeout": "5s", "retries": 30},
            },
            "cache": {"image": settings["valkey_image"]},
            "cloud": {
                "image": settings["nextcloud_image"],
                "ports": [f"127.0.0.1:{cloud_port}:80"],
                "environment": {
                    "POSTGRES_HOST": "db", "POSTGRES_DB": "nextcloud", "POSTGRES_USER": "nextcloud",
                    "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD:?Run lab.py init first}",
                    "REDIS_HOST": "cache", "NEXTCLOUD_ADMIN_USER": "pilot-admin",
                    "NEXTCLOUD_ADMIN_PASSWORD": "${NEXTCLOUD_ADMIN_PASSWORD:?Run lab.py init first}",
                    "NEXTCLOUD_TRUSTED_DOMAINS": "localhost 127.0.0.1 cloud",
                    "OVERWRITECLIURL": f"http://localhost:{cloud_port}",
                },
                "volumes": ["nextcloud:/var/www/html"],
                "depends_on": {"db": {"condition": "service_healthy"},
                               "cache": {"condition": "service_started"}},
            },
            "cron": {
                "image": settings["nextcloud_image"],
                "entrypoint": "/cron.sh", "volumes": ["nextcloud:/var/www/html"],
                "depends_on": ["cloud"],
            },
            "office": {
                "image": settings["collabora_image"],
                "ports": [f"127.0.0.1:{office_port}:9980"],
                "environment": {
                    "aliasgroup1": "http://cloud:80",
                    "server_name": f"localhost:{office_port}",
                    "extra_params": "--o:ssl.enable=false --o:ssl.termination=false "
                                    f"--o:net.frame_ancestors=http://localhost:{cloud_port}",
                },
                "cap_add": ["MKNOD"], "shm_size": "512m",
            },
        },
        "volumes": {"database": {}, "nextcloud": {}},
    }


def initialize(settings, directory=LOCAL):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    environment = directory / "lab.env"
    # Create once; reruns must not reset credentials for an existing database.
    try:
        fd = os.open(environment, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if environment.is_symlink():
            raise ValueError("Refusing a symlink for the local credentials file")
        environment.chmod(0o600)
    else:
        with os.fdopen(fd, "w") as stream:
            stream.write(f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}\n")
            stream.write(f"NEXTCLOUD_ADMIN_PASSWORD={secrets.token_urlsafe(32)}\n")
    document = directory / "compose.json"
    document.write_text(json.dumps(compose_document(settings), indent=2) + "\n")
    document.chmod(0o600)
    return document, environment


def engine_command(engine):
    if engine == "auto":
        engine = "podman" if shutil.which("podman") else "docker"
    if not shutil.which(engine):
        raise ValueError("Install Podman and podman-compose with setup_fedora.py first")
    if engine == "podman":
        if not shutil.which("podman-compose"):
            raise ValueError("Install podman-compose first")
        return ["podman-compose"]
    return ["docker", "compose"]


def compose_prefix(engine, settings):
    document, environment = initialize(settings)
    return engine_command(engine) + ["--project-name", PROJECT, "--env-file", str(environment), "--file", str(document)]


def occ(prefix, arguments, *, capture=False, interactive=False):
    command = prefix + ["exec"]
    if not interactive:
        command += ["-T"]
    command += ["--user", "www-data", "cloud", "php", "occ", *arguments]
    return run(command, capture_output=capture, text=True)


def configure(prefix, settings):
    print("Waiting for Nextcloud's initial installation (up to six minutes)...", flush=True)
    for _ in range(120):
        result = subprocess.run(prefix + ["exec", "-T", "--user", "www-data", "cloud", "php", "occ",
                                          "status", "--output=json"], capture_output=True, text=True)
        try:
            ready = result.returncode == 0 and json.loads(result.stdout).get("installed") is True
        except (ValueError, AttributeError):
            ready = False
        if ready:
            break
        time.sleep(3)
    else:
        raise ValueError("Nextcloud did not become ready. Inspect: python3 scripts/lab.py logs")
    installed = json.loads(occ(prefix, ["app:list", "--output=json"], capture=True).stdout)
    for app in ("richdocuments", "spreed"):
        if app not in installed.get("enabled", {}):
            action = "app:enable" if app in installed.get("disabled", {}) else "app:install"
            occ(prefix, [action, app])
    occ(prefix, ["background:cron"])
    occ(prefix, ["config:system:set", "allow_local_remote_servers", "--type=boolean", "--value=true"])
    values = {
        "wopi_url": "http://office:9980",
        "public_wopi_url": f"http://localhost:{settings['office_port']}",
        "wopi_callback_url": "http://cloud",
    }
    for name, value in values.items():
        occ(prefix, ["config:app:set", "richdocuments", name, "--value=" + value])
    # Limit WOPI calls to this lab's document-server address.
    address_result = run(prefix + ["exec", "-T", "cloud", "php", "-r", 'echo gethostbyname("office");'],
                         capture_output=True, text=True)
    address = ipaddress.ip_address(address_result.stdout.strip())
    occ(prefix, ["config:app:set", "richdocuments", "wopi_allowlist", "--value=" + str(address)])
    # Wait for CODE too; no browser should be sent to a half-started editor.
    for _ in range(60):
        result = subprocess.run(prefix + ["exec", "-T", "cloud", "curl", "--fail", "--silent",
                                          "--max-time", "3", "http://office:9980/hosting/discovery"],
                                capture_output=True, text=True)
        if result.returncode == 0 and "wopi-discovery" in result.stdout:
            break
        time.sleep(2)
    else:
        raise ValueError("Collabora did not become ready. Inspect the office service logs.")
    occ(prefix, ["richdocuments:activate-config"])
    # activate-config may derive the public URL from discovery; make it explicit.
    occ(prefix, ["config:app:set", "richdocuments", "public_wopi_url",
                 "--value=" + values["public_wopi_url"]])
    print(f"Local collaboration lab: http://localhost:{settings['cloud_port']}")
    print("Admin user: pilot-admin; show the generated password with: python3 scripts/lab.py credentials")
    print("Use two browser profiles for the first co-editing test. No LAN ports were opened.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.toml")
    parser.add_argument("--engine", choices=("auto", "podman", "docker"), default="auto")
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("init", "up", "down", "status", "logs", "configure", "credentials"):
        subparsers.add_parser(action)
    occ_parser = subparsers.add_parser("occ", help="Run a Nextcloud administration command")
    occ_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        settings = load_config(args.config)["lab"]
        if args.action == "init":
            document, _ = initialize(settings)
            print(f"Generated {document}; local credentials are excluded from Git.")
            return
        if args.action == "credentials":
            environment = LOCAL / "lab.env"
            if not environment.exists():
                raise ValueError("Run lab.py init or lab.py up first")
            values = dict(line.split("=", 1) for line in environment.read_text().splitlines())
            print("Username: pilot-admin\nPassword: " + values["NEXTCLOUD_ADMIN_PASSWORD"])
            return
        prefix = compose_prefix(args.engine, settings)
        if args.action == "up":
            run(prefix + ["up", "-d"])
            configure(prefix, settings)
        elif args.action == "configure":
            configure(prefix, settings)
        elif args.action == "down":
            # Volumes are intentionally retained.
            run(prefix + ["down"])
        elif args.action == "status":
            run(prefix + ["ps"])
        elif args.action == "logs":
            run(prefix + ["logs", "--tail", "80"])
        elif args.action == "occ":
            if not args.arguments:
                parser.error("Provide an occ command, such as user:add alice")
            occ(prefix, args.arguments, interactive=sys.stdin.isatty())
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Lab command stopped: {error}\n")


if __name__ == "__main__":
    main()
