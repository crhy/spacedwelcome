# Spaced Linux Welcome

Spaced Linux Welcome is the native first-run application installer for Spaced
Linux. It installs SpacedBazaar and a curated set of user Flatpaks from
Flathub and the signed Spaced GitHub repository after the OS is installed.

![Spaced Linux Welcome 0.1.7 showing post-install apps from Flathub and Spaced GitHub](screenshots/welcome-0.1.7.png)

The UI always names the application and source currently being installed. Its
**Details** pane streams remote setup, Flatpak, retry, and failure output while
work is in progress.

The **Help & Apps** page starts with task-oriented recommendations for video,
photos, audio, email, coding, emulation, streaming, and games. Choosing one
launches its exact `appstream://` page in SpacedBazaar; the
user still confirms any installation in Bazaar.

## Catalog

The structured catalog lives in `data/catalog.json`. Version 1 contains these
verified CRHY applications:

| Application | Flatpak ID | Delivery |
| --- | --- | --- |
| SpacedBazaar | `io.github.crhy.SpacedBazaar` | Signed `spaced-github` remote |
| Voice2Text AI | `io.github.crhy.voice2textai` | Signed `spaced-github` remote |
| Cards With Cats | `io.github.crhy.CardsWithCats` | Signed `spaced-github` remote |
| Brutal Chess | `io.github.crhy.BrutalChess` | Signed `spaced-github` remote |
| Spaced Update | `org.spacedlinux.SpacedUpdate` | Signed `spaced-github` remote |

Audacious, Brave, LibreOffice, and VLC are suggested from Flathub's `stable`
branch. Every catalog entry names its branch explicitly so a missing remote
branch fails validation before release instead of on an end user's machine.

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

The package artifact is exactly `dist/spaced-welcome_0.1.7_all.deb`.

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

Spaced Linux should install only the small native `spaced-welcome` Debian
package in the live filesystem. On the installed system, the user can choose
**Install Suggested Apps** to fetch SpacedBazaar and the rest of the catalog.

## License

Copyright 2026 Spaced Linux Team. Licensed under the GNU General Public License,
version 3 or (at your option) any later version. See `LICENSE`.
