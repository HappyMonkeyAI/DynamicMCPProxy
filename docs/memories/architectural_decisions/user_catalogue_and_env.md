# Architectural Decision: user.catalogue.json + .env

**Date:** 2026-03-20
**Status:** Active

## Context
The public `catalogue.json` contains generic community MCP servers. Users have personal servers (local paths, private APIs, custom tools) that must not be committed to the public repo. API keys for both public and private servers also must not be committed.

## Decision
- `user.catalogue.json`: Private catalogue overlay, gitignored. Merged at load time, user entries win on name collision. Populated from the user's existing IDE MCP config.
- `.env`: Gitignored. Loaded via `python-dotenv` with `override=False`. Contains blanked template keys for all catalogue `env_vars` plus pre-filled values from the user's existing setup.

## Tradeoffs
- Pro: Clean separation of public/private — repo stays shareable
- Pro: `override=False` means CI/production env vars always take precedence over the file
- Con: `user.catalogue.json` must be manually maintained when the user's IDE config changes (no auto-sync yet)
- Future: A `scripts/sync_user_catalogue.py` could auto-generate from the IDE's mcp_config.json
