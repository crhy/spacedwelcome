# Spaced Linux Welcome

Spaced Linux Welcome is the native first-run application installer for Spaced
Linux. It opens the SpacedBazaar already installed in the base system and can
install a curated set of user Flatpaks from Flathub and verified CRHY GitHub
releases.

<img width="720" height="507" alt="WelcomeScreenshot" src="https://github.com/user-attachments/assets/363d1e13-ec5b-4a79-9cfa-d4a257f93108" />

The UI always names the application and source currently being installed. Its
**Details** pane streams resolver, download, verification, Flatpak, retry, and
failure output while work is in progress.

## Catalog

The structured catalog lives in `data/catalog.json`. Version 1 contains these
verified CRHY applications:

| Application | Flatpak ID | Delivery |
| --- | --- | --- |
| SpacedBazaar | `io.github.crhy.SpacedBazaar` | Preinstalled system Flatpak |
| Voice2Text AI | `io.github.crhy.voice2textai` | Latest stable GitHub release |
| Cards with Cats | `io.github.crhy.ScumWithCats` | Latest stable GitHub release |
| Brutal Chess | `io.github.crhy.BrutalChess` | Latest stable GitHub release |
| Spaced Update | `org.spacedlinux.SpacedUpdate` | Latest stable GitHub release |

Audacious, Brave, LibreOffice, and VLC are suggested from Flathub.

GitHub release assets are selected by an exact architecture-specific name or
name template. Before an install, the helper:

1. accepts only a stable `crhy/*` release and an expected `github.com` release URL;
2. preserves the final `.flatpak` suffix and resumes a private partial download;
3. checks the GitHub asset size and SHA-256 digest when GitHub supplies one;
4. imports the bundle into a temporary OSTree repository and validates its exact
   application ID, architecture, and branch;
5. ensures the user's Flathub runtime remote exists; and
6. installs noninteractively with independent retries and a post-install check.

Direct GitHub bundles are curated, not arbitrary search results. SpacedBazaar
owns broader GitHub discovery; Welcome deliberately installs only reviewed
catalog entries.

## Commands

```sh
spaced-welcome-install --list
spaced-welcome-install --list --json
spaced-welcome-install --resolve cards-with-cats
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
PYTHONPATH=src tools/validate-live-releases.py
```

The package artifact is exactly `dist/spaced-welcome_0.1.0_all.deb`.
The optional live-release validator downloads and inspects every current CRHY
bundle without installing it; Voice2Text AI is currently about 520 MB.

The behavioral test harness can inject commands and paths without weakening
production validation:

- `SPACED_WELCOME_CATALOG`
- `SPACED_WELCOME_ARCH`
- `SPACED_WELCOME_CACHE_DIR`
- `SPACED_WELCOME_CURL`
- `SPACED_WELCOME_FLATPAK`
- `SPACED_WELCOME_OSTREE`
- `SPACED_WELCOME_ATTEMPTS`
- `SPACED_WELCOME_RETRY_DELAY`
- `SPACED_WELCOME_INSTALLER`

`SPACED_WELCOME_GITHUB_API_ROOT` is accepted only when
`SPACED_WELCOME_ALLOW_TEST_API=1`; downloaded asset URLs must still use the
expected HTTPS GitHub release path.

## Packaging and OS integration

This project ships a native `Architecture: all` Debian package because the
first-run app must invoke the host Flatpak installation, inspect local bundles,
detect the live session, refresh desktop exports, and launch Spaced Linux system
tools. A sandboxed Welcome Flatpak would either lose those capabilities or need
an overly broad host-command permission.

Spaced Linux should install the `spaced-welcome` Debian package and the
`io.github.crhy.SpacedBazaar` system Flatpak in the live filesystem. Calamares
then copies both into the installed target, so SpacedBazaar is available before the
first-login Welcome window appears.

## License

Copyright 2026 Spaced Linux Team. Licensed under the GNU General Public License,
version 3 or (at your option) any later version. See `LICENSE`.
