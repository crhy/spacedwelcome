SHELL := /bin/bash

VERSION := $(shell tr -d '[:space:]' < VERSION)
HOST_RUN ?= $(shell command -v flatpak-spawn >/dev/null 2>&1 && printf 'flatpak-spawn --host')

.PHONY: help check test deb clean

help:
	@printf '%s\n' 'make check  Run source and behavioral tests' 'make deb    Build the Debian package' 'make clean  Remove generated artifacts'

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: test
	python3 -m compileall -q src tests
	python3 -m json.tool data/catalog.json >/dev/null
	bash -n bin/spaced-welcome bin/spaced-welcome-install packaging/build-deb.sh packaging/debian/postinst packaging/debian/prerm
	desktop-file-validate data/spaced-welcome.desktop data/spaced-welcome-autostart.desktop
	@if command -v appstreamcli >/dev/null 2>&1; then appstreamcli validate --no-net data/io.github.crhy.SpacedWelcome.metainfo.xml; fi
	@if command -v shellcheck >/dev/null 2>&1; then shellcheck bin/* packaging/build-deb.sh packaging/debian/postinst packaging/debian/prerm; fi

deb:
	$(HOST_RUN) bash "$(CURDIR)/packaging/build-deb.sh"

clean:
	rm -f -- "dist/spaced-welcome_$(VERSION)_all.deb" dist/*.sha256
