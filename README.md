# Cloudflare DNS External IP Synchronizer (Python)

This repository will synchronize Cloudflare DNS records with your current public IP address.

I created this as a solution to the annoyingly short DHCP leases handed out by my ISP. Personally, I use it to set A records on a few of my site's subdomains — allowing me to RDP into my machine by hostname, without having to worry about whether or not my external IP changed.

## Features
- Guided setup that verifies your API token before writing anything
- API token kept in `.env`, separate from the record config
- **Syncs as many records as you like**, across as many zones as you like, in one run
- IPv4 (`A`) and IPv6 (`AAAA`) records
- Creates records that don't exist yet, and leaves already-correct records alone
- A failure on one record doesn't stop the others
- Installs its own schedule (Task Scheduler or cron), and removes it again on uninstall
- Logging, with rotation that holds up when two runs overlap — same on Linux and Windows,
  no `logrotate` to configure

## Quick start

Grab the repo, then run the setup script for your platform. It builds a virtual
environment, installs the dependencies into it, asks for your Cloudflare API
token, checks the token actually works, and offers to schedule the sync.

**Linux / macOS**
```bash
git clone https://github.com/mdennis281/cloudflare-dns-sync.git
cd cloudflare-dns-sync
chmod +x setup.sh
./setup.sh
```

**Windows (PowerShell)**
```powershell
git clone https://github.com/mdennis281/cloudflare-dns-sync.git
cd cloudflare-dns-sync
.\setup.ps1
```
> If PowerShell blocks the script, either run
> `powershell -ExecutionPolicy Bypass -File .\setup.ps1`, or unblock it once with
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

You'll need an API token first — create one at
https://dash.cloudflare.com/profile/api-tokens with these two permissions:

*    Zone   Zone   Read
*    Zone   DNS    Edit

Setup writes the token to `.env` and points you at `config.ini`, where you list
the records you want synced. Both files are gitignored.

### Uninstall
```bash
./setup.sh --uninstall          # Linux / macOS
.\setup.ps1 -Uninstall          # Windows
```
This removes the scheduled job and the `.venv`, and asks before deleting `.env`,
`config.ini`, and any log files. Add `--purge` / `-Purge` to skip the questions.
It does **not** revoke your API token — do that in the Cloudflare dashboard.

Everything lives inside the project directory, so if you'd rather remove it by
hand: delete the scheduled job (`CloudflareDNSSync` in Task Scheduler, or the
`# cf-dns-sync` line in `crontab -e`) and delete the folder.

## Manual setup

If you'd rather not run the setup script, a virtual environment is still the
recommended way to install this — it keeps these dependencies off your system
Python.

```bash
python3 -m venv .venv
. .venv/bin/activate           # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env               # then paste in your API token
cp config.example.ini config.ini   # then list your records
python main.py -v
```

Schedule it yourself with cron or Task Scheduler (see below), or let the
installer do just that part: `python install.py`.

## The API token

The token lives in `.env`, not in `config.ini`:

```dotenv
CLOUDFLARE_API_TOKEN=fJldweoEslakCwpLsaecCeroscorlaecp
```

It's looked for in this order:

1. An exported `CLOUDFLARE_API_TOKEN` environment variable — handy for systemd
   units, containers, or CI, which can inject one without a file on disk.
2. `.env` next to `config.ini`, then `.env` in the project root.
3. `[CloudFlare-API] token` in `config.ini`. This is the pre-2.1 location and
   still works, but it logs a warning telling you to move it.

`CLOUDFLARE_API_TOKEN` is the same variable name Wrangler and the Cloudflare
Terraform provider use, so an already-exported token works with no setup.

> Cron and Task Scheduler don't inherit your shell's environment, so for
> scheduled runs the token needs to be in `.env` (or exported by whatever
> supervises the job) — not just `export`ed in your `.bashrc`.

## Configuration

Each record gets its own `[DNS:<record name>]` section. A plain `[DNS]` section supplies
the defaults every record inherits, so shared settings only need writing once.

```ini
[CloudFlare-API]
; the token goes in .env, not here
; default zone for every record below
siteName = mydomain.com

[DNS:home.mydomain.com]

[DNS:vpn.mydomain.com]
proxied = True

; an AAAA record — the public IPv6 address is looked up separately
[DNS:home6.mydomain.com]
recordType = AAAA

; a record in a different zone on the same account
[DNS:nas.otherdomain.com]
zone = otherdomain.com

; every A record under test.mydomain.com, however many there are
[DNS:*.test.mydomain.com]

; defaults inherited by all of the above
[DNS]
recordType = A
proxied = False
createRecord = True
ttl = 1

[general]
loggingEnabled = True
logPath = CF-DNS.log
logLevel = 2
logRotation = size
logMaxSize = 1MB
logBackups = 5
```

### Record settings
| Key | Default | Meaning |
| --- | --- | --- |
| `recordType` | `A` | `A` for IPv4, `AAAA` for IPv6 |
| `proxied` | `False` | Route the record through Cloudflare's proxy |
| `ttl` | `1` | Seconds; `1` means automatic. Forced to `1` when `proxied` is on |
| `zone` | `siteName` | Which zone this record lives in |
| `createRecord` | `True` | Create the record if it doesn't exist yet |

### Wildcards

A name containing `*` is a pattern rather than a hostname. Every existing record of
the same type whose name matches is pointed at your public IP, so one section can
cover a whole subtree:

```ini
[DNS:*.test.mydomain.com]
[DNS:*.lanscape.app]
zone = lanscape.app
```

`*` spans any number of labels, so `*.test.mydomain.com` covers
`app.test.mydomain.com` and `one.two.test.mydomain.com` alike — plus the Cloudflare
wildcard record `*.test.mydomain.com` itself, if the zone has one. `*` can also sit
inside a label: `[DNS:dev-*.mydomain.com]`.

Matching is case-insensitive, and the pattern has to end with its own zone —
`[DNS:*]` is rejected rather than quietly claiming everything.

- Matched records **keep their own `proxied` and `ttl`**; only the IP is rewritten.
  Those keys apply to a record this tool creates itself.
- `createRecord` has something to create only when nothing matched *and* the pattern
  is a real Cloudflare wildcard (`*.` as the leftmost label). A pattern that matches
  nothing else is a logged no-op.
- A wildcard claims **every** matching `A`/`AAAA` record in the zone, including any
  you deliberately pointed elsewhere.

### General settings
| Key | Default | Meaning |
| --- | --- | --- |
| `loggingEnabled` | `True` | Write to the log file and stdout. `False` runs silently |
| `logPath` | `CF-DNS.log` | Relative paths resolve against the config file's directory |
| `logLevel` | `2` | `1` errors, `2` info, `3` debug |
| `logRotation` | `size` | `size`, `daily`, or `off` |
| `logMaxSize` | `1MB` | `size` rotation only. Bytes, or a suffix: `512KB`, `5MB`, `1GB` |
| `logBackups` | `5` | Old logs to keep. `0` discards the old log instead of keeping it |

### Log rotation

Rotation is handled in-process, identically on both platforms — there's no
`logrotate` unit to write on Linux and nothing extra to install on Windows.

`logRotation = size` (the default) keeps the live log under `logMaxSize` and
shifts the old ones down, so `.1` is always the most recent:

```
CF-DNS.log      CF-DNS.log.1      CF-DNS.log.2   ...   CF-DNS.log.5
```

`logRotation = daily` starts a fresh file on the first run of a new day and
names the archive after the day it covers:

```
CF-DNS.log      CF-DNS.log.2026-08-20      CF-DNS.log.2026-08-19
```

Either way `logBackups` old files are kept and the rest are deleted, so the
worst case is bounded: `size` costs at most `logMaxSize × (logBackups + 1)`.
`logRotation = off` disables rotation and lets the file grow forever.

Because the sync is scheduled, a slow run and the next one can overlap and
both write the same file. Rotation is decided while holding an exclusive lock
on a `CF-DNS.log.lock` file beside the log, and re-checked against what's
actually on disk, so two runs can't both rotate the same file — and neither
ends up appending to a file that has already been rotated away. That last part
is the one that bites on Windows, where the rename fails outright if anyone
else has the file open. The lock file is created automatically and cleaned up
by `--uninstall`.

### Where config.ini is looked for
In order: `--config <path>`, the `CF_DNS_CONFIG` environment variable, the project root
(next to `main.py`), then the current working directory.

## Command line
```
python main.py [-c CONFIG] [-v]

  -c, --config   path to config.ini
  -v, --verbose  log debug output to stdout
```
Exit codes: `0` all records in sync, `1` one or more records failed, `2` bad config.

If something isn't working, run `python main.py -v` for debug output, or check
the log file you specified in the ini.

## Scheduling it yourself

The setup script does this for you, but if you'd rather wire it up by hand:

**Windows / Task Scheduler.** Point a task at the venv's `pythonw.exe` (not
`python.exe` — `pythonw` avoids a console window flashing on every run):
```
"C:\path\to\project\.venv\Scripts\pythonw.exe" "C:\path\to\project\main.py"
```
Be sure to use FULL paths; a relative path will not work from Task Scheduler.
Here's some screenshots of my configuration (runs every 10 minutes):

> [General Tab](http://bit.ly/2nvvIe1)

> [Triggers > New](http://bit.ly/2nvyLTv)

> [Actions](http://bit.ly/2lXrcEE)

**Linux / cron.** Run `crontab -e` and add:
```cron
*/10 * * * * /path/to/project/.venv/bin/python /path/to/project/main.py
```
>Note: If you don't know how to format a cron job, use this: https://crontab-generator.org/

## Development
```bash
pip install -r requirements-dev.txt
pytest
```
Requires Python 3.9 or newer. Tested against 3.11 and 3.13.

## License
MIT — see [LICENSE](LICENSE).
