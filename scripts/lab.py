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
import matrix_lab

PROJECT = "fedora-diy-workstation"
LOCAL = ROOT / ".local"


def compose_document(settings, matrix_settings=None, directory=LOCAL):
    cloud_port, office_port = settings["cloud_port"], settings["office_port"]
    document = {
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
    if matrix_settings and matrix_settings.get("enabled"):
        document["services"].update(matrix_lab.services(matrix_settings, directory))
        document["volumes"].update({"matrix-data": {}, "matrix-tls": {}})
    return document


def initialize(settings, directory=LOCAL, matrix_settings=None, theme=None):
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
    if matrix_settings and matrix_settings.get("enabled"):
        values = matrix_lab.initialize(matrix_settings, directory, theme)
        matrix_lab.write_key_files(directory, values)
    document = directory / "compose.json"
    document.write_text(json.dumps(compose_document(settings, matrix_settings, directory), indent=2) + "\n")
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


def compose_prefix(engine, settings, matrix_settings=None, theme=None):
    document, environment = initialize(settings, matrix_settings=matrix_settings, theme=theme)
    return engine_command(engine) + ["--project-name", PROJECT, "--env-file", str(environment), "--file", str(document)]


def occ(prefix, arguments, *, capture=False, interactive=False):
    command = prefix + ["exec"]
    if not interactive:
        command += ["-T"]
    command += ["--user", "www-data", "cloud", "php", "occ", *arguments]
    return run(command, capture_output=capture, text=True)


def configure(prefix, settings, theme=None):
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
    # Existing Talk data is retained when switching to Element.
    if "spreed" in installed.get("enabled", {}):
        occ(prefix, ["app:disable", "spreed"])
    for app in ("richdocuments",):
        if app not in installed.get("enabled", {}):
            action = "app:enable" if app in installed.get("disabled", {}) else "app:install"
            occ(prefix, [action, app])
    occ(prefix, ["background:cron"])
    if theme and theme.get("enabled"):
        occ(prefix, ["theming:config", "name", theme["workspace_name"]])
        occ(prefix, ["theming:config", "primary_color", theme["brand_color"]])
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
    for action in ("init", "up", "down", "status", "logs", "configure", "credentials", "trust"):
        subparsers.add_parser(action)
    for action in ("matrix-user", "matrix-disable"):
        subparsers.add_parser(action).add_argument("username")
    occ_parser = subparsers.add_parser("occ", help="Run a Nextcloud administration command")
    occ_parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        settings = config["lab"]
        matrix = config.get("matrix", {"enabled": False})
        if args.action == "init":
            document, _ = initialize(settings, matrix_settings=matrix, theme=config.get("theme"))
            print(f"Generated {document}; local credentials are excluded from Git.")
            return
        if args.action == "credentials":
            environment = LOCAL / "lab.env"
            if not environment.exists():
                raise ValueError("Run lab.py init or lab.py up first")
            values = dict(line.split("=", 1) for line in environment.read_text().splitlines())
            print("Username: pilot-admin\nPassword: " + values["NEXTCLOUD_ADMIN_PASSWORD"])
            matrix_secrets = LOCAL / "matrix/secrets.json"
            if matrix["enabled"] and matrix_secrets.exists():
                print("Matrix username: pilot-admin\nMatrix password: " + json.loads(matrix_secrets.read_text())["admin_password"])
            return
        prefix = compose_prefix(args.engine, settings, matrix, config.get("theme"))
        if args.action == "up":
            if matrix["enabled"]:
                matrix_lab.prepare(prefix, LOCAL)
            run(prefix + ["up", "-d"])
            if matrix["enabled"]:
                # Caddy has its admin API disabled; restart to read regenerated routes.
                run(prefix + ["restart", "gateway"])
                matrix_lab.configure(prefix, LOCAL)
            configure(prefix, settings, config.get("theme"))
        elif args.action == "configure":
            if matrix["enabled"]:
                matrix_lab.configure(prefix, LOCAL)
            configure(prefix, settings, config.get("theme"))
        elif args.action == "trust":
            certificate = LOCAL / "matrix/ca.crt"
            if not matrix["enabled"] or "BEGIN CERTIFICATE" not in certificate.read_text():
                raise ValueError("Run lab.py up before trusting the local Matrix CA")
            run(["sudo", "trust", "anchor", "--store", str(certificate)])
            print("Local Matrix certificate authority trusted. Restart your browser before opening Element.")
        elif args.action in ("matrix-user", "matrix-disable"):
            if not matrix["enabled"]:
                raise ValueError("Matrix is disabled in config.toml")
            matrix_lab.user_command(prefix, LOCAL, args.username, disable=args.action == "matrix-disable")
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
        if args.action in ("up", "configure") and matrix["enabled"]:
            print(f"Element chat and calls: https://{matrix['server_name']}")
            print("Run python3 scripts/lab.py trust once on Fedora, then restart your browser.")
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Lab command stopped: {error}\n")


if __name__ == "__main__":
    main()
