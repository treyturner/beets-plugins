# beets-tidal-v1-meta

`tidalv1meta` adds TIDAL v1 sources to the built-in beets `lyrics` and `fetchart` plugins.

The lyrics endpoint used is the legacy v1 endpoint:

```text
GET https://api.tidal.com/v1/tracks/{track_id}/lyrics
```

TIDAL v2 does not currently expose the same lyrics payload.

## Install

```sh
python -m pip install git+https://github.com/treyturner/beets-tidal-v1-meta.git
```

## Configure beets

Enable this plugin before `lyrics` and `fetchart` so it registers before beets builds the source lists:

```yaml
plugins:
  - tidalv1meta
  - lyrics
  - fetchart

lyrics:
  sources:
    - tidalv1meta
    - lrclib

fetchart:
  sources:
    - filesystem
    - tidalv1meta
    - coverart

tidalv1meta:
  v1_client_id: YOUR_TIDAL_V1_APP_CLIENT_ID
  v1_client_secret: YOUR_TIDAL_V1_APP_CLIENT_SECRET
  country_code: US
  prefer_synced: yes
  art_size: 1280
  match_threshold: 0.78
```

A **legacy v1 client ID and secret** are required. If you have a credential pair in the same format used by `tiddl`, you can provide a Base64-encoded `<v1_client_id>;<v1_client_secret>` value instead:

```yaml
tidalv1meta:
  v1_client_id_secret_b64: BASE64_ENCODED_PAIR
```

If left empty, a best-effort attempt will be made to find it for you.

Run `beet tidalv1-auth` once to authorize a TIDAL account. The command stores a refreshable token cache at `~/.config/beets/tidalv1meta.json`.

## Usage

Fetch lyrics through the normal beets command:

```sh
beet lyrics artist:"Daft Punk"
```

Fetch album art through the normal fetchart command:

```sh
beet fetchart -f album:"Discovery"
```

During imports, the built-in `lyrics` and `fetchart` plugins handle automatic updates when their own `auto` settings are enabled.

## Development

Run tests:

```sh
pytest
mypy
```

Run a single module:

```sh
pytest tests/test_client.py
```
