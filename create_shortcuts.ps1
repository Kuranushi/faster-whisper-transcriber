param(
    [Parameter(Mandatory = $true)]
    [string]$Root
)

$ErrorActionPreference = "Stop"

$pywExe     = Join-Path $Root "python\pythonw.exe"
$scriptPath = Join-Path $Root "transcribe_ui.py"
$icon       = Join-Path $Root "icon.ico"
$name       = "Launch Faster-Whisper Transcriber"

if (-not (Test-Path $pywExe)) {
    Write-Host "ERROR: pythonw.exe not found under '$Root'. Run Setup.bat first."
    exit 1
}

try {
    # Shortcut is created INSIDE the project folder only - never on the
    # Desktop or in the Start Menu. The user decides where it goes from
    # here (copy it, pin it, drag it - all optional, all manual).
    $target = Join-Path $Root "$name.lnk"

    $ws = New-Object -ComObject WScript.Shell
    $shortcut = $ws.CreateShortcut($target)
    $shortcut.TargetPath       = $pywExe
    $shortcut.Arguments        = '"' + $scriptPath + '"'
    $shortcut.WorkingDirectory = $Root
    if (Test-Path $icon) {
        $shortcut.IconLocation = $icon
    }
    $shortcut.Save()

    Write-Host "Shortcut created: $target"
    exit 0
}
catch {
    Write-Host "ERROR: Failed to create shortcut: $($_.Exception.Message)"
    exit 1
}
