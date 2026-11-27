$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $root '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $pythonw)) {
    $cmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
    if ($cmd) { $pythonw = $cmd.Source }
}
if (-not $pythonw) {
    Write-Error 'pythonw.exe not found. Run install.bat first.'
    exit 1
}
$desktop = [Environment]::GetFolderPath('Desktop')
Get-ChildItem -LiteralPath $desktop -Filter 'Guardian-AI*.lnk' -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -ne 'Guardian-AI.lnk' } |
    Remove-Item -Force -ErrorAction SilentlyContinue
$targets = @((Join-Path $desktop 'Guardian-AI.lnk'))
$startMenu = [Environment]::GetFolderPath('Programs')
if ($startMenu) {
    Get-ChildItem -LiteralPath $startMenu -Filter 'Guardian-AI*.lnk' -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -ne 'Guardian-AI.lnk' } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    $targets += (Join-Path $startMenu 'Guardian-AI.lnk')
}
foreach ($lnk in $targets) {
    $shell = New-Object -ComObject WScript.Shell
    $s = $shell.CreateShortcut($lnk)
    $s.TargetPath = $pythonw
    $s.Arguments = '"' + (Join-Path $root 'backend\desktop\launcher.py') + '"'
    $s.WorkingDirectory = $root
    $s.IconLocation = (Join-Path $root 'backend\desktop\guardian.ico')
    $s.Description = 'Guardian-AI'
    $s.Save()
    Write-Host "Created: $lnk"
}
