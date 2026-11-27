Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

$form = New-Object System.Windows.Forms.Form
$form.Text = 'Guardian-AI 客户端安装'
$form.Size = New-Object System.Drawing.Size(640, 330)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false

$label1 = New-Object System.Windows.Forms.Label
$label1.Text = '安装目录'
$label1.Location = New-Object System.Drawing.Point(24, 28)
$label1.Size = New-Object System.Drawing.Size(90, 24)
$form.Controls.Add($label1)

$pathBox = New-Object System.Windows.Forms.TextBox
$pathBox.Location = New-Object System.Drawing.Point(120, 25)
$pathBox.Size = New-Object System.Drawing.Size(390, 26)
$pathBox.Text = (Join-Path $env:LOCALAPPDATA 'Guardian-AI')
$form.Controls.Add($pathBox)

$browse = New-Object System.Windows.Forms.Button
$browse.Text = '浏览…'
$browse.Location = New-Object System.Drawing.Point(520, 24)
$browse.Size = New-Object System.Drawing.Size(80, 28)
$browse.Add_Click({
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    if ($dialog.ShowDialog() -eq 'OK') { $pathBox.Text = $dialog.SelectedPath }
})
$form.Controls.Add($browse)

$label2 = New-Object System.Windows.Forms.Label
$label2.Text = '服务器地址'
$label2.Location = New-Object System.Drawing.Point(24, 78)
$label2.Size = New-Object System.Drawing.Size(90, 24)
$form.Controls.Add($label2)

$serverBox = New-Object System.Windows.Forms.TextBox
$serverBox.Location = New-Object System.Drawing.Point(120, 75)
$serverBox.Size = New-Object System.Drawing.Size(480, 26)
$serverBox.Text = 'https://'
$form.Controls.Add($serverBox)

$note = New-Object System.Windows.Forms.Label
$note.Text = '填写管理员提供的公网地址（例如 https://xxx.ts.net 或 Cloudflare 地址）。本客户端不安装数据库，所有数据统一保存在服务器。'
$note.Location = New-Object System.Drawing.Point(120, 112)
$note.Size = New-Object System.Drawing.Size(480, 46)
$note.ForeColor = [System.Drawing.Color]::FromArgb(90, 100, 115)
$form.Controls.Add($note)

$install = New-Object System.Windows.Forms.Button
$install.Text = '开始安装'
$install.Location = New-Object System.Drawing.Point(120, 175)
$install.Size = New-Object System.Drawing.Size(140, 38)
$form.Controls.Add($install)

$status = New-Object System.Windows.Forms.Label
$status.Text = '选择安装位置并填写服务器地址'
$status.Location = New-Object System.Drawing.Point(24, 235)
$status.Size = New-Object System.Drawing.Size(570, 40)
$form.Controls.Add($status)

$install.Add_Click({
    try {
        $target = $pathBox.Text.Trim()
        $url = $serverBox.Text.Trim().TrimEnd('/')
        if (-not $target) { $status.Text = '请填写安装目录'; return }
        $uri = $null
        if (-not [Uri]::TryCreate($url, [UriKind]::Absolute, [ref]$uri) -or @('http','https') -notcontains $uri.Scheme) {
            $status.Text = '服务器地址必须以 http:// 或 https:// 开头'; return
        }
        New-Item -ItemType Directory -Force -Path $target | Out-Null
        $iconSrc = Join-Path $PSScriptRoot '..\backend\desktop\guardian.ico'
        $iconDst = Join-Path $target 'guardian.ico'
        if (Test-Path $iconSrc) { Copy-Item -LiteralPath $iconSrc -Destination $iconDst -Force }
        $config = [ordered]@{ server_url = $url; installed_at = (Get-Date).ToString('s') } | ConvertTo-Json
        Set-Content -Path (Join-Path $target 'client_config.json') -Value $config -Encoding UTF8

        $pf = $env:ProgramFiles
        $pf86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
        $candidates = @()
        if ($pf86) { $candidates += (Join-Path $pf86 'Microsoft\Edge\Application\msedge.exe') }
        if ($pf) { $candidates += (Join-Path $pf 'Microsoft\Edge\Application\msedge.exe') }
        if ($pf) { $candidates += (Join-Path $pf 'Google\Chrome\Application\chrome.exe') }
        if ($pf86) { $candidates += (Join-Path $pf86 'Google\Chrome\Application\chrome.exe') }
        $browser = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1

        $desktop = [Environment]::GetFolderPath('Desktop')
        $startMenu = [Environment]::GetFolderPath('Programs')
        $targets = @((Join-Path $desktop 'Guardian-AI.lnk'))
        if ($startMenu) { $targets += (Join-Path $startMenu 'Guardian-AI.lnk') }
        $wsh = New-Object -ComObject WScript.Shell
        foreach ($lnk in $targets) {
            $sc = $wsh.CreateShortcut($lnk)
            if ($browser) {
                $sc.TargetPath = $browser
                $sc.Arguments = '--app="' + $url + '"'
            } else {
                $sc.TargetPath = $url
            }
            $sc.WorkingDirectory = $target
            if (Test-Path $iconDst) { $sc.IconLocation = "$iconDst,0" }
            $sc.Description = 'Guardian-AI'
            $sc.Save()
        }
        $status.Text = '安装完成：' + (Join-Path $desktop 'Guardian-AI.lnk')
        $open = [System.Windows.Forms.MessageBox]::Show('安装完成，是否现在打开 Guardian-AI？', 'Guardian-AI', 'YesNo', 'Question')
        if ($open -eq 'Yes') {
            if ($browser) { Start-Process -FilePath $browser -ArgumentList ('--app="' + $url + '"') }
            else { Start-Process $url }
        }
    } catch {
        $status.Text = '安装失败：' + $_.Exception.Message
        [System.Windows.Forms.MessageBox]::Show($_.Exception.Message, '安装失败', 'OK', 'Error')
    }
})
$form.Controls.Add($install)
[void]$form.ShowDialog()
