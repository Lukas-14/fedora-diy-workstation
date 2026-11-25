"""Shared, standard-library-only configuration and process helpers."""
from pathlib import Path
import re
import shlex
import subprocess
import tomllib
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def load_config(path=None):
    with Path(path or ROOT / "config.toml").open("rb") as stream:
        config = tomllib.load(stream)
    fedora = config["fedora"]
    for key in ("image_url", "checksum_url", "keys_url"):
        url = urlparse(fedora[key])
        if (url.scheme != "https" or not url.hostname
                or not (url.hostname == "fedoraproject.org" or url.hostname.endswith(".fedoraproject.org"))
                or url.username or url.password or url.query or url.fragment):
            raise ValueError(f"{key} must be an HTTPS URL on fedoraproject.org")
    if not re.fullmatch(r"[0-9a-f]{64}", fedora["sha256"]):
        raise ValueError("Invalid Fedora SHA256")
    if not re.fullmatch(r"[0-9A-F]{40}", fedora["signing_fingerprint"]):
        raise ValueError("Invalid Fedora signing fingerprint")
    if type(fedora["size_bytes"]) is not int or fedora["size_bytes"] <= 0:
        raise ValueError("Invalid Fedora image size")
    filename = Path(urlparse(fedora["image_url"]).path).name
    if not re.fullmatch(r"Fedora-Workstation-Live-[A-Za-z0-9._-]+\.iso", filename):
        raise ValueError("Unexpected Workstation image filename")
    release, architecture = fedora["release"], fedora["architecture"]
    if not isinstance(release, str) or not release.isdigit() or architecture not in ("x86_64", "aarch64"):
        raise ValueError("Use a stable numeric Fedora release and x86_64 or aarch64")
    expected_path = f"/releases/{release}/Workstation/{architecture}/iso/"
    if any(expected_path not in urlparse(fedora[key]).path for key in ("image_url", "checksum_url")):
        raise ValueError("Fedora URLs must match the configured release and architecture")
    if not filename.startswith(f"Fedora-Workstation-Live-{release}-") or not filename.endswith(f".{architecture}.iso"):
        raise ValueError("Fedora image filename must match the configured release and architecture")
    for package in config["workstation"]["packages"]:
        if not isinstance(package, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9+_.-]*", package):
            raise ValueError(f"Invalid package name: {package!r}")
    for section, key in (("workstation", "start_syncthing"), ("desktop", "natural_scroll"), ("peer", "install_element")):
        if type(config[section][key]) is not bool:
            raise ValueError(f"{section}.{key} must be true or false")
    layout = config["desktop"]["button_layout"]
    if not isinstance(layout, str) or not re.fullmatch(r"[a-z,:]*", layout):
        raise ValueError("Invalid GNOME button layout")
    theme = config.get("theme", {"enabled": False})
    if type(theme["enabled"]) is not bool:
        raise ValueError("theme.enabled must be true or false")
    if theme["enabled"]:
        if theme["accent_color"] not in ("blue", "teal", "green", "yellow", "orange", "red", "pink", "purple", "slate"):
            raise ValueError("Use one of GNOME's built-in accent colors")
        if theme["color_scheme"] not in ("default", "prefer-light", "prefer-dark"):
            raise ValueError("Invalid GNOME color scheme")
        for key in ("interface_font", "document_font", "titlebar_font"):
            if not isinstance(theme[key], str) or not re.fullmatch(r"[\w .,()-]{1,95} [0-9]{1,2}", theme[key]):
                raise ValueError(f"Invalid font description: {key}")
        if not isinstance(theme["brand_color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", theme["brand_color"]):
            raise ValueError("Invalid theme brand color")
        if not isinstance(theme["workspace_name"], str) or not 1 <= len(theme["workspace_name"]) <= 80:
            raise ValueError("Invalid workspace name")
    lab = config["lab"]
    for key in ("cloud_port", "office_port"):
        if type(lab[key]) is not int or not 1024 <= lab[key] <= 65535:
            raise ValueError(f"{key} must be an unprivileged TCP port")
    if lab["cloud_port"] == lab["office_port"]:
        raise ValueError("Cloud and office ports must differ")
    for key in ("nextcloud_image", "postgres_image", "valkey_image", "collabora_image"):
        if not isinstance(lab[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]*", lab[key]):
            raise ValueError(f"Invalid container image: {key}")
    matrix = config.get("matrix", {"enabled": False})
    if type(matrix["enabled"]) is not bool:
        raise ValueError("matrix.enabled must be true or false")
    if matrix["enabled"]:
        ports = [lab["cloud_port"], lab["office_port"]]
        for key in ("https_port", "media_tcp_port", "media_udp_port"):
            if type(matrix[key]) is not int or not 1024 <= matrix[key] <= 65535:
                raise ValueError(f"Invalid Matrix port: {key}")
            ports.append(matrix[key])
        if len(set(ports)) != len(ports):
            raise ValueError("Lab and Matrix ports must not overlap")
        if matrix["server_name"] != f"localhost:{matrix['https_port']}":
            raise ValueError("This local Matrix lab requires server_name localhost:<https_port>")
        for key in ("synapse_image", "element_image", "livekit_image", "jwt_image", "gateway_image"):
            if not isinstance(matrix[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@:-]*", matrix[key]):
                raise ValueError(f"Invalid Matrix image: {key}")
    return config


def run(command, *, dry_run=False, **kwargs):
    print("+ " + shlex.join([str(part) for part in command]), flush=True)
    if dry_run:
        return None
    return subprocess.run(command, check=True, **kwargs)
