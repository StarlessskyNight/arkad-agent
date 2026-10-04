# Arkad uninstaller for Windows (PowerShell 5.1+). The Windows twin of scripts/uninstall.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/StarlessskyNight/arkad-agent/main/scripts/uninstall.ps1 | iex"
#
# Config/data is kept unless you pass -Purge:
#   & { $args = @('-Purge') }; irm ... | iex   (or run the script directly with -Purge)

& {
    param([switch]$Purge = $false)

    $InstallDir = if ($env:ARKAD_INSTALL_DIR) { $env:ARKAD_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'arkad-agent' }
    $BinDir     = if ($env:ARKAD_BIN_DIR)     { $env:ARKAD_BIN_DIR }     else { Join-Path $HOME '.local\bin' }

    $Shim = Join-Path $BinDir 'arkad.cmd'
    if (Test-Path $Shim) {
        Remove-Item -Force $Shim
        Write-Host "removed $Shim"
    }

    if (Test-Path $InstallDir) {
        Remove-Item -Recurse -Force $InstallDir
        Write-Host "removed $InstallDir"
    } else {
        Write-Host "no install found at $InstallDir"
    }

    if ($Purge) {
        foreach ($p in @((Join-Path $env:LOCALAPPDATA 'arkad-agent'), (Join-Path $HOME '.config\arkad-agent'), (Join-Path $HOME '.arkad'))) {
            if (Test-Path $p) { Remove-Item -Recurse -Force $p; Write-Host "purged $p" }
        }
    } else {
        Write-Host "kept config/data (rerun with -Purge to delete)"
    }

    Write-Host 'Arkad Agent uninstalled.'
} @args
