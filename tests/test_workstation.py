import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import ROOT, load_config, run
import download_fedora
import lab
import setup_fedora
import theme
import matrix_lab


class ConfigurationTests(unittest.TestCase):
    def test_public_config_loads(self):
        self.assertEqual(load_config()["fedora"]["release"], "45")

    def modified_config(self, old, new):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text((ROOT / "config.toml").read_text().replace(old, new))
            return load_config(path)

    def test_rejects_non_fedora_download_host(self):
        with self.assertRaises(ValueError):
            self.modified_config("https://download.fedoraproject.org/", "https://fedoraproject.org.example.invalid/")

    def test_rejects_http_download(self):
        with self.assertRaises(ValueError):
            self.modified_config("https://download.fedoraproject.org/", "http://download.fedoraproject.org/")

    def test_rejects_package_argument_injection(self):
        with self.assertRaises(ValueError):
            self.modified_config('"git", "curl"', '"--installroot=/tmp/elsewhere", "curl"')

    def test_rejects_duplicate_ports(self):
        with self.assertRaises(ValueError):
            self.modified_config("office_port = 9980", "office_port = 8080")

    def test_rejects_release_url_mismatch(self):
        with self.assertRaisesRegex(ValueError, "URLs"):
            self.modified_config('release = "45"', 'release = "46"')

    def test_rejects_string_boolean(self):
        with self.assertRaises(ValueError):
            self.modified_config("start_syncthing = true", 'start_syncthing = "false"')

    def test_dry_run_never_executes(self):
        with tempfile.TemporaryDirectory() as directory, patch("common.subprocess.run") as execute:
            for command in setup_fedora.commands(load_config()):
                run(command, dry_run=True)
            theme.apply_theme(load_config(), dry_run=True, backup=Path(directory) / "backup.json",
                              wallpaper_directory=Path(directory) / "wallpapers")
            execute.assert_not_called()
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_user_preferences_do_not_run_as_root(self):
        commands = list(setup_fedora.commands(load_config()))
        preferences = [command for command in commands if command[0] == "gsettings"]
        self.assertEqual(len(preferences), 2)
        self.assertTrue(all(command[0] != "sudo" for command in preferences))


class DownloadTests(unittest.TestCase):
    def test_same_size_corruption_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.iso"
            image.write_bytes(b"bad")
            with self.assertRaisesRegex(ValueError, "checksum"):
                download_fedora.verify_file(image, {"size_bytes": 3, "sha256": hashlib.sha256(b"yes").hexdigest()})

    def test_incomplete_image_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "image.iso"
            image.write_bytes(b"short")
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                download_fedora.verify_file(image, {"size_bytes": 10, "sha256": "0" * 64})

    def test_resume_and_atomic_promotion(self):
        payload = b"complete fixture image"
        settings = copy.deepcopy(load_config()["fedora"])
        settings.update(size_bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
        name = Path(settings["image_url"]).name
        with tempfile.TemporaryDirectory() as directory:
            partial = Path(directory) / (name + ".part")
            partial.write_bytes(payload[:4])
            def fetch(url, destination, *, resume=False):
                if url == settings["image_url"]:
                    self.assertTrue(resume)
                    self.assertEqual(destination.read_bytes(), payload[:4])
                    with destination.open("ab") as stream:
                        stream.write(payload[4:])
                else:
                    destination.write_bytes(b"fixture")
            with patch.object(download_fedora, "fetch", side_effect=fetch), patch.object(download_fedora, "verify_signed_checksum"):
                image = download_fedora.download(settings, directory)
            self.assertEqual(image.read_bytes(), payload)
            self.assertFalse(partial.exists())

    def test_bad_download_is_not_promoted(self):
        settings = copy.deepcopy(load_config()["fedora"])
        settings.update(size_bytes=3, sha256=hashlib.sha256(b"yes").hexdigest())
        name = Path(settings["image_url"]).name
        with tempfile.TemporaryDirectory() as directory:
            def fetch(url, destination, **kwargs):
                destination.write_bytes(b"bad")
            with patch.object(download_fedora, "fetch", side_effect=fetch), patch.object(download_fedora, "verify_signed_checksum"):
                with self.assertRaises(ValueError):
                    download_fedora.download(settings, directory)
            self.assertFalse((Path(directory) / name).exists())
            self.assertTrue((Path(directory) / (name + ".part")).exists())


@unittest.skipUnless(shutil.which("gpg") and shutil.which("gpgv"), "GnuPG required")
class SignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.path = Path(cls.directory.name)
        cls.path.chmod(0o700)
        def gpg(*args, **kwargs):
            return subprocess.run(["gpg", "--homedir", str(cls.path), "--batch", "--yes", *args],
                                  check=True, capture_output=True, **kwargs)
        gpg("--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key",
            "Fixture <fixture@example.invalid>", "ed25519", "sign", "0")
        listing = gpg("--with-colons", "--list-keys", text=True).stdout
        cls.fingerprint = next(line.split(":")[9] for line in listing.splitlines() if line.startswith("fpr:"))
        cls.keys = cls.path / "keys.gpg"
        cls.keys.write_bytes(gpg("--export", cls.fingerprint).stdout)
        cls.image_name = "Fedora-Workstation-Live-fixture.iso"
        cls.settings = {"signing_fingerprint": cls.fingerprint, "sha256": "a" * 64}
        unsigned = cls.path / "unsigned"
        unsigned.write_text(f"SHA256 ({cls.image_name}) = {'a' * 64}\n")
        cls.checksum = cls.path / "CHECKSUM"
        gpg("--pinentry-mode", "loopback", "--passphrase", "", "--output", str(cls.checksum), "--clearsign", str(unsigned))

    @classmethod
    def tearDownClass(cls):
        if shutil.which("gpgconf"):
            subprocess.run(["gpgconf", "--homedir", str(cls.path), "--kill", "gpg-agent"], capture_output=True)
        cls.directory.cleanup()

    def test_valid_signature_and_pinned_key(self):
        download_fedora.verify_signed_checksum(self.checksum, self.keys, self.image_name, self.settings)

    def test_other_signer_rejected(self):
        with self.assertRaisesRegex(ValueError, "release key"):
            download_fedora.verify_signed_checksum(self.checksum, self.keys, self.image_name,
                                                   {**self.settings, "signing_fingerprint": "0" * 40})

    def test_correct_signature_wrong_image_hash_rejected(self):
        with self.assertRaisesRegex(ValueError, "Signed checksum"):
            download_fedora.verify_signed_checksum(self.checksum, self.keys, self.image_name,
                                                   {**self.settings, "sha256": "b" * 64})

    def test_tampered_signed_payload_rejected(self):
        altered = self.path / "TAMPERED"
        altered.write_text(self.checksum.read_text().replace("a" * 64, "b" * 64))
        with self.assertRaises(subprocess.CalledProcessError):
            download_fedora.verify_signed_checksum(altered, self.keys, self.image_name, self.settings)


class LabTests(unittest.TestCase):
    def test_matrix_keeps_every_published_port_on_loopback(self):
        config = load_config()
        services = lab.compose_document(config["lab"], config["matrix"])["services"]
        ports = [port for service in services.values() for port in service.get("ports", [])]
        self.assertEqual(len(ports), 5)
        self.assertTrue(all(port.startswith("127.0.0.1:") for port in ports))
        self.assertNotIn("ports", services["matrix"])
        self.assertEqual(services["matrixrtc"]["network_mode"], "service:gateway")
        self.assertNotIn("LIVEKIT_INSECURE_SKIP_VERIFY_TLS", services["matrixrtc"]["environment"])

    def test_matrix_upgrade_keeps_existing_credentials_and_identity(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as directory:
            _, environment = lab.initialize(config["lab"], directory)
            original = environment.read_text()
            lab.initialize(config["lab"], directory, config["matrix"], config["theme"])
            state = Path(directory) / "matrix/secrets.json"
            before = state.read_text()
            lab.initialize(config["lab"], directory, config["matrix"], config["theme"])
            self.assertEqual(state.read_text(), before)
            self.assertEqual(environment.read_text(), original)
            self.assertEqual(stat.S_IMODE(state.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(state.parent.stat().st_mode), 0o700)
            with self.assertRaisesRegex(ValueError, "identity"):
                matrix_lab.initialize({**config["matrix"], "server_name": "different.invalid"}, directory)

    def test_matrix_call_secrets_are_not_embedded_in_compose(self):
        config = load_config()
        with tempfile.TemporaryDirectory() as directory:
            document, _ = lab.initialize(config["lab"], directory, config["matrix"], config["theme"])
            state = json.loads((Path(directory) / "matrix/secrets.json").read_text())
            for key, secret in state.items():
                if key != "server_name":
                    self.assertNotIn(secret, document.read_text())
            homeserver = json.loads((Path(directory) / "matrix/homeserver.yaml").read_text())
            self.assertFalse(homeserver["enable_registration"])
            self.assertEqual(homeserver["federation_domain_whitelist"], [])
            self.assertTrue(homeserver["experimental_features"]["msc4143_enabled"])

    def test_only_loopback_ports_are_published(self):
        services = lab.compose_document(load_config()["lab"])["services"]
        ports = [port for service in services.values() for port in service.get("ports", [])]
        self.assertEqual(len(ports), 2)
        self.assertTrue(all(port.startswith("127.0.0.1:") for port in ports))
        self.assertNotIn("ports", services["db"])
        self.assertNotIn("ports", services["cache"])

    def test_credentials_are_private_and_persist_across_reruns(self):
        with tempfile.TemporaryDirectory() as directory:
            document, environment = lab.initialize(load_config()["lab"], Path(directory) / "local")
            before = environment.read_text()
            lab.initialize(load_config()["lab"], environment.parent)
            self.assertEqual(environment.read_text(), before)
            self.assertEqual(stat.S_IMODE(environment.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(environment.parent.stat().st_mode), 0o700)
            passwords = [line.split("=", 1)[1] for line in before.splitlines()]
            self.assertEqual(len(passwords), 2)
            self.assertNotEqual(*passwords)
            self.assertTrue(all(password not in document.read_text() for password in passwords))

    def test_custom_ports_are_used_consistently(self):
        settings = {**load_config()["lab"], "cloud_port": 18080, "office_port": 19980}
        services = lab.compose_document(settings)["services"]
        self.assertEqual(services["cloud"]["ports"], ["127.0.0.1:18080:80"])
        self.assertEqual(services["office"]["environment"]["server_name"], "localhost:19980")
        self.assertIn("http://localhost:18080", services["office"]["environment"]["extra_params"])

    def test_no_host_mounts_or_privileged_containers(self):
        services = lab.compose_document(load_config()["lab"])["services"]
        for service in services.values():
            self.assertFalse(service.get("privileged", False))
            self.assertTrue(all(not volume.startswith("/") for volume in service.get("volumes", [])))

    def test_rejects_symlinked_secret_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            target = path / "outside"
            target.write_text("do not change")
            local = path / "local"
            local.mkdir()
            (local / "lab.env").symlink_to(target)
            with self.assertRaises(ValueError):
                lab.initialize(load_config()["lab"], local)
            self.assertEqual(target.read_text(), "do not change")


if __name__ == "__main__":
    unittest.main()
