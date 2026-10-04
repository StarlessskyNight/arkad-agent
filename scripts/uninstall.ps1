# Arkad uninstaller for Windows (PowerShell 5.1+). Removes everything:
# install dir, command shims, config/data, and the PATH entry we added.
#
#   powershell -ExecutionPolicy ByPass -c "irm https://raw.githubusercontent.com/StarlessskyNight/arkad-agent/main/scripts/uninstall.ps1 | iex"

& {
    $InstallDir = if ($env:ARKAD_INSTALL_DIR) { $env:ARKAD_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA 'arkad-agent' }
    $BinDir     = if ($env:ARKAD_BIN_DIR)     { $env:ARKAD_BIN_DIR }     else { Join-Path $HOME '.local\bin' }

    # 1. Remove command shims.
    foreach ($name in 'arkad.cmd', 'arkad-agent.cmd') {
        $Shim = Join-Path $BinDir $name
        if (Test-Path $Shim) {
            Remove-Item -Force $Shim
            Write-Host "removed $Shim"
        }
    }

    # 2. Remove install dir.
    if (Test-Path $InstallDir) {
        Remove-Item -Recurse -Force $InstallDir
        Write-Host "removed $InstallDir"
    } else {
        Write-Host "no install found at $InstallDir"
    }

    # 3. Remove config/data everywhere Arkad writes.
    foreach ($p in @((Join-Path $env:LOCALAPPDATA 'arkad-agent'), (Join-Path $HOME '.config\arkad-agent'), (Join-Path $HOME '.arkad'))) {
        if (Test-Path $p) {
            Remove-Item -Recurse -Force $p
            Write-Host "removed $p"
        }
    }

    # 4. Remove our bin dir from the user PATH.
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    try {
        $raw = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $parts = @($raw -split ';' | Where-Object { $_ })
        $kept = @($parts | Where-Object {
            [Environment]::ExpandEnvironmentVariables($_).TrimEnd('\') -ine ($BinDir.TrimEnd('\'))
        })
        if ($kept.Count -ne $parts.Count) {
            $key.SetValue('Path', ($kept -join ';'), [Microsoft.Win32.RegistryValueKind]::ExpandString)
            [Environment]::SetEnvironmentVariable('ARKAD_INSTALLER_TMP', '1', 'User')
            [Environment]::SetEnvironmentVariable('ARKAD_INSTALLER_TMP', $null, 'User')
            Write-Host "removed $BinDir from user PATH"
        }
    } finally {
        $key.Close()
    }

    Write-Host 'Arkad Agent fully uninstalled.'
}
