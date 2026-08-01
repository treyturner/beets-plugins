# Beets Plugins

This repository contains independently packaged plugins for [Beets](https://beets.io/), the music library manager. Each plugin has its own installation, configuration, and usage documentation.

## Plugins

### [beets-tidalv1](plugins/tidalv1/README.md)

Adds TIDAL v1 API sources to Beets' built-in `lyrics` and `fetchart` plugins. Notably, lyrics support is missing from TIDAL's v2 API consumed by the upstream [`tidal` plugin](https://beets.readthedocs.io/en/stable/plugins/tidal.html).

### [beets-nohirescd](plugins/nohirescd/README.md)

Prevents high-resolution audio from matching MusicBrainz CD releases during import, and can audit or reimport existing library violations.

## Development

Repository development and release documentation is available in
[DEVELOPMENT.md](DEVELOPMENT.md).
