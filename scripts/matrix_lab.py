"""Local Element/MatrixRTC configuration; generated secrets never enter Git."""
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

from common import run


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    Path(path).chmod(0o600)


def initialize(settings, directory, theme=None):
    directory = Path(directory) / "matrix"
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(0o700)
    state = directory / "secrets.json"
    if state.exists():
        values = json.loads(state.read_text())
        if values["server_name"] != settings["server_name"]:
            raise ValueError("Matrix server_name cannot change for an existing lab; retain its original identity")
    else:
        values = {key: secrets.token_urlsafe(32) for key in (
            "registration", "macaroon", "form", "livekit_key", "livekit_secret", "as_token", "hs_token", "admin_password")}
        values["server_name"] = settings["server_name"]
        private_json(state, values)
    base = f"https://{settings['server_name']}"
    registration = {
        "id": "local-matrixrtc", "as_token": values["as_token"], "hs_token": values["hs_token"],
        "sender_localpart": "_matrixrtc", "url": None,
        "namespaces": {"users": [{"exclusive": False, "regex": ".*"}], "aliases": [], "rooms": []},
        "io.element.msc4502.scopes": ["urn:matrix:client:io.element.msc4502:rooms:is_joined"],
        "io.element.msc4512.proxy_prefix": "rtc/livekit",
        "io.element.msc4512.proxy_url": "http://gateway:8080",
    }
    homeserver = {
        "server_name": settings["server_name"], "public_baseurl": base + "/", "pid_file": "/data/synapse.pid",
        "listeners": [{"port": 8008, "tls": False, "type": "http", "x_forwarded": True,
                       "resources": [{"names": ["client", "openid"], "compress": False}]}],
        "database": {"name": "sqlite3", "args": {"database": "/data/homeserver.db"}},
        "media_store_path": "/data/media_store", "signing_key_path": "/data/signing.key",
        "log_config": "/config/log.yaml", "report_stats": False,
        "enable_registration": False, "registration_shared_secret": values["registration"],
        "macaroon_secret_key": values["macaroon"], "form_secret": values["form"],
        "trusted_key_servers": [], "federation_domain_whitelist": [],
        "app_service_config_files": ["/config/rtc-registration.yaml"],
        "experimental_features": {"msc3266_enabled": True, "msc4143_enabled": True, "msc4222_enabled": True,
                                  "msc4502_enabled": True, "msc4512_enabled": True},
        "max_event_delay_duration": "24h", "rc_message": {"per_second": 0.5, "burst_count": 30},
        "rc_delayed_event_mgmt": {"per_second": 1, "burst_count": 20},
        "matrix_rtc": {"transports": [{"type": "livekit", "livekit_service_url": base + "/livekit/jwt"}]},
    }
    well_known = {"m.homeserver": {"base_url": base},
                  "org.matrix.msc4143.rtc_foci": [{"type": "livekit", "livekit_service_url": base + "/livekit/jwt"}]}
    element = {
        "default_server_config": well_known, "disable_custom_urls": True, "disable_guests": True,
        "enable_client_well_known_lookups": True, "default_federate": False,
        "brand": "Element", "default_theme": "light", "integrations_ui_url": "", "integrations_rest_url": "",
        "element_call": {"use_exclusively": True, "disable": False},
    }
    if theme and theme.get("enabled"):
        element["setting_defaults"] = {"custom_themes": [{
            "name": "Egmont Quiet", "is_dark": False,
            "colors": {"accent-color": theme["brand_color"], "primary-color": theme["brand_color"],
                       "warning-color": "#b55100", "sidebar-color": "#ffffff", "roomlist-background-color": "#ffffff",
                       "roomlist-text-color": "#1c304a", "roomlist-text-secondary-color": "#5d574c",
                       "roomlist-highlights-color": "#eef3fc", "roomlist-separator-color": "#e4eaf3",
                       "timeline-background-color": "#ffffff", "timeline-text-color": "#1c304a",
                       "timeline-text-secondary-color": "#5d574c", "timeline-highlights-color": "#eef3fc"},
        }]}
        element["default_theme"] = "custom-Egmont Quiet"
    livekit = {
        "port": 7880, "bind_addresses": ["0.0.0.0"],
        "rtc": {"tcp_port": settings["media_tcp_port"], "udp_port": settings["media_udp_port"],
                "node_ip": "127.0.0.1", "use_external_ip": False, "enable_loopback_candidate": True,
                "stun_servers": []},
        "keys": {values["livekit_key"]: values["livekit_secret"]}, "room": {"auto_create": False},
        "logging": {"level": "info"},
    }
    logging = {"version": 1, "handlers": {"console": {"class": "logging.StreamHandler"}},
               "root": {"level": "INFO", "handlers": ["console"]}, "disable_existing_loggers": False}
    for name, content in (("homeserver.yaml", homeserver), ("rtc-registration.yaml", registration),
                          ("element.json", element), ("livekit.yaml", livekit), ("log.yaml", logging)):
        path = directory / name
        path.write_text(json.dumps(content, indent=2) + "\n")
        # Readable by the container UIDs; the containing host directory is owner-only.
        path.chmod(0o644)
    caddy = """{
    admin off
    auto_https disable_redirects
}
https://SERVER {
    tls internal
    handle /healthz {
        respond "ok" 200
    }
    handle /.well-known/matrix/client {
        header Content-Type application/json
        header Access-Control-Allow-Origin *
        respond `WELLKNOWN` 200
    }
    handle /_matrix/* {
        reverse_proxy matrix:8008
    }
    handle /_synapse/* {
        reverse_proxy matrix:8008
    }
    handle_path /livekit/jwt/* {
        reverse_proxy 127.0.0.1:8080
    }
    handle_path /livekit/sfu/* {
        reverse_proxy livekit:7880
    }
    handle {
        reverse_proxy element:8080
    }
}
""".replace("SERVER", settings["server_name"]).replace("WELLKNOWN", json.dumps(well_known))
    (directory / "Caddyfile").write_text(caddy)
    (directory / "Caddyfile").chmod(0o644)
    if not (directory / "ca.crt").exists():
        (directory / "ca.crt").touch(mode=0o644)
    return values


def services(settings, directory):
    directory = (Path(directory) / "matrix").resolve()
    def bind(name, destination):
        return f"{directory / name}:{destination}:ro,z"
    return {
        "matrix": {
            "image": settings["synapse_image"], "user": "991:991",
            "environment": {"SYNAPSE_CONFIG_PATH": "/config/homeserver.yaml"},
            "volumes": ["matrix-data:/data", bind("homeserver.yaml", "/config/homeserver.yaml"),
                        bind("rtc-registration.yaml", "/config/rtc-registration.yaml"), bind("log.yaml", "/config/log.yaml")],
        },
        "element": {"image": settings["element_image"], "environment": {"ELEMENT_WEB_PORT": "8080"},
                    "volumes": [bind("element.json", "/app/config.json")]},
        "livekit": {
            "image": settings["livekit_image"], "command": ["--config", "/etc/livekit.yaml"],
            "volumes": [bind("livekit.yaml", "/etc/livekit.yaml")],
            "ports": [f"127.0.0.1:{settings['media_tcp_port']}:{settings['media_tcp_port']}/tcp",
                      f"127.0.0.1:{settings['media_udp_port']}:{settings['media_udp_port']}/udp"],
        },
        "gateway": {
            "image": settings["gateway_image"],
            "ports": [f"127.0.0.1:{settings['https_port']}:{settings['https_port']}"],
            "volumes": ["matrix-tls:/data", bind("Caddyfile", "/etc/caddy/Caddyfile")],
        },
        "matrixrtc": {
            "image": settings["jwt_image"], "network_mode": "service:gateway",
            "environment": {
                "LIVEKIT_URL": f"wss://{settings['server_name']}/livekit/sfu",
                "LIVEKIT_KEY_FROM_FILE": "/config/livekit-key", "LIVEKIT_SECRET_FROM_FILE": "/config/livekit-secret",
                "LIVEKIT_FULL_ACCESS_HOMESERVERS": settings["server_name"],
                "LIVEKIT_HS_SERVER_NAME": settings["server_name"],
                "LIVEKIT_AS_REGISTRATION_FILE": "/config/rtc-registration.yaml",
                "LIVEKIT_CS_API_URL_OVERRIDES": f"{settings['server_name']}=http://matrix:8008",
                "LIVEKIT_REMOTE_CAN_PUBLISH_HOMESERVERS": "", "SSL_CERT_FILE": "/config/ca.crt",
            },
            "volumes": [bind("livekit-key", "/config/livekit-key"), bind("livekit-secret", "/config/livekit-secret"),
                        bind("rtc-registration.yaml", "/config/rtc-registration.yaml"), bind("ca.crt", "/config/ca.crt")],
            "depends_on": ["gateway", "matrix", "livekit"],
        },
    }


def write_key_files(directory, values):
    directory = Path(directory) / "matrix"
    for name, key in (("livekit-key", "livekit_key"), ("livekit-secret", "livekit_secret")):
        path = directory / name
        path.write_text(values[key] + "\n")
        path.chmod(0o644)


def prepare(prefix, directory):
    # Named data volume ownership is prepared inside a rootless container.
    run(prefix + ["run", "--rm", "--no-deps", "--user", "0:0", "--entrypoint", "python", "matrix", "-c",
                  "import os; os.makedirs('/data',exist_ok=True); os.chown('/data',991,991)"])
    run(prefix + ["run", "--rm", "--no-deps", "--entrypoint", "python", "matrix", "-m", "synapse.app.homeserver",
                  "--generate-keys", "--config-path=/config/homeserver.yaml"])
    # Bootstrap the local CA before starting clients that need its certificate.
    run(prefix + ["up", "-d", "gateway"])
    for _ in range(60):
        result = subprocess.run(prefix + ["exec", "-T", "gateway", "cat", "/data/caddy/pki/authorities/local/root.crt"],
                                text=True, capture_output=True)
        if result.returncode == 0 and "BEGIN CERTIFICATE" in result.stdout:
            (Path(directory) / "matrix/ca.crt").write_text(result.stdout)
            return
        time.sleep(2)
    raise ValueError("Local Matrix TLS certificate did not become ready; inspect gateway logs")


# Executed inside Synapse; credentials arrive through stdin, never process arguments.
ADMIN_SCRIPT = r'''
import hashlib, hmac, json, urllib.request, urllib.error, urllib.parse
data = json.load(__import__('sys').stdin)
def request(path, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token: headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request('http://127.0.0.1:8008' + path,
                                 data=None if body is None else json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=15) as response: return json.load(response)
if data['action'] == 'bootstrap':
    nonce = request('/_synapse/admin/v1/register')['nonce']
    user, password = 'pilot-admin', data['password']
    mac = hmac.new(data['secret'].encode(), digestmod=hashlib.sha1)
    mac.update(('\0'.join([nonce, user, password, 'admin'])).encode())
    try:
        request('/_synapse/admin/v1/register', dict(nonce=nonce, username=user, password=password, admin=True, mac=mac.hexdigest()))
        print('Matrix administrator created.')
    except urllib.error.HTTPError as error:
        detail = json.load(error)
        if detail.get('errcode') != 'M_USER_IN_USE': raise
        print('Existing Matrix administrator retained.')
else:
    login = request('/_matrix/client/v3/login', {'type':'m.login.password', 'identifier':{'type':'m.id.user','user':'pilot-admin'}, 'password':data['password']})
    token = login['access_token']
    try:
        user = urllib.parse.quote('@' + data['user'] + ':' + data['server_name'], safe='')
        request('/_synapse/admin/v1/deactivate/' + user, {'erase':False}, token)
        print('Matrix account deactivated; content retained.')
    finally:
        request('/_matrix/client/v3/logout', {}, token)
'''


def configure(prefix, directory):
    for _ in range(90):
        result = subprocess.run(prefix + ["exec", "-T", "matrix", "python", "-c",
                                          "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8008/health', timeout=3)"],
                                capture_output=True)
        if result.returncode == 0:
            break
        time.sleep(2)
    else:
        raise ValueError("Synapse did not become ready; inspect matrix service logs")
    values = json.loads((Path(directory) / "matrix/secrets.json").read_text())
    subprocess.run(prefix + ["exec", "-T", "matrix", "python", "-c", ADMIN_SCRIPT], check=True,
                   input=json.dumps({"action": "bootstrap", "password": values["admin_password"], "secret": values["registration"]}), text=True)


def user_command(prefix, directory, username, *, disable=False):
    if not re.fullmatch(r"[a-z0-9][a-z0-9._=-]{0,63}", username) or username == "pilot-admin":
        raise ValueError("Use a lowercase test username other than pilot-admin")
    if disable:
        values = json.loads((Path(directory) / "matrix/secrets.json").read_text())
        subprocess.run(prefix + ["exec", "-T", "matrix", "python", "-c", ADMIN_SCRIPT], check=True, text=True,
                       input=json.dumps({"action": "disable", "user": username, "server_name": values["server_name"], "password": values["admin_password"]}))
    else:
        command = prefix + ["exec"] + ([] if sys.stdin.isatty() else ["-T"])
        run(command + ["matrix", "register_new_matrix_user", "-c", "/config/homeserver.yaml", "-u", username,
                       "--no-admin", "http://127.0.0.1:8008"])
