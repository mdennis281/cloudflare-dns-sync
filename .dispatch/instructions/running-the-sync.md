# Running the sync

Use Python 3.11 (`py -3.11`). The pins in `requirements.txt` do not work on
3.12+: `urllib3==1.25.11` fails at import with
`No module named 'urllib3.packages.six.moves'`. Do not "fix" this by bumping
pins unless that is the actual task.

Always run from the repo root — `.venv/Scripts/python.exe main.py`. Never
`cd src` first. `src/config.py` calls `ConfigParser.read('config.ini')`, which
is resolved against the working directory, so a different cwd silently loads
no config and every setting falls back to its default (empty token → the
Cloudflare call fails with "Invalid request headers").

`config.ini` is not in the repo and there is no template — the sample that the
README describes was deleted in `ef5f0d1`. It goes at the repo root, holds a
live Cloudflare API token, and is gitignored. Never commit it, and never paste
its contents into a chat, a log, or a commit message.

The README is stale: it says `main.py`, `config.ini`, and `requirements.txt`
live in `src/`. They live at the repo root. Trust the code, not the README.

There are no tests and no test framework. Do not add a `test` command to
`.dispatch/project.yaml` that just fails.
