"""Explicit Docker integration check; uses isolated containers, volumes and ports.

Run: python3 tests/matrix_smoke.py
Downloads Matrix images if needed. Does not install a CA into the host trust store.
"""
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from common import load_config
import lab
import matrix_lab


def port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def main():
    config = load_config()
    settings = dict(config["matrix"])
    ports = set()
    while len(ports) < 3:
        ports.add(port())
    settings["https_port"], settings["media_tcp_port"], settings["media_udp_port"] = sorted(ports)
    settings["server_name"] = f"localhost:{settings['https_port']}"
    project = "fdiy-matrix-smoke-" + secrets.token_hex(4)
    (ROOT / ".local").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="matrix-smoke-", dir=ROOT / ".local") as temporary:
        directory = Path(temporary)
        document, environment = lab.initialize(config["lab"], directory, settings, config.get("theme"))
        prefix = ["docker", "compose", "--project-name", project, "--env-file", str(environment), "--file", str(document)]
        try:
            matrix_lab.prepare(prefix, directory)
            subprocess.run(prefix + ["up", "-d", "matrix", "element", "livekit", "gateway", "matrixrtc"], check=True)
            matrix_lab.configure(prefix, directory)
            context = ssl.create_default_context(cafile=str(directory / "matrix/ca.crt"))
            base = "https://" + settings["server_name"]
            def api(path, body=None, token=None, method=None):
                headers = {"Content-Type": "application/json"}
                if token:
                    headers["Authorization"] = "Bearer " + token
                request = urllib.request.Request(base + path, headers=headers, method=method,
                                                 data=None if body is None else json.dumps(body).encode())
                with urllib.request.urlopen(request, context=context, timeout=20) as response:
                    return json.load(response)
            for _ in range(30):
                try:
                    api("/_matrix/client/versions")
                    break
                except (OSError, urllib.error.URLError):
                    time.sleep(2)
            else:
                raise RuntimeError("Matrix API not reachable through local HTTPS")
            well_known = api("/.well-known/matrix/client")
            assert well_known["m.homeserver"]["base_url"] == base
            state = json.loads((directory / "matrix/secrets.json").read_text())
            users = {}
            for username in ("alice", "bob"):
                password = secrets.token_urlsafe(24)
                nonce = api("/_synapse/admin/v1/register")["nonce"]
                message = chr(0).join((nonce, username, password, "notadmin"))
                mac = hmac.new(state["registration"].encode(), message.encode(), hashlib.sha1).hexdigest()
                api("/_synapse/admin/v1/register", {"nonce": nonce, "username": username, "password": password, "admin": False, "mac": mac})
                users[username] = api("/_matrix/client/v3/login", {"type": "m.login.password", "identifier": {"type": "m.id.user", "user": username}, "password": password})
            alice, bob = users["alice"], users["bob"]
            room = api("/_matrix/client/v3/createRoom", {"preset": "private_chat", "invite": [bob["user_id"]]}, alice["access_token"])["room_id"]
            room_path = urllib.parse.quote(room, safe="")
            api("/_matrix/client/v3/join/" + room_path, {}, bob["access_token"])
            event = api("/_matrix/client/v3/rooms/" + room_path + "/send/m.room.message/smoke",
                        {"msgtype": "m.text", "body": "Local Matrix smoke test"}, alice["access_token"], "PUT")
            received = api("/_matrix/client/v3/rooms/" + room_path + "/event/" + urllib.parse.quote(event["event_id"], safe=""), token=bob["access_token"])
            assert received["content"]["body"] == "Local Matrix smoke test"
            transports = api("/_matrix/client/unstable/org.matrix.msc4143/rtc/transports", token=alice["access_token"])
            assert "/livekit/jwt" in json.dumps(transports)
            # Authenticated MatrixRTC request also exercises LiveKit room creation.
            for _ in range(30):
                try:
                    rtc = api("/_matrix/client/v1/rtc/livekit/get_token", {
                        "server_name": settings["server_name"], "url": "wss://" + settings["server_name"] + "/livekit/sfu",
                        "room_id": room, "slot_id": "m.call#room", "member_id": "smoke-member",
                    }, alice["access_token"])
                    assert rtc["jwt"].count(".") == 2
                    break
                except urllib.error.HTTPError:
                    time.sleep(2)
            else:
                raise RuntimeError("MatrixRTC authorization / LiveKit room creation failed")
            matrix_lab.user_command(prefix, directory, "bob", disable=True)
            try:
                api("/_matrix/client/v3/account/whoami", token=bob["access_token"])
            except urllib.error.HTTPError as error:
                assert error.code == 401
            else:
                raise AssertionError("Deactivated Matrix account retained API access")
            print("PASS: local HTTPS, accounts, chat, RTC discovery, LiveKit token/room creation, offboarding.")
            print("Browser media-device and two-participant audio/video acceptance remain manual.")
        except Exception:
            subprocess.run(prefix + ["logs", "--tail", "35", "matrix", "matrixrtc", "gateway", "livekit"], check=False)
            raise
        finally:
            # Only this test's randomly named project and newly created volumes.
            subprocess.run(prefix + ["down", "--volumes", "--remove-orphans"], check=False)


if __name__ == "__main__":
    main()
