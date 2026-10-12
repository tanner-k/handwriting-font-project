# Backup and restore

This repository preserves the project snapshot from October 12, 2026. All 117
project files were copied without changing their contents, including the Python
pipeline, Remotion source/configuration, npm lockfile, template PDF/HTML/layout,
83 glyph files (including the rectified handwriting sheet and manifest), both
font copies, source videos and captions, and `caption-app/out/captioned.mp4`.
The rendered video is deliberately tracked despite the existing `out` ignore rule.

The original README describes an earlier state: the snapshot already includes
the handwriting font, glyphs, an input test video, its captions, and a rendered
video. `BACKUP.md` records the backup's actual coverage and restoration steps.

## Restore the saved files

```sh
git clone https://github.com/tanner-k/handwriting-font-project.git
cd handwriting-font-project
```

The videos and fonts are ordinary Git files; no Git LFS or paid storage is needed.
`backup-manifest.json` records byte sizes, SHA-256 hashes, and executable status for
all original project files. Verify them without installing any dependencies:

```sh
python3 - <<'PY'
import hashlib
import json
from pathlib import Path

files = json.loads(Path('backup-manifest.json').read_text())['files']
for entry in files:
    path = Path(entry['path'])
    assert path.stat().st_size == entry['bytes'], path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256'], path
    assert bool(path.stat().st_mode & 0o100) == entry['executable'], path
print(f'Verified {len(files)} original project files.')
PY
```

## Recreate the development environment

The original Python environment used Python 3.13.12 on macOS ARM64.
`requirements.snapshot.txt` records its installed package versions; the original
`requirements.txt` remains unchanged. Install Python 3.13, then:

```sh
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.snapshot.txt
```

Install a Node.js version compatible with the packages in `caption-app/package-lock.json`
and npm, then recreate the JavaScript dependencies using the lockfile:

```sh
cd caption-app
npm ci
npm run dev
```

The supplied video, captions, and font are sufficient for previewing the saved
composition. Rendering can download Remotion's browser on first use:

```sh
npx remotion render CaptionedVideo out/new-captioned.mp4
```

For new transcriptions, `node sub.mjs public/your-video.mp4` uses the existing
installer to download/build Whisper.cpp 1.6.0 and its `base.en` model. On macOS,
install Xcode Command Line Tools if a compiler is missing. Network access is
needed to restore dependencies and downloads. Package availability and platform
compatibility can change; restoring or running the application was not tested
during this backup.

The omitted Whisper checkout was the unmodified upstream release commit
`08981d1bacbe494ff1c943af6c577c669a2d9f4d` at
<https://github.com/ggerganov/whisper.cpp>. The only non-ignored untracked file was
the downloaded model, `ggml-base.en.bin` (147,964,211 bytes; SHA-256
`a03779c86df3323075f5e796cb2ce5029f00ec8869eee3fdfb897afe36c6d002`).
Ignored items were compiler outputs and Finder metadata.

## Coverage and exclusions

The original folder occupied approximately 902 MiB on disk (945,737,728 bytes
reported by `du`). File payloads differ from allocated disk space:

| Category | File bytes | Disposition |
| --- | ---: | --- |
| Project source and assets | 31,436,603 | All 117 files preserved |
| `caption-app/node_modules` | 484,003,513 | Reinstall with `npm ci`; includes downloaded browser/cache |
| `.venv` | 208,245,687 | Recreate with Python and the requirements snapshot |
| `caption-app/whisper.cpp` | 173,785,754 | Re-download upstream release/model and rebuild |
| Finder `.DS_Store` files | 49,180 | Omitted machine metadata |

There was no project-level Git repository/history. The only nested repository was
the reproducible Whisper dependency. All 355 installed npm package versions and
integrities matched the saved npm lockfile. All 2,063 hash-bearing Python package
RECORD entries checked matched their installed files; the two extra site-package
files were standard virtualenv bootstrap files.

No credentials were found by filename and source-pattern checks. The input test
video, its rendered output, and handwriting assets are included in this
repository. No unique project files were intentionally omitted. The original
unrectified handwriting photograph was not in this folder; only assets present
in the folder are covered. The original local folder was left untouched.
