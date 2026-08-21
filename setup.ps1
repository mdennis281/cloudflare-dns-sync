# Builds the venv, then hands off to install.py.
# Usage:  .\setup.ps1                    set up
#         .\setup.ps1 -Uninstall         tear down
#         .\setup.ps1 -Uninstall -Purge  tear down, no questions asked
[CmdletBinding()]
param(
	[switch]$Uninstall,
	[switch]$Purge
)

$ErrorActionPreference = 'Stop'

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Venv = Join-Path $Root '.venv'
$Py = Join-Path $Venv 'Scripts\python.exe'
$Installer = Join-Path $Root 'install.py'

function Find-Python {
	$candidates = @(
		@{ Exe = 'py'; Args = @('-3') },
		@{ Exe = 'python3'; Args = @() },
		@{ Exe = 'python'; Args = @() }
	)
	foreach ($candidate in $candidates) {
		$command = Get-Command $candidate.Exe -ErrorAction SilentlyContinue
		if (-not $command) { continue }
		$probe = @($candidate.Args) + @('-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)')
		& $command.Source @probe 2>$null
		if ($LASTEXITCODE -eq 0) {
			return @{ Exe = $command.Source; Args = @($candidate.Args) }
		}
	}
	throw 'Python 3.9+ is required but was not found on PATH.'
}

if ($Uninstall) {
	# [string[]] matters: a bare @('--purge') unrolls to a string, and splatting
	# a string passes it one character at a time.
	[string[]]$installerArgs = @($Installer, '--uninstall')
	if ($Purge) { $installerArgs += '--purge' }

	if (Test-Path $Py) {
		& $Py @installerArgs
	}
	else {
		Write-Host 'No venv found; removing the scheduled job with the system Python.'
		$system = Find-Python
		[string[]]$systemArgs = @($system.Args) + $installerArgs
		& $system.Exe @systemArgs
	}

	# Done last: install.py runs from inside the venv.
	if (Test-Path $Venv) {
		Remove-Item -Recurse -Force $Venv
		Write-Host '  removed .venv'
	}
	exit 0
}

if (-not (Test-Path $Py)) {
	Write-Host 'Creating virtual environment in .venv'
	$system = Find-Python
	[string[]]$venvArgs = @($system.Args) + @('-m', 'venv', $Venv)
	& $system.Exe @venvArgs
	if ($LASTEXITCODE -ne 0) { throw 'could not create the virtual environment' }
}

Write-Host 'Installing dependencies'
& $Py -m pip install --quiet --upgrade pip
& $Py -m pip install --quiet -r (Join-Path $Root 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'could not install dependencies' }
Write-Host ''

& $Py $Installer
exit $LASTEXITCODE
