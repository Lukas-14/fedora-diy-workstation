# Fedora DIY workstation

A reproducible Fedora Workstation + GNOME pilot with a public configuration,
a verified ISO downloader, peer-to-peer tools, and an optional collaboration lab
that runs **on the test computer**. No paid subscription or rented server is
required for these components.

The repository configures Fedora **after a normal installation**. Choose disks,
disk encryption and your personal account in the Fedora installer. The scripts
do not partition disks, overwrite USB drives or replace your installed OS.

## Choose the first experiment

| Option | Components | What you can test |
| --- | --- | --- |
| Peer-to-peer | LibreOffice + Syncthing; optionally Jami | Local office editing, file synchronization, chat and calls |
| Same-computer collaboration | Nextcloud + Collabora CODE + Nextcloud Talk | Shared files, browser office co-editing, chat and application accounts |

Syncthing synchronizes whole files; simultaneous office edits can produce
conflict copies. It does not provide Word/Excel-style live co-editing. Jami
provides decentralized communication, not a complete corporate identity system.

For the first co-editing demonstration, run the lab on the Fedora laptop and
open two browser profiles as two different users. The laptop is the server
while those containers are running. Sleeping or shutting it down stops access.

## 1. Get the repository

Python 3.11 or newer is required. On a newly installed Fedora Workstation:

```bash
sudo dnf install git python3 curl gnupg2-verify
git clone https://github.com/Lukas-14/fedora-diy-workstation.git
cd fedora-diy-workstation
```

All shared choices live in [`config.toml`](config.toml). It contains package
names, desktop preferences, public Fedora download information and lab image
names. Edit it before applying the setup. Keep machine-specific or secret
configuration under ignored `.local/`, not in that public file.

## 2. Download Fedora, when you need another installer

On an existing Linux computer with Python, curl and gpgv:

```bash
python3 scripts/download_fedora.py
```

This downloads the configured Workstation ISO into ignored `downloads/`.
Downloads resume from an `.iso.part` file. The script checks the signed Fedora
checksum, the pinned release signing-key fingerprint, the exact size and SHA256
before promoting that file to `.iso`. Rerun the command after a network failure.
An oversized or checksum-invalid file is retained for inspection rather than
silently trusted or deleted.

Verify an existing ISO, checksum file and `fedora.gpg` without network access:

```bash
python3 scripts/download_fedora.py --verify-only --output /path/to/download-directory
```

The config currently pins Fedora 45 x86_64, matching the Workstation installer
used for this pilot. When updating it, review **all** Fedora URL, filename, size,
hash and fingerprint fields together against the official download and security
pages. A newer release is not selected automatically.

Use [Fedora Media Writer](https://fedoraproject.org/workstation/download/) to
create another installer USB. Install Fedora with its graphical installer,
then continue below in a terminal in the installed GNOME desktop.

## 3. Apply the workstation configuration

```bash
python3 scripts/setup_fedora.py --dry-run
python3 scripts/setup_fedora.py
```

Run as your normal desktop user. Only DNF uses sudo. The setup:

- Installs LibreOffice, Firefox, Git, Podman, podman-compose and Syncthing.
- Starts the per-user Syncthing service when enabled in the config.
- Applies natural scrolling and left-side window buttons through GNOME settings.
- Optionally installs Jami through the user-scoped Flathub remote when
  `peer.install_jami = true`.

This targets regular DNF-based Fedora Workstation, not Silverblue/Atomic.
The dry run works on other Linux systems and changes nothing. For custom
configuration, pass `--config /path/to/config.toml` to any script.

### Subtle Egmont Group appearance

The default `[theme]` uses the main Egmont Group identity as inspiration:

- Original, quiet editorial wallpaper in white/cobalt (`#ffffff` / `#326dd9`).
- A matching dark wallpaper in navy/cornflower (`#1c304a` / `#acc1f5`).
- GNOME's built-in blue accent, its nearest stock match to cobalt.
- Liberation Sans for interface text and Liberation Serif for document text.
  These open-source fonts stand in for the brand guide's Arial/Times New Roman
  fallbacks. Egmont's actual Gestura and Octave files are not distributed here.
- The local Nextcloud lab's primary color follows `theme.brand_color`.

No shell extensions or replacement GTK theme are installed. Backgrounds are
copied into your user data directory, so moving the Git checkout does not break
them. Applications that use their own styling/fonts can retain those choices.

Preview: [light wallpaper](assets/egmont/light.svg) · [dark wallpaper](assets/egmont/dark.svg).

Apply or inspect just the appearance, without reinstalling packages:

```bash
python3 scripts/theme.py --dry-run apply
python3 scripts/theme.py apply
```

The initial GNOME appearance values are saved privately under
`.local/theme-backup.json` before the first change. Reapplying preserves that
snapshot. Restore those values with:

```bash
python3 scripts/theme.py restore
```

Set `theme.enabled = false` to skip future appearance changes. Use `restore`
to undo an already-applied desktop theme; it does not reset Nextcloud's separate
application settings. To use locally installed licensed brand fonts, edit the
font descriptions in `[theme]`. This is a community pilot theme, not an official
Egmont-distributed workstation image.

References: [Egmont Group colours](https://brandcenter.egmont.com/colours) and
[typography](https://brandcenter.egmont.com/typography).

Open Syncthing at `http://127.0.0.1:8384`, pair a second device and explicitly
choose the folder to share. Pairing is deliberately manual: no private device
IDs or keys belong in the public repository. Keep Syncthing's GUI on loopback.
Syncthing can use public discovery and relay infrastructure; configure static
addresses and disable those features in its settings if you want a LAN-only
experiment.

## 4. Optional: run the collaboration lab on this computer

The lab uses rootless Podman on Fedora. Docker Compose is also supported with
`--engine docker`. You do not need a VM, cloud account, domain or separate
physical server for the localhost experiment. The first start pulls several
container images and installs the office and Talk apps; allow time and disk
space for that download.

```bash
python3 scripts/lab.py up
python3 scripts/lab.py credentials
```

Open `http://localhost:8080` and sign in as `pilot-admin` with the locally
generated password. The setup installs/configures Nextcloud's Collabora office
integration and Talk. The office server is at `http://localhost:9980`; users
open documents through Nextcloud, rather than directly through that URL.

The public `config.toml` controls ports and images. Generated Compose JSON and
random passwords are stored in ignored `.local/` with private file permissions.
Rerunning `init` or `up` preserves existing credentials. Containers store the
database and documents in named persistent volumes. Retain `.local/lab.env`
when keeping or migrating that data. Changing the initial-admin environment
value does not reset an existing Nextcloud account's password.

Administration and troubleshooting:

```bash
python3 scripts/lab.py status
python3 scripts/lab.py logs
python3 scripts/lab.py configure
python3 scripts/lab.py down
```

`down` stops/removes the containers and their network while retaining data
volumes. It does not uninstall workstation packages or stop Syncthing. No
automatic service is installed to start the lab after reboot; rerun `up`.

The images are tagged in the public config. CODE uses its development channel;
after evaluating an image, you can replace its tag with an exact tested digest.
Review upgrades explicitly; there is no automatic image updater.

### First onboarding/offboarding exercise

Create two test accounts. Nextcloud prompts for their passwords in your terminal:

```bash
python3 scripts/lab.py occ user:add alice
python3 scripts/lab.py occ user:add bob
```

Log into separate browser profiles, share a document and edit it together.
Try a Talk conversation. Then disable Bob's application account:

```bash
python3 scripts/lab.py occ user:disable bob
python3 scripts/lab.py occ user:auth-tokens:list bob --output=json
```

For immediate session/app-password revocation, delete each listed token by its
actual ID, for example `occ user:auth-tokens:delete bob TOKEN_ID`. Verify the
behavior in Bob's already-open browser too. Account disabling can take several
minutes to invalidate existing sessions. These commands manage the test
application, not the Fedora account, offline file copies or other services.
Files are retained; decide on ownership/transfer before deleting real accounts.

### Localhost, LAN and calling limitations

This lab publishes **only** `127.0.0.1:8080` and `127.0.0.1:9980` and uses HTTP.
It is a single-computer development setup, not an internet-facing deployment.
Two browser profiles on that computer are sufficient for the first account
and co-editing exercise. Never forward these HTTP ports from your router.

Using a second computer requires configuring a shared reachable hostname,
trusted HTTPS, Nextcloud trusted domains, office callback/public URLs and
Collabora's host/frame allowlists together. Merely changing the bind address
is insufficient. Calls across different networks may additionally need TURN
and a conferencing backend. Jami is the simpler initial P2P calling experiment.

Collabora CODE is the free development/community build. You can run this pilot
without buying a Collabora subscription; you own its operation, compatibility
testing and upgrades. No vendor support agreement is bundled. Upstream tools
retain their own licenses; this repository's MIT license covers its scripts
and documentation only.

## Scope and validation

This first slice supplies an installed-workstation setup and a local application
lab. Central Linux identity, automated employee workflows, endpoint security
management and central OpenTelemetry collection are later integrations. A P2P
file copy cannot be recalled simply by disabling an application account.

The tests exercise real GnuPG signatures and signer pinning, corrupted-image
rejection, resumed-download promotion, configuration validation, dry-run behavior,
loopback bindings and generated-secret persistence/permissions:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/setup_fedora.py --dry-run
python3 scripts/lab.py init
docker compose --env-file .local/lab.env --file .local/compose.json config --quiet
```

CI runs those checks. Desktop setup and browser co-editing still need a live
acceptance test on the newly installed Fedora computer; unit tests and Compose
validation do not establish browser, camera or rootless-container compatibility.

## Upstream references

- [Fedora download](https://fedoraproject.org/workstation/download/) and
  [signing keys](https://fedoraproject.org/security/).
- [Syncthing synchronization and conflicts](https://docs.syncthing.net/users/syncing.html).
- [Jami](https://jami.net/).
- [Nextcloud container documentation](https://hub.docker.com/_/nextcloud).
- [Nextcloud office integration](https://github.com/nextcloud/richdocuments/blob/main/docs/install.md)
  and [connection settings](https://github.com/nextcloud/richdocuments/blob/main/lib/AppConfig.php).
- [Nextcloud account and token administration](https://docs.nextcloud.com/server/stable/admin_manual/occ_users.html).

Fedora and the upstream applications are not affiliated with this repository.
