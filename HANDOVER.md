# Handover: Fedora DIY workstation pilot

Start here if you are taking over this project. The aim is a DIY Fedora desktop
with office editing, shared files, chat and calls, initially hosted on the test
computer. There is no required paid subscription or separate server.

## Current state and first priority

| Area | State |
| --- | --- |
| Fedora Workstation + GNOME | Setup script available; full LibreOffice and Nextcloud desktop client are included. |
| Appearance | Subtle Egmont Group colors/fonts and the supplied Egmont clock wallpaper. |
| Nextcloud | User can access the web app. Nextcloud users are separate from Matrix users. |
| Browser office editing | **Unresolved:** user reports “Unauthorized WOPI host” when opening a DOCX. Diagnose this first; no confirmed fix yet. |
| Element web page | Gateway port mismatch fixed in commit `9b3a0bf`: Element uses internal port 8080. Ensure the Fedora checkout includes that update. |
| Chat and calls | Docker integration check passed for web page/config, account creation, chat, RTC discovery, LiveKit authorization/room creation and deactivation. Camera/microphone acceptance on Fedora remains to be completed. |
| Central employee/device management | Not implemented. This is an application pilot, not a completed Intune/CoreView/Entra replacement. |

The automated integration check ran using Docker on the development computer.
It does **not** prove rootless Podman, office co-editing or hardware media works
on the Fedora test computer. Treat the table above as the starting point, not
an acceptance sign-off.

## Take over the existing test computer

Use the **same Fedora user, repository checkout and container engine** as the
original setup. Rootless containers and their data belong to that user. Running
with sudo or switching from Podman to Docker can make existing data appear missing.

In a terminal inside the installed Fedora GNOME session:

```bash
cd ~/fedora-diy-workstation
git status --short
git pull --ff-only
python3 scripts/lab.py status
```

If Git reports local changes or refuses the pull, preserve and reconcile those
changes. Do not discard the person's configuration. If the checkout is elsewhere,
use its actual path.

Start or update the services, then install the local Matrix CA if needed:

```bash
python3 scripts/lab.py up
python3 scripts/lab.py trust
```

Stop and read any error from `up`; it may have started some services before a
later configuration step failed. Fully restart Firefox after `trust`.

Rerun `python3 scripts/setup_fedora.py` only when workstation packages/settings
need updating. A lab update does not require reinstalling Fedora. The workstation
script also applies the desktop theme; appearance alone can be applied with
`python3 scripts/theme.py apply` or restored with `python3 scripts/theme.py restore`.

### Addresses and login

Open these **on the computer running the lab**:

| Address | Purpose |
| --- | --- |
| `http://localhost:8080` | Nextcloud files, sharing and browser office editing |
| `https://localhost:8443` | Element chat and calls; HTTPS is required |
| `http://localhost:9980` | Collabora service, normally opened through Nextcloud |
| `http://127.0.0.1:8384` | Syncthing, if the workstation script enabled it |

Both application administrators are named **`pilot-admin`**, with **different
generated passwords**. Display them privately on the test computer:

```bash
python3 scripts/lab.py credentials
```

`Password` is for Nextcloud; `Matrix password` is for Element. Neither is the
Fedora login password. Never paste this command's output into GitHub.

If Firefox still rejects the certificate after a restart, import
`.local/matrix/ca.crt` in Firefox's certificate Authorities settings and allow
website identification. Do not change the URL to plain HTTP as a workaround.

## Diagnose the outstanding DOCX/WOPI issue

WOPI is the connection through which Collabora reads and saves Nextcloud files.
The user-facing error does not establish whether Collabora rejected a hostname
or Nextcloud rejected a callback. Obtain logs before changing allowlists.

1. Open Nextcloud at exactly `http://localhost:8080` and reproduce the failure
   with a small DOCX owned by the signed-in user. Record the time and exact error.
2. Inspect the generated settings and service state:

   ```bash
   python3 scripts/lab.py status
   python3 scripts/lab.py occ config:app:get richdocuments wopi_url
   python3 scripts/lab.py occ config:app:get richdocuments public_wopi_url
   python3 scripts/lab.py occ config:app:get richdocuments wopi_callback_url
   python3 scripts/lab.py occ config:app:get richdocuments wopi_allowlist
   curl --fail http://localhost:9980/hosting/discovery
   python3 scripts/lab.py logs
   ```

3. Compare the results against the intended routes:

   | Connection | Intended value |
   | --- | --- |
   | Nextcloud → Collabora | `http://office:9980` |
   | Browser → Collabora | `http://localhost:9980` |
   | Collabora → Nextcloud | `http://cloud` (port 80) |
   | Collabora allowed WOPI host | `aliasgroup1=http://cloud:80` |
   | Nextcloud WOPI allowlist | The office container IP, resolved from inside the cloud container during configuration |

   These are defaults; custom ports must agree with `config.toml`. Container
   `localhost` refers to that container, not the Fedora host. Do not use
   `localhost:8080` as the internal callback address.

4. Reapply the existing settings, then close the editor tab and reopen the file:

   ```bash
   python3 scripts/lab.py configure
   ```

   This refreshes the office IP allowlist and integration settings. If it fails,
   keep its exact error. It does not restart containers or apply changed Compose
   environment variables; use `lab.py up` after changing those.

5. If still broken, inspect `office` and `cloud` logs around the reproduction.
   For the default Fedora engine, more targeted container output is available:

   ```bash
   podman-compose --project-name fedora-diy-workstation --env-file .local/lab.env --file .local/compose.json logs --tail 100 office cloud
   podman-compose --project-name fedora-diy-workstation --env-file .local/lab.env --file .local/compose.json exec -T cloud tail -n 100 /var/www/html/data/nextcloud.log
   ```

   Look for `WOPI`, `CheckFileInfo`, `Unauthorized`, `Forbidden`, rejected hosts
   and source addresses. Redact access tokens, passwords and document contents
   before sharing logs. Do not “fix” this by allowing every host or every IP.

The relevant code is `compose_document()` and `configure()` in
[`scripts/lab.py`](scripts/lab.py). A successful discovery request confirms the
service responds, not that document opening or saving works. Verify both after a fix.

## Users, invitations and a working test

Use two separate browser profiles, one for Alice and one for Bob. Two ordinary
tabs in one profile usually share the same login session.

For **new** test users only:

```bash
python3 scripts/lab.py occ user:add alice
python3 scripts/lab.py occ user:add bob
python3 scripts/lab.py matrix-user alice
python3 scripts/lab.py matrix-user bob
```

Choose passwords at the terminal prompts. Check existing Nextcloud users with
`python3 scripts/lab.py occ user:list`. Existing users do not need recreating.
Matching names in the two apps do not synchronize passwords or permissions.

In **Nextcloud**, Alice uploads a document, clicks its Share icon, searches for
the Nextcloud user `bob`, selects him and grants **Can edit**. Bob opens **Shared
with you**. Once WOPI is fixed, both open the same file and verify edits appear
in both browsers, survive closing and reopening, and are saved to Nextcloud.

In **Element**, Alice starts a new chat using Bob's full Matrix ID:
`@bob:localhost:8443`. Bob accepts the invitation. Alice's ID is
`@alice:localhost:8443`. Searching only a short name may not find someone who
does not yet share a room. Both must have Matrix accounts on this local server.
Test messages, then a voice/video call with microphone/camera permission. Use
headphones or mute one side to avoid feedback. Share a Nextcloud file link in chat.

If Bob was already used for the offboarding test, he may be disabled/deactivated.
Use a fresh test name in both systems rather than assuming registration resets
an existing account.

### Connect local LibreOffice

The full desktop suite includes Writer, Calc, Impress, Draw, Base and Math.
Open the Nextcloud desktop application, connect to `http://localhost:8080`,
authorize it using a Nextcloud test account and select a sync folder, normally
`~/Nextcloud`. Open files from that folder in LibreOffice. Save, close and wait
for synchronization before opening the same file in the browser.

Desktop synchronization exchanges files; it does not turn LibreOffice into a
live Collabora client. Avoid simultaneous desktop/browser edits to the same
file. Base databases are not browser co-editable office documents.

### Offboarding exercise

Use a disposable test account, after the collaboration tests:

```bash
python3 scripts/lab.py occ user:disable bob
python3 scripts/lab.py matrix-disable bob
python3 scripts/lab.py occ user:auth-tokens:list bob --output=json
```

Revoke any listed Nextcloud app/session tokens by their actual IDs using
`python3 scripts/lab.py occ user:auth-tokens:delete bob TOKEN_ID`. Test existing
sessions as well as a fresh login. Matrix deactivation revokes chat access and
retains content; it does not necessarily terminate an already connected media
session immediately. Offline copies remain on the device. These commands do
not disable the Fedora user or delete retained files.

## Where things live and how to operate them

| File/component | Responsibility |
| --- | --- |
| `config.toml` | Public package, appearance, port and image settings |
| `scripts/download_fedora.py` | Resumable ISO download with signed-checksum verification |
| `scripts/setup_fedora.py` | Fedora DNF packages and per-user GNOME/Syncthing setup |
| `scripts/theme.py` | Wallpaper/fonts/accent application and appearance restore |
| `scripts/lab.py` | Container composition, startup, Nextcloud/Collabora integration and admin commands |
| `scripts/matrix_lab.py` | Synapse, Element, local HTTPS and MatrixRTC configuration/account helpers |
| `.local/` | Private generated config, passwords and exported public CA; ignored by Git |
| Container volumes | Nextcloud files/database, Matrix messages/media/signing keys, and TLS CA private keys |

The files/office services are Nextcloud, PostgreSQL, Valkey, a cron worker and
Collabora CODE. Chat/calls use Synapse, Element Web, LiveKit, its authorization
service and the Caddy HTTPS gateway. The gateway forwards Element traffic to
internal port **8080**, Matrix API traffic to Synapse and call traffic to the
RTC services. Published ports are all loopback-only. Matrix federation and
public self-registration are disabled.

```bash
python3 scripts/lab.py status     # Service status
python3 scripts/lab.py logs       # Recent logs
python3 scripts/lab.py configure  # Reapply application integration settings
python3 scripts/lab.py down      # Stop/remove containers; retain data volumes
python3 scripts/lab.py up        # Start again, including after reboot
```

There is no automatic startup service. Sleep/shutdown makes the laptop's
applications unavailable. `down` does not stop Syncthing or remove desktop apps.
All `lab.py` commands must use the same engine. If the existing lab uses Docker,
put `--engine docker` **before** the action, e.g.
`python3 scripts/lab.py --engine docker status`, and replace `podman-compose`
with `docker compose` in direct commands.

Preserve `.local/` **and** the container volumes when handing over existing data.
A Git clone does not contain accounts, documents or their passwords. Copying
`.local/` alone is not a data backup either. Moving to a different OS user or
computer requires a deliberate data/volume migration and restore test.
Never delete volumes to troubleshoot. Do not change `matrix.server_name` after
users/rooms exist; it is part of their identity. Password changes made manually
in an app are not automatically reflected in the generated credential files.

## Checks and next work

For repository changes:

```bash
python3 -m unittest discover -s tests -v
python3 scripts/setup_fedora.py --dry-run
git diff --check
```

The optional `python3 tests/matrix_smoke.py` uses Docker, downloads images if
needed, creates its own random project/ports and removes only its own containers
and volumes. It does not install a CA on the host and does not test Collabora.
See [README.md](README.md#scope-and-validation) for Compose validation and details.

Suggested order for the next few days:

1. Resolve WOPI on Fedora; verify DOCX opening, saving, permissions and two-user
   co-editing. Record the cause and fix here and add a meaningful regression check.
2. Finish Fedora acceptance: local LibreOffice sync, Element invitations,
   two-participant audio/video, reboot/restart, and both application offboarding paths.
3. Only after that, choose one next slice: employee workflow automation for
   Linux plus one application, or a central identity proof of concept. Keep it
   small enough to demonstrate end to end.

Central Linux identity, SSO, coordinated onboarding/offboarding, endpoint policy,
backups and central OpenTelemetry collection remain separate work. Telemetry
collects operational data; it does not provision users or enforce access.
Several images currently use `latest`; record tested versions/digests before
relying on repeatable deployments. LAN use also needs a reachable shared hostname,
trusted HTTPS, office callback/allowlist changes and reachable call media (possibly
TURN). Merely opening a firewall port is insufficient for the current localhost lab.

## Reference material

- [Project setup and architecture](README.md)
- [Nextcloud sharing](https://docs.nextcloud.com/server/stable/user_manual/en/files/sharing.html)
- [Nextcloud Office configuration](https://docs.nextcloud.com/server/stable/admin_manual/office/configuration.html)
- [Nextcloud Office URL configuration source](https://github.com/nextcloud/richdocuments/blob/main/lib/AppConfig.php)
- [Collabora installation and troubleshooting](https://sdk.collaboraonline.com/CO-SDK-manual.pdf)
- [Element invitations](https://docs.element.io/latest/element-support/matrix-rooms/getting-started-creating-a-room/)
