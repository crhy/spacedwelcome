# Spaced Linux Welcome

Spaced Linux Welcome is the native first-run application installer for Spaced
Linux. It opens the SpacedBazaar already installed in the base system and can
install a curated set of user Flatpaks from Flathub and the signed Spaced
GitHub repository.

<img width="720" height="507" alt="WelcomeScreenshot" src="https://github.com/user-attachments/assets/363d1e13-ec5b-4a79-9cfa-d4a257f93108" />

The UI always names the application and source currently being installed. Its
**Details** pane streams remote setup, Flatpak, retry, and failure output while
work is in progress.

The **Help & Apps** page starts with task-oriented recommendations for video,
photos, audio, email, coding, emulation, streaming, and games. Choosing one
launches its exact `appstream://` page in the preinstalled SpacedBazaar; the
user still confirms any installation in Bazaar.

## Catalog

The structured catalog lives in `data/catalog.json`. Version 1 contains these
verified CRHY applications:

| Application | Flatpak ID | Delivery |
| --- | --- | --- |
| SpacedBazaar | `io.github.crhy.SpacedBazaar` | Preinstalled system Flatpak |
| Voice2Text AI | `io.github.crhy.voice2textai` | Signed `spaced-github` remote |
| Cards With Cats | `io.github.crhy.CardsWithCats` | Signed `spaced-github` remote |
| Brutal Chess | `io.github.crhy.BrutalChess` | Signed `spaced-github` remote |
| Spaced Update | `org.spacedlinux.SpacedUpdate` | Signed `spaced-github` remote |

Audacious, Brave, LibreOffice, and VLC are suggested from Flathub.

SpacedBazaar's publication job validates each curated GitHub release bundle,
imports it into a GPG-signed OSTree repository, and regenerates AppStream
metadata. Welcome installs those reviewed applications by exact Flatpak ID from
that same `spaced-github` remote. This avoids mutable “latest release” downloads
at first login and gives every app a normal signed update path.

## Commands

```sh
spaced-welcome-install --list
spaced-welcome-install --list --json
spaced-welcome-install --install suggested
spaced-welcome-install --install cards-with-cats --events
spaced-welcome
```

`--events` emits newline-delimited JSON for the GTK UI and other front ends.
One failed application does not prevent the remaining suggestions from being
attempted.

## Development

```sh
make check
make deb
```

The package artifact is exactly `dist/spaced-welcome_0.1.6_all.deb`.

The behavioral test harness can inject commands and paths without weakening
production validation:

- `SPACED_WELCOME_CATALOG`
- `SPACED_WELCOME_FLATPAK`
- `SPACED_WELCOME_ATTEMPTS`
- `SPACED_WELCOME_RETRY_DELAY`
- `SPACED_WELCOME_INSTALLER`

## Packaging and OS integration

This project ships a native `Architecture: all` Debian package because the
first-run app must invoke the host Flatpak installation, detect the live
session, refresh desktop exports, and launch Spaced Linux system tools. The
Flatpak build uses the standard host Flatpak portal for the same operations.

Spaced Linux should install the `spaced-welcome` Debian package and the
`io.github.crhy.SpacedBazaar` system Flatpak in the live filesystem. Calamares
then copies both into the installed target, so SpacedBazaar is available before the
first-login Welcome window appears.

## License

Copyright 2026 Spaced Linux Team. Licensed under the GNU General Public License,
version 3 or (at your option) any later version. See `LICENSE`.
