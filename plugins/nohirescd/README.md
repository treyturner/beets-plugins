# beets-nohirescd

`nohirescd` prevents high-resolution source audio from being matched to a CD release during a beets album import.

If any source track exceeds the configured maximum bit depth or sample rate, the plugin removes candidates whose matched medium is CD. It filters both the initial candidate list and candidates returned by manual searches or entered IDs.

## Install

```sh
python -m pip install "beets-nohirescd @ git+https://github.com/treyturner/beets-plugins.git#subdirectory=plugins/nohirescd"
```

## Configure beets

Enable the plugin:

```yaml
plugins:
  - nohirescd
```

The defaults treat audio above 16-bit or 44.1 kHz as high resolution:

```yaml
nohirescd:
  max_bitdepth: 16
  max_samplerate: 44100
  cd_media_pattern: '(?:^|[^A-Za-z0-9])CD(?:-R)?(?:$|[^A-Za-z0-9])'
```

The default media pattern matches values such as `CD`, `Enhanced CD`, `8cm CD`, `SHM-CD`, and `CD-R`. It deliberately does not match `SACD`.

## Behavior

The plugin operates only on album import tasks. It checks every source item, and a single item above either configured limit activates filtering for the whole album.

Both album-level media and each mapped track's media are checked. This catches mixed-media releases, which beets may represent with the generic album-level value `Media` while retaining `CD` on individual mapped tracks.

After removing candidates, the plugin recalculates beets' recommendation. This prevents quiet mode from retaining a recommendation based on a removed CD candidate and produces no recommendation when no valid candidates remain.

## Development

```sh
uv sync
uv run pytest
uv run mypy
uv run pyright
```
