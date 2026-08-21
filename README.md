# Cloudflare DNS External IP Synchronizer (Python)

This repository will synchronize Cloudflare DNS records with your current public IP address.

I created this as a solution to the annoyingly short DHCP leases handed out by my ISP. Personally, I use it to set A records on a few of my site's subdomains — allowing me to RDP into my machine by hostname, without having to worry about whether or not my external IP changed.

## Features
- Guided setup that verifies your API token before writing anything
- **Syncs as many records as you like**, across as many zones as you like, in one run
- IPv4 (`A`) and IPv6 (`AAAA`) records
- Creates records that don't exist yet, and leaves already-correct records alone
- A failure on one record doesn't stop the others
- Installs its own schedule (Task Scheduler or cron), and removes it again on uninstall
- Logging

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

Setup finishes by pointing you at `config.ini`, where you list the records you
want synced. That file is gitignored, so your token stays out of version control.

### Uninstall
```bash
./setup.sh --uninstall          # Linux / macOS
.\setup.ps1 -Uninstall          # Windows
```
This removes the scheduled job and the `.venv`, and asks before deleting
`config.ini` and any log files. Add `--purge` / `-Purge` to skip the questions.
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
cp config.example.ini config.ini   # then edit it
python main.py -v
```

Schedule it yourself with cron or Task Scheduler (see below), or let the
installer do just that part: `python install.py`.

## Configuration

Each record gets its own `[DNS:<record name>]` section. A plain `[DNS]` section supplies
the defaults every record inherits, so shared settings only need writing once.

```ini
[CloudFlare-API]
token = fJldweoEslakCwpLsaecCeroscorlaecp
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
```

### Record settings
| Key | Default | Meaning |
| --- | --- | --- |
| `recordType` | `A` | `A` for IPv4, `AAAA` for IPv6 |
| `proxied` | `False` | Route the record through Cloudflare's proxy |
| `ttl` | `1` | Seconds; `1` means automatic. Forced to `1` when `proxied` is on |
| `zone` | `siteName` | Which zone this record lives in |
| `createRecord` | `True` | Create the record if it doesn't exist yet |

### General settings
| Key | Default | Meaning |
| --- | --- | --- |
| `loggingEnabled` | `True` | Write to the log file and stdout. `False` runs silently |
| `logPath` | `CF-DNS.log` | Relative paths resolve against the config file's directory |
| `logLevel` | `2` | `1` errors, `2` info, `3` debug |

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
