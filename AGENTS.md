# Agent instructions

## Project

This Home Assistant integration matches devices to NetBox inventory and exposes each matched device's asset tag and NetBox URL. It also includes optional sync and device-writing actions.

## Working in this repository

- Read `README.md` before changing matching or write behavior. Preserve the rule that conflicting candidate matches are ignored rather than guessed.
- Keep optional NetBox permissions and their related write actions aligned with the README.
- Before changing CI, check [pschmitt/ci-workflows](https://github.com/pschmitt/ci-workflows) for reusable components and preserve this repository's existing checks.

## Validation

- Run `uvx ruff check .` and `uvx ruff format --check .` for Python changes.
- CI runs Hassfest and the shared Ruff checks; it currently has no test job.
