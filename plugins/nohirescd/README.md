# beets-nohirescd

`nohirescd` prevents high-resolution source audio from being matched to a CD release during a beets album import. It can also audit a library for existing matches that violate the same rule and send those albums through beets' normal reimport workflow.

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
  cd_media_pattern: '(?:^|[^A-Za-z0-9])(?:HDCD|HQCD|CD(?:-R)?)(?:$|[^A-Za-z0-9])'
```

The default media pattern matches values such as `CD`, `Enhanced CD`, `8cm CD`, `SHM-CD`, `HDCD`, `HQCD`, and `CD-R`. It deliberately does not match `SACD`.

## Import behavior

On album import tasks, every source item is checked. A single item above either configured limit activates filtering for the whole album.

Both album-level media and each mapped track's media are checked. This catches mixed-media releases, which beets may represent with the generic album-level value `Media` while retaining `CD` on individual mapped tracks.

After removing candidates, the plugin recalculates beets' recommendation. This prevents quiet mode from retaining a recommendation based on a removed CD candidate and produces no recommendation when no valid candidates remain.

## Audit existing albums

Run the command without a query to audit every album in the library:

```sh
beet nohirescd
```

The concise console report contains one line per violating album followed by album and track totals. An existing album is a violation when any of its tracks exceeds either configured resolution limit and any of its tracks has stored media matching `cd_media_pattern`. These may be different tracks on a mixed-media release. Singleton items are not included.

Standard beets album queries restrict the audit:

```sh
beet nohirescd albumartist:"Beyoncé"
```

The audit reads metadata already stored in the beets library and does not query MusicBrainz.

### CSV report

Use `-o` or `--output` to write a detailed UTF-8 CSV while retaining the concise console report:

```sh
beet nohirescd --output nohirescd-audit.csv
```

The output contains one row per violating album and overwrites an existing file at the specified path. Its columns are:

- `album_id`, `mb_albumid`, `albumartist`, and `album`
- `path` and `track_count`
- `max_bitdepth` and `max_samplerate`
- `media`, containing the album's distinct stored track media
- `hires_tracks` and `cd_tracks`, containing semicolon-separated track details that show why the album was flagged

No report file is created unless `--output` is supplied.

### Reimport violations

Use `--reimport` to pass the violating albums directly to beets' library reimport pipeline instead of producing an audit report:

```sh
beet nohirescd --reimport
beet nohirescd --reimport year:1990..1999
```

The command preserves the normal `import` configuration and prompts, except that it always runs this album-only audit's results through album import mode. Any configured singleton mode is restored when the command finishes. Because the `nohirescd` candidate filter must run during reimport, `import.autotag` must be enabled. Depending on the beets import configuration and choices made during the session, reimporting can update library metadata and files. `--reimport` cannot be combined with `--output`.

## Development

```sh
uv sync
uv run pytest
uv run mypy
uv run pyright
```
