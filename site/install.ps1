# Install YTKTV and/or YTKTV Desk on Windows from the latest GitHub release.
#
#   irm https://tonyd365.github.io/YTKTV/install.ps1 | iex
#
# With options (YTKTV is -Room, YTKTV Desk is -Desk; -Yes accepts the license without asking):
#
#   & ([scriptblock]::Create((irm https://tonyd365.github.io/YTKTV/install.ps1))) -Room -Desk -Yes
#
# In a console it is interactive: tick YTKTV, YTKTV Desk or both with the arrow keys and
# space, read and accept the license, then it downloads the installers, checks them against
# SHA256SUMS and installs them silently for the current user. Same pages as the installers
# (packaging/installer/). winget install TonyD365.YTKTV still works too.
#
# In a console it first runs the full-screen installer program from the release
# (installer/, built with Ink like Claude Code's CLI), checked against SHA256SUMS. When the
# release has none yet, or with -Plain, this script does the same itself.
#
# This file is plain ASCII on purpose: the symbols are made from code points, so it reads
# the same whatever encoding the download is decoded with.

param([switch]$Room, [switch]$Desk, [switch]$Yes, [switch]$Plain, [switch]$Help)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'  # Invoke-WebRequest's own bar is very slow on 5.1
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$Repo = 'TonyD365/YTKTV'
if ($Help) { Get-Content $PSCommandPath -TotalCount 20 -ErrorAction SilentlyContinue; return }

function Sym([int]$code) { [string][char]$code }
$Tick = Sym 0x2713; $Cross = Sym 0x2717; $Pointer = Sym 0x203A
$On = Sym 0x25CF; $Off = Sym 0x25CB
$H = Sym 0x2500; $V = Sym 0x2502
$TL = Sym 0x250C; $TR = Sym 0x2510; $BL = Sym 0x2514; $BR = Sym 0x2518

# Interactive only in a real console that can read keys.
$Tui = $false
if (-not $Yes) {
    try { $Tui = -not [Console]::IsInputRedirected -and [Console]::WindowWidth -gt 0 } catch { $Tui = $false }
}

function Say([string]$text) { Write-Host '==> ' -ForegroundColor Magenta -NoNewline; Write-Host $text }
function Ok([string]$text) { Write-Host "  $Tick " -ForegroundColor Green -NoNewline; Write-Host $text }
function Fail([string]$text) {
    try { [Console]::CursorVisible = $true } catch { }
    Write-Host "  $Cross Error: " -ForegroundColor Red -NoNewline; Write-Host $text
    throw 'YTKTV install stopped.'
}

function Box([string[]]$lines) {
    $width = 40
    foreach ($line in $lines) { if ($line.Length -gt $width) { $width = $line.Length } }
    $bar = $H * ($width + 4)
    Write-Host "  $TL$bar$TR" -ForegroundColor Magenta
    $first = $true
    foreach ($line in $lines) {
        Write-Host "  $V  " -ForegroundColor Magenta -NoNewline
        if ($first) { Write-Host $line.PadRight($width) -ForegroundColor White -NoNewline }
        else { Write-Host $line.PadRight($width) -ForegroundColor DarkGray -NoNewline }
        Write-Host "  $V" -ForegroundColor Magenta
        $first = $false
    }
    Write-Host "  $BL$bar$BR" -ForegroundColor Magenta
}

# Draws a list of "label|hint" items and lets the arrow keys move; returns the index chosen.
# With $ticks it is a checklist (space ticks) and returns the ticked flags instead.
function Choose([string]$question, [string[]]$items, [bool[]]$ticks = $null) {
    $selected = 0
    $help = if ($ticks) { 'Up/Down to move - Space to tick - Enter to go on - Q to quit' }
            else { 'Up/Down to move - Enter to choose - Q to quit' }
    Write-Host ''
    Write-Host "  $question" -ForegroundColor White
    [Console]::CursorVisible = $false
    # Make room first, so the console scrolling does not move the menu while it is drawn.
    for ($i = 0; $i -lt $items.Count + 2; $i++) { Write-Host '' }
    $top = [Console]::CursorTop - ($items.Count + 2)
    while ($true) {
        [Console]::SetCursorPosition(0, $top)
        for ($i = 0; $i -lt $items.Count; $i++) {
            $label, $hint = $items[$i].Split('|', 2)
            $mark = ''
            if ($ticks) { $mark = if ($ticks[$i]) { "$On " } else { "$Off " } }
            $line = if ($i -eq $selected) { "  $Pointer $mark" } else { "    $mark" }
            Write-Host $line -ForegroundColor $(if ($i -eq $selected) { 'Magenta' } else { 'Gray' }) -NoNewline
            Write-Host $label.PadRight(13) -ForegroundColor $(if ($i -eq $selected) { 'White' } else { 'Gray' }) -NoNewline
            Write-Host (' ' + $hint).PadRight(40) -ForegroundColor DarkGray
        }
        Write-Host ''
        Write-Host "  $help" -ForegroundColor DarkGray
        $key = [Console]::ReadKey($true)
        switch ($key.Key) {
            'UpArrow' { $selected = ($selected + $items.Count - 1) % $items.Count }
            'DownArrow' { $selected = ($selected + 1) % $items.Count }
            'K' { $selected = ($selected + $items.Count - 1) % $items.Count }
            'J' { $selected = ($selected + 1) % $items.Count }
            'Spacebar' { if ($ticks) { $ticks[$selected] = -not $ticks[$selected] } }
            'Enter' {
                [Console]::CursorVisible = $true
                if (-not $ticks) { return $selected }
                if ($ticks -contains $true) { return , $ticks }
            }
            'Q' { Write-Host ''; Fail 'Cancelled, nothing was installed.' }
            'Escape' { Write-Host ''; Fail 'Cancelled, nothing was installed.' }
        }
    }
}

function Page([string]$path) {
    foreach ($ref in @($script:Tag, 'main')) {
        if (-not $ref) { continue }
        try { return (Invoke-WebRequest -UseBasicParsing "https://raw.githubusercontent.com/$Repo/$ref/$path").Content }
        catch { }
    }
    return ''
}
function Show([string]$path) {
    $first = $true
    foreach ($line in ((Page $path) -split "`r?`n")) {
        if ($first) { Write-Host "  $line" -ForegroundColor Cyan; $first = $false }
        else { Write-Host "  $line" }
    }
}

function Hash-Of([string]$path) {
    $sha = [Security.Cryptography.SHA256]::Create()
    $stream = [IO.File]::OpenRead($path)
    try { return ([BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLower() }
    finally { $stream.Dispose(); $sha.Dispose() }
}

# The installer program: download it, check it, unpack it and run it. $false when there is none.
function Run-Program {
    $base = if ($env:YTKTV_INSTALLER_BASE) { $env:YTKTV_INSTALLER_BASE } else { "https://github.com/$Repo/releases/latest/download" }
    $name = 'ytktv-installer-windows-x64.exe.gz'  # Windows on ARM runs it emulated
    $work = Join-Path ([IO.Path]::GetTempPath()) ("ytktv-installer-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        $gz = Join-Path $work $name
        try {
            (New-Object Net.WebClient).DownloadFile("$base/$name", $gz)
            $sums = (New-Object Net.WebClient).DownloadString("$base/SHA256SUMS")
        } catch { return $false }
        $line = ($sums -split "`n") | Where-Object { $_ -match "\s\*?$([regex]::Escape($name))\s*$" } | Select-Object -First 1
        if (-not $line -or (Hash-Of $gz) -ne ($line -split '\s+')[0].ToLower()) { return $false }
        $exe = Join-Path $work 'ytktv-installer.exe'
        $in = [IO.File]::OpenRead($gz)
        $out = [IO.File]::Create($exe)
        try {
            $unzip = New-Object IO.Compression.GZipStream($in, [IO.Compression.CompressionMode]::Decompress)
            $unzip.CopyTo($out)
            $unzip.Dispose()
        } finally { $out.Dispose(); $in.Dispose() }
        $arguments = @()
        if ($Room) { $arguments += '--room' }
        if ($Desk) { $arguments += '--desk' }
        & $exe @arguments
        $script:ProgramExit = $LASTEXITCODE
        return $true
    } finally {
        Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }
}

function Install-YTKTV {
    # --- What to install -------------------------------------------------------------
    $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') { 'arm64' } else { 'x64' }
    Say 'Looking up the latest release...'
    try { $release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest" }
    catch { Fail 'Could not reach GitHub. Check the internet connection and try again.' }
    $script:Tag = $release.tag_name

    if ($Tui) { Write-Host ''; Box @('YTKTV Installer', "$($script:Tag) for Windows ($arch)") }
    $apps = @()
    if ($Room) { $apps += 'YTKTV' }
    if ($Desk) { $apps += 'YTKTV-Desk' }
    if (-not $apps) {
        if ($Tui) {
            $ticked = Choose 'What do you want to install?' @('YTKTV|for a karaoke room', 'YTKTV Desk|for the front desk') @($true, $false)
            if ($ticked[0]) { $apps += 'YTKTV' }
            if ($ticked[1]) { $apps += 'YTKTV-Desk' }
        } else { $apps = @('YTKTV') }
    }
    $names = if ($apps.Count -gt 1) { 'YTKTV and YTKTV Desk' } else { $apps[0] -replace '-', ' ' }

    # The asset whose name is APP-<version>-windows-<arch>-setup.exe (YTKTV must not match YTKTV-Desk).
    $assets = @{}
    foreach ($app in $apps) {
        $asset = $release.assets | Where-Object { $_.name -match "^$([regex]::Escape($app))-\d[^-]*-windows-$arch-setup\.exe$" } | Select-Object -First 1
        if (-not $asset) { Fail "The latest release has no $($app -replace '-', ' ') installer for this computer yet. Try again in a while." }
        $assets[$app] = $asset
    }

    # --- Welcome and license ---------------------------------------------------------
    foreach ($app in $apps) {
        Write-Host ''
        Show "packaging/installer/$(if ($app -eq 'YTKTV-Desk') { 'desk' } else { 'ytktv' })-welcome.txt"
    }
    if (-not $Yes) {
        if (-not $Tui) { Fail "Cannot ask you to accept the license here. Read it at https://github.com/$Repo/blob/main/LICENSE and run again with -Yes." }
        while ($true) {
            $choice = Choose 'Do you accept the YTKTV License?' @("Accept|and install $names", 'View|read the license', 'Cancel|install nothing')
            if ($choice -eq 0) { break }
            if ($choice -eq 2) { Write-Host ''; Fail 'You did not accept the license, so nothing was installed.' }
            Write-Host ''
            (Page 'LICENSE') -split "`r?`n" | Out-Host -Paging
        }
    }
    Write-Host ''
    Ok 'License accepted'

    # --- Download and install --------------------------------------------------------
    $sums = ''
    $sumsAsset = $release.assets | Where-Object { $_.name -eq 'SHA256SUMS' } | Select-Object -First 1
    if ($sumsAsset) {
        try {
            $content = (Invoke-WebRequest -UseBasicParsing $sumsAsset.browser_download_url).Content
            $sums = if ($content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($content) } else { [string]$content }
        } catch { }
    }
    $work = Join-Path ([IO.Path]::GetTempPath()) ("ytktv-install-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $work | Out-Null
    try {
        foreach ($app in $apps) {
            $asset = $assets[$app]; $label = $app -replace '-', ' '
            $file = Join-Path $work $asset.name
            Write-Host ''
            Say "${label}: downloading $($asset.name) ($([math]::Round($asset.size / 1MB)) MB)..."
            try { (New-Object Net.WebClient).DownloadFile($asset.browser_download_url, $file) }
            catch { Fail 'The download failed. Please try again.' }
            Ok 'Downloaded'
            $line = ($sums -split "`n") | Where-Object { $_ -match "\s\*?$([regex]::Escape($asset.name))\s*$" } | Select-Object -First 1
            if ($line) {
                Say 'Checking the download...'
                if ((Hash-Of $file) -ne ($line -split '\s+')[0].ToLower()) { Fail 'The download is damaged (checksum mismatch). Please try again.' }
                Ok 'Checksum OK'
            }
            Say "Installing $label..."
            $process = Start-Process -FilePath $file -Wait -PassThru `
                -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER'
            if ($process.ExitCode -ne 0) { Fail "The installer stopped with code $($process.ExitCode)." }
            Ok "Installed $label $($script:Tag)"
        }
    } finally {
        Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
    }

    foreach ($app in $apps) {
        Write-Host ''
        Show "packaging/installer/$(if ($app -eq 'YTKTV-Desk') { 'desk' } else { 'ytktv' })-done.txt"
    }
    Write-Host ''
}

if ($Tui -and -not $Plain -and (Run-Program)) { return }
try { Install-YTKTV } catch { if ($_.Exception.Message -ne 'YTKTV install stopped.') { throw } }
