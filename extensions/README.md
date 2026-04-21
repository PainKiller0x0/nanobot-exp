# Extensions

This directory contains optional add-ons that are intentionally kept outside nanobot core.

## Enable extensions

Set `NANOBOT_EXTENSION_MODULES` to a comma-separated module list.

Example:

```bash
export NANOBOT_EXTENSION_MODULES=extensions.reflexio
```

When unset, nanobot core runs without loading any external extension logic.
## Provider failover plugin

To enable provider-side 529 failover:

`ash
export NANOBOT_PROVIDER_FAILOVER_MODULE=extensions.provider_failover
`

It reads existing failover settings from NANOBOT_FAILOVER_SETTINGS_URL and related NANOBOT_FALLBACK_* env vars.
