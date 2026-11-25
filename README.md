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
| Peer-to-peer files | Full LibreOffice + Syncthing | Local/offline office editing and file synchronization |
| Same-computer collaboration | Nextcloud + Collabora CODE + Element/MatrixRTC | Shared files, browser office co-editing, chat and voice/video calls |

Syncthing synchronizes whole files; simultaneous office edits can produce
conflict copies. It does not provide Word/Excel-style live co-editing. Element is
a Matrix client backed by a homeserver; this lab hosts that server locally.

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

- Installs the full Fedora `libreoffice` suite: Writer, Calc, Impress, Draw,
  Base and Math, plus Firefox, Git, Podman, podman-compose, Syncthing and the
  Nextcloud desktop sync client.
- Starts the per-user Syncthing service when enabled in the config.
- Applies natural scrolling and left-side window buttons through GNOME settings.
- Optionally installs the Element desktop client through the user-scoped Flathub
  remote when `peer.install_element = true`. Element Web is included in the lab
  regardless of this optional desktop-client choice.

This targets regular DNF-based Fedora Workstation, not Silverblue/Atomic.
The dry run works on other Linux systems and changes nothing. For custom
configuration, pass `--config /path/to/config.toml` to any script.

### Subtle Egmont Group appearance

The default `[theme]` uses the main Egmont Group identity as inspiration:

- The supplied Egmont clock photograph as the wallpaper in both light and dark mode.
- GNOME's built-in blue accent, its nearest stock match to cobalt.
- Liberation Sans for interface text and Liberation Serif for document text.
  These open-source fonts stand in for the brand guide's Arial/Times New Roman
  fallbacks. Egmont's actual Gestura and Octave files are not distributed here.
- The local Nextcloud lab's primary color follows `theme.brand_color`.

No shell extensions or replacement GTK theme are installed. Backgrounds are
copied into your user data directory, so moving the Git checkout does not break
them. Applications that use their own styling/fonts can retain those choices.

Preview: [Egmont clock wallpaper](assets/egmont/clock.jpeg).
Photo by User:Jhsmith, CC BY-SA 3.0; see [attribution](assets/egmont/ATTRIBUTION.md).

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
container images and installs the office app and communication services; allow time and disk
space for that download.

```bash
python3 scripts/lab.py up
python3 scripts/lab.py credentials
```

Open `http://localhost:8080` and sign in as `pilot-admin` with the Nextcloud
password. The setup installs/configures Nextcloud's Collabora office
integration. The office server is at `http://localhost:9980`; users
open documents through Nextcloud, rather than directly through that URL.

To connect desktop LibreOffice to the shared files, open the **Nextcloud**
desktop application, add `http://localhost:8080`, authorize it with your test
account and choose its local sync folder (usually `~/Nextcloud`). Save a
Writer/Calc/Impress document there, close the desktop editor and wait for sync.
Open that same file through Nextcloud for a Collabora co-editing session.
Browser changes synchronize back to the local folder. Installing the full
desktop suite does not make Base databases into browser co-editable documents.

For **Element chat, voice and video**, trust the lab's local certificate authority
once on Fedora, then restart Firefox:

```bash
python3 scripts/lab.py trust
```

This uses `sudo trust anchor` to install this lab's development CA in the Fedora
trust store. Its private key remains in the local Caddy data volume, outside Git.
Open **https://localhost:8443** and sign in as `pilot-admin` using the separate
**Matrix password** printed by `credentials`. Firefox should show a valid secure
connection. If it does not recognize the newly trusted CA after a restart,
import `.local/matrix/ca.crt` under Firefox Settings → Privacy & Security →
Certificates → View Certificates → Authorities, with website identification enabled.

The communication stack consists of Synapse, Element Web, LiveKit, a MatrixRTC
authorization service and Caddy for local HTTPS. It enables the required RTC
discovery, delayed-event and state-sync features. LiveKit media is restricted to
this computer's loopback TCP/UDP ports. No hosted Element account or paid
subscription is needed, and Matrix federation is disabled for this pilot.

The main `lab.py up` command starts both the files/office and Matrix components.
Generated configuration is in `.local/matrix/`; account history, signing keys,
media and TLS keys are in named volumes. Preserve those volumes and local secret
files. **Do not change `matrix.server_name` after creating users and rooms.**

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
Create their separate Matrix accounts for Element:

```bash
python3 scripts/lab.py matrix-user alice
python3 scripts/lab.py matrix-user bob
```

Choose passwords at the prompts. At `https://localhost:8443`, log into Element
as Alice and Bob in separate browser profiles. Create a private room, invite
the other user and accept the invitation. Test chat, then start a voice/video
call from the room. Allow microphone/camera access. Mute one side or use
headphones to avoid feedback when both test users are on the same computer.
Share a Nextcloud document link in Element to open it in the browser editor.
LibreOffice handles local/offline editing; Collabora handles the live browser
co-editing session. Avoid simultaneously editing that file in the desktop app.

Nextcloud and Matrix accounts are currently independent: matching usernames do
not synchronize passwords or permissions. Disable Bob in **both** applications
when testing offboarding:

```bash
python3 scripts/lab.py occ user:disable bob
python3 scripts/lab.py matrix-disable bob
python3 scripts/lab.py occ user:auth-tokens:list bob --output=json
```

For immediate session/app-password revocation, delete each listed token by its
actual ID, for example `occ user:auth-tokens:delete bob TOKEN_ID`. Verify the
behavior in Bob's already-open browser too. Account disabling can take several
minutes to invalidate existing sessions. These commands manage the test
application, not the Fedora account, offline file copies or other services.
Files are retained; decide on ownership/transfer before deleting real accounts.
Matrix deactivation revokes chat account access and retains content. A call
already connected to LiveKit may continue until its media authorization/session
ends; this is not an immediate remote media-session kill or a device wipe.

### Updating an existing Talk-based pilot

Wait for any current package installation to finish, then:

```bash
cd ~/fedora-diy-workstation
git pull --ff-only
python3 scripts/setup_fedora.py
python3 scripts/lab.py up
python3 scripts/lab.py trust
python3 scripts/lab.py credentials
```

The workstation rerun installs the full LibreOffice suite if you originally
installed only Writer/Calc/Impress. Lab startup disables the Nextcloud Talk app
when it is present; its existing data and all Nextcloud files are retained.
Talk conversations are not automatically imported into Matrix. Use the new
`matrix-user` commands for chat accounts. If `git pull` reports local config
changes, resolve those changes rather than discarding your configuration.

### Localhost, LAN and calling limitations

This lab publishes **only loopback ports**: files/office use HTTP at 8080/9980;
Element/Matrix use HTTPS at 8443, with LiveKit media on TCP 7881 and UDP 7882.
It is a single-computer development setup, not an internet-facing deployment.
Two browser profiles on that computer are sufficient for the first account
and co-editing exercise. Never forward these HTTP ports from your router.

Using a second computer requires configuring a shared reachable hostname,
trusted HTTPS, Nextcloud trusted domains, office callback/public URLs and
Collabora's host/frame allowlists together. Merely changing the bind address
is insufficient. Calls from another computer also require reachable media
candidates, a shared trusted HTTPS hostname and potentially TURN. The default
LiveKit candidate is deliberately `127.0.0.1`, so it serves same-computer testing only.

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

An optional isolated Docker integration check downloads Matrix images, checks
HTTPS, registration, message exchange, MatrixRTC discovery/authorization,
LiveKit room creation and chat account deactivation, then removes its own
randomly named test containers and volumes. It does not install a host CA:

```bash
python3 tests/matrix_smoke.py
```

## Upstream references

- [Fedora download](https://fedoraproject.org/workstation/download/) and
  [signing keys](https://fedoraproject.org/security/).
- [Syncthing synchronization and conflicts](https://docs.syncthing.net/users/syncing.html).
- [Element Web configuration](https://github.com/element-hq/element-web/blob/develop/docs/config.md).
- [Element Call self-hosting](https://github.com/element-hq/element-call/blob/main/docs/self_hosting.md).
- [MatrixRTC authorization](https://github.com/element-hq/lk-jwt-service).
- [Nextcloud container documentation](https://hub.docker.com/_/nextcloud).
- [Nextcloud office integration](https://github.com/nextcloud/richdocuments/blob/main/docs/install.md)
  and [connection settings](https://github.com/nextcloud/richdocuments/blob/main/lib/AppConfig.php).
- [Nextcloud account and token administration](https://docs.nextcloud.com/server/stable/admin_manual/occ_users.html).

Fedora and the upstream applications are not affiliated with this repository.
