# ADR-0001: Runtime environment (WSL2, uv, Python 3.12, CLI entrypoint)

**Status:** accepted

## Context
The development machine runs Windows 11 with no make and no Java. CI runs on Linux (GitHub Actions `ubuntu-latest`). The machine already has Python 3.14 (system Python in WSL Ubuntu 26.04).

## Options
1. Native Windows, with a Python CLI as the only entrypoint and Synthea run in a Java container.
2. **WSL2 Ubuntu**, with the repo in the Linux filesystem.
3. Native Windows with make installed through a Windows package manager.

## Decision
Option 2. Development matches CI (same OS family, same shell, same Makefile), and make and Java come from apt. The repo lives under `~/projects`, not `/mnt/c`, because cross-filesystem I/O through WSL is several times slower.

**Python 3.14, the existing system interpreter**, pinned in `.python-version` and `requires-python`. The first draft of this plan assumed 3.14 was too new, and that assumption was **checked instead of acted on** (2026-10-08). The full planned dependency set (dbt-core, dbt-postgres, sentence-transformers, CPU torch, bm25s, anthropic, psycopg and the rest) resolves to prebuilt wheels on 3.14 with `uv pip compile --only-binary :all:`, and dbt-core 1.12 declares 3.14 support in its classifiers. There was no reason to install a second interpreter.

uv still manages the project's virtualenv and lockfile. It uses `/usr/bin/python3.14` locally, and CI gets 3.14 from uv.

**Entrypoint:** a typer CLI (`rwe`). It is the real interface. The Makefile is a thin wrapper for convention, so the pipeline logic is never split between Make and Python.

## Consequences
- Contributors on Windows need WSL2. On macOS or Linux it runs natively.
- `pyproject.toml` declares lower bounds. `uv.lock` pins exact versions, and CI installs with `--frozen`, so it fails if the lock is stale instead of silently resolving new versions.
