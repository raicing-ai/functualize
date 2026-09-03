<#
.SYNOPSIS
    Install the functualize standalone binary on Windows.

.DESCRIPTION
    irm https://raw.githubusercontent.com/raicing-ai/functualize/master/install.ps1 | iex

    Downloads the archive matching this machine's architecture, verifies it
    against the published checksum, and places `func.exe` on PATH.

    Shipped because uv ships both scripts and Hatch ships neither, and is
    measurably harder to install on Windows for it. There is no libc branch
    here: Windows has one ABI for this purpose, and the musl question is a
    Linux question.
#>

[CmdletBinding()]
param(
    [string]$Version = $(if ($env:FUNCTUALIZE_VERSION) { $env:FUNCTUALIZE_VERSION } else { "latest" }),
    [string]$Repo = $(if ($env:FUNCTUALIZE_REPO) { $env:FUNCTUALIZE_REPO } else { "raicing-ai/functualize" }),
    [string]$InstallDir = $(if ($env:FUNCTUALIZE_INSTALL_DIR) { $env:FUNCTUALIZE_INSTALL_DIR } else { "$env:LOCALAPPDATA\functualize\bin" })
)

$ErrorActionPreference = "Stop"

function Get-Target {
    switch ($env:PROCESSOR_ARCHITECTURE) {
        "AMD64" { return "x86_64-pc-windows-msvc" }
        "ARM64" {
            # No aarch64 Windows artifact is published yet. The x86_64 build
            # runs under emulation, and saying so is better than failing with
            # a 404 the user cannot interpret.
            Write-Host "note: no native ARM64 build yet; using the x86_64 binary under emulation."
            return "x86_64-pc-windows-msvc"
        }
        default { throw "unsupported architecture: $env:PROCESSOR_ARCHITECTURE" }
    }
}

$target = Get-Target
$archive = "functualize-$target.zip"
$base = if ($Version -eq "latest") {
    "https://github.com/$Repo/releases/latest/download"
} else {
    "https://github.com/$Repo/releases/download/$Version"
}

Write-Host "platform: $target"

$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ([System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

try {
    Write-Host "downloading $archive"
    Invoke-WebRequest -Uri "$base/$archive" -OutFile "$tmp\$archive" -UseBasicParsing
    Invoke-WebRequest -Uri "$base/SHA256SUMS" -OutFile "$tmp\SHA256SUMS" -UseBasicParsing

    # Verified before extraction, never after: a substituted archive must not
    # reach the filesystem as an executable even briefly.
    $expected = (Get-Content "$tmp\SHA256SUMS" |
        Where-Object { $_ -match [regex]::Escape($archive) + '\s*$' } |
        Select-Object -First 1) -split '\s+' | Select-Object -First 1
    if (-not $expected) { throw "no checksum published for $archive" }

    $actual = (Get-FileHash "$tmp\$archive" -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $expected.ToLower()) {
        throw "checksum mismatch for ${archive}: expected $expected, got $actual"
    }
    Write-Host "checksum ok"

    Expand-Archive -Path "$tmp\$archive" -DestinationPath $tmp -Force
    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    Move-Item -Path "$tmp\func.exe" -Destination "$InstallDir\func.exe" -Force

    Write-Host "installed to $InstallDir\func.exe"

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$InstallDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$InstallDir", "User")
        Write-Host "added $InstallDir to your user PATH -- open a new terminal to pick it up."
    }

    Write-Host ""
    Write-Host "Run 'func builtin self doctor' to check the installation."
}
finally {
    Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
}
