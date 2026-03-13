#Requires -Version 5.0
param()
Set-StrictMode -Off

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[System.Windows.Forms.Application]::SetCompatibleTextRenderingDefault($false)

$ScriptDir    = Split-Path -Parent $MyInvocation.MyCommand.Definition
$VenvDir      = Join-Path $ScriptDir ".venv"
$VenvPy       = Join-Path $VenvDir "Scripts\python.exe"
$script:PythonExe   = ""
$script:InstallDone = $false
$script:LogExpanded = $false

# -- Colours ------------------------------------------------------------------
$BG     = [System.Drawing.Color]::FromArgb(28,  28,  30)
$PANEL  = [System.Drawing.Color]::FromArgb(44,  44,  46)
$ACCENT = [System.Drawing.Color]::FromArgb(0,  122, 255)
$TXT    = [System.Drawing.Color]::FromArgb(242, 242, 247)
$SUB    = [System.Drawing.Color]::FromArgb(174, 174, 178)
$GREEN  = [System.Drawing.Color]::FromArgb(48,  209,  88)
$RED    = [System.Drawing.Color]::FromArgb(255,  69,  58)
$LOGBG  = [System.Drawing.Color]::FromArgb(10,   10,  12)
$WHITE  = [System.Drawing.Color]::White

$FNormal = New-Object System.Drawing.Font("Segoe UI", 10)
$FBig    = New-Object System.Drawing.Font("Segoe UI", 20, [System.Drawing.FontStyle]::Bold)
$FSmall  = New-Object System.Drawing.Font("Segoe UI",  9)
$FMono   = New-Object System.Drawing.Font("Consolas", 8.5)

# -- Layout constants ---------------------------------------------------------
$BTN_Y_COLL = 415
$BTN_Y_EXP  = 545
$H_COLL     = 460
$H_EXP      = 595

# -- Form ---------------------------------------------------------------------
$Form = New-Object System.Windows.Forms.Form
$Form.Text            = "NokiCam Setup"
$Form.ClientSize      = New-Object System.Drawing.Size(520, $H_COLL)
$Form.StartPosition   = "CenterScreen"
$Form.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedSingle
$Form.MaximizeBox     = $false
$Form.BackColor       = $BG
$Form.ForeColor       = $TXT
$Form.Font            = $FNormal

# -- Header -------------------------------------------------------------------
$hdr = New-Object System.Windows.Forms.Panel
$hdr.SetBounds(0, 0, 520, 90)
$hdr.BackColor = $PANEL

$lbTitle = New-Object System.Windows.Forms.Label
$lbTitle.Text      = "NokiCam"
$lbTitle.Font      = $FBig
$lbTitle.ForeColor = $TXT
$lbTitle.AutoSize  = $true
$lbTitle.Location  = New-Object System.Drawing.Point(20, 14)

$lbSub = New-Object System.Windows.Forms.Label
$lbSub.Text      = "Webcam Fisheye Correction + Virtual Camera"
$lbSub.Font      = $FSmall
$lbSub.ForeColor = $SUB
$lbSub.AutoSize  = $true
$lbSub.Location  = New-Object System.Drawing.Point(22, 55)

$hdr.Controls.AddRange(@($lbTitle, $lbSub))
$Form.Controls.Add($hdr)

# Install path
$lbPath = New-Object System.Windows.Forms.Label
$lbPath.Text      = "Installing to:  $ScriptDir"
$lbPath.Font      = $FSmall
$lbPath.ForeColor = $SUB
$lbPath.SetBounds(20, 97, 480, 20)
$Form.Controls.Add($lbPath)

# Divider
$div = New-Object System.Windows.Forms.Panel
$div.SetBounds(20, 122, 480, 1)
$div.BackColor = $PANEL
$Form.Controls.Add($div)

# -- Steps --------------------------------------------------------------------
$StepNames = @(
    "Check Python 3.10+",
    "Create virtual environment",
    "Upgrade pip",
    "Install core packages  (OpenCV, PyQt5, MediaPipe, Pillow)",
    "Install virtual camera  (pyvirtualcam)",
    "Create desktop shortcut",
    "Create Start Menu shortcut"
)
$StepIco = @()
$StepLbl = @()
for ($i = 0; $i -lt $StepNames.Count; $i++) {
    $y = 131 + $i * 26

    $ico = New-Object System.Windows.Forms.Label
    $ico.Text      = "o"
    $ico.ForeColor = $SUB
    $ico.Font      = $FNormal
    $ico.SetBounds(20, $y, 20, 22)
    $Form.Controls.Add($ico)

    $lbl = New-Object System.Windows.Forms.Label
    $lbl.Text      = $StepNames[$i]
    $lbl.ForeColor = $SUB
    $lbl.Font      = $FNormal
    $lbl.SetBounds(44, $y, 456, 22)
    $Form.Controls.Add($lbl)

    $StepIco += $ico
    $StepLbl += $lbl
}

# -- Progress bar -------------------------------------------------------------
$PBar = New-Object System.Windows.Forms.ProgressBar
$PBar.SetBounds(20, 318, 480, 18)
$PBar.Minimum = 0
$PBar.Maximum = 100
$PBar.Style   = [System.Windows.Forms.ProgressBarStyle]::Continuous
$Form.Controls.Add($PBar)

# -- Status label -------------------------------------------------------------
$lbStatus = New-Object System.Windows.Forms.Label
$lbStatus.Text      = "Click Install to begin."
$lbStatus.Font      = $FSmall
$lbStatus.ForeColor = $SUB
$lbStatus.SetBounds(20, 342, 480, 20)
$Form.Controls.Add($lbStatus)

# -- Details toggle -----------------------------------------------------------
$btnToggle = New-Object System.Windows.Forms.Button
$btnToggle.Text      = "> Show details"
$btnToggle.SetBounds(16, 367, 160, 26)
$btnToggle.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$btnToggle.ForeColor = $ACCENT
$btnToggle.BackColor = $BG
$btnToggle.Cursor    = [System.Windows.Forms.Cursors]::Hand
$btnToggle.FlatAppearance.BorderSize         = 0
$btnToggle.FlatAppearance.MouseOverBackColor = $BG
$btnToggle.FlatAppearance.MouseDownBackColor = $BG
$Form.Controls.Add($btnToggle)

# -- Debug log (hidden by default) --------------------------------------------
$rtbLog = New-Object System.Windows.Forms.RichTextBox
$rtbLog.SetBounds(20, 398, 480, 136)
$rtbLog.BackColor    = $LOGBG
$rtbLog.ForeColor    = $SUB
$rtbLog.Font         = $FMono
$rtbLog.ReadOnly     = $true
$rtbLog.ScrollBars   = [System.Windows.Forms.RichTextBoxScrollBars]::Vertical
$rtbLog.BorderStyle  = [System.Windows.Forms.BorderStyle]::FixedSingle
$rtbLog.Visible      = $false
$Form.Controls.Add($rtbLog)

# -- Buttons ------------------------------------------------------------------
$btnCopy = New-Object System.Windows.Forms.Button
$btnCopy.Text      = "Copy debug info"
$btnCopy.SetBounds(20, $BTN_Y_COLL, 148, 32)
$btnCopy.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$btnCopy.BackColor = $PANEL
$btnCopy.ForeColor = $SUB
$btnCopy.FlatAppearance.BorderSize = 0
$btnCopy.Visible   = $false
$Form.Controls.Add($btnCopy)

$btnCancel = New-Object System.Windows.Forms.Button
$btnCancel.Text      = "Cancel"
$btnCancel.SetBounds(302, $BTN_Y_COLL, 88, 32)
$btnCancel.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$btnCancel.BackColor = $PANEL
$btnCancel.ForeColor = $TXT
$btnCancel.FlatAppearance.BorderSize = 0
$Form.Controls.Add($btnCancel)

$btnInstall = New-Object System.Windows.Forms.Button
$btnInstall.Text      = "Install"
$btnInstall.SetBounds(400, $BTN_Y_COLL, 100, 32)
$btnInstall.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$btnInstall.BackColor = $ACCENT
$btnInstall.ForeColor = $WHITE
$btnInstall.FlatAppearance.BorderSize = 0
$Form.Controls.Add($btnInstall)

# -- Helpers ------------------------------------------------------------------
function Write-Log([string]$Line) {
    if (-not $Line) { return }
    $rtbLog.AppendText("$Line`n")
    $rtbLog.ScrollToCaret()
}

function Update-Status([string]$Msg) {
    $lbStatus.Text = $Msg
    Write-Log $Msg
    [System.Windows.Forms.Application]::DoEvents()
}

function Set-Step([int]$Idx, [string]$State) {
    switch ($State) {
        "active" { $StepIco[$Idx].Text=">"; $StepIco[$Idx].ForeColor=$ACCENT; $StepLbl[$Idx].ForeColor=$TXT }
        "ok"     { $StepIco[$Idx].Text="OK"; $StepIco[$Idx].ForeColor=$GREEN;  $StepLbl[$Idx].ForeColor=$TXT }
        "error"  { $StepIco[$Idx].Text="!!"; $StepIco[$Idx].ForeColor=$RED;    $StepLbl[$Idx].ForeColor=$RED
                   if (-not $script:LogExpanded) { Expand-Log } }
        "skip"   { $StepIco[$Idx].Text="-";  $StepIco[$Idx].ForeColor=$SUB;    $StepLbl[$Idx].ForeColor=$SUB }
    }
    [System.Windows.Forms.Application]::DoEvents()
}

function Expand-Log {
    $script:LogExpanded  = $true
    $btnToggle.Text      = "v Hide details"
    $rtbLog.Visible      = $true
    $btnCopy.Visible     = $true
    $Form.ClientSize     = New-Object System.Drawing.Size(520, $H_EXP)
    $btnCopy.Location    = New-Object System.Drawing.Point(20,  $BTN_Y_EXP)
    $btnCancel.Location  = New-Object System.Drawing.Point(302, $BTN_Y_EXP)
    $btnInstall.Location = New-Object System.Drawing.Point(400, $BTN_Y_EXP)
    [System.Windows.Forms.Application]::DoEvents()
}

function Collapse-Log {
    $script:LogExpanded  = $false
    $btnToggle.Text      = "> Show details"
    $rtbLog.Visible      = $false
    $btnCopy.Visible     = $false
    $Form.ClientSize     = New-Object System.Drawing.Size(520, $H_COLL)
    $btnCopy.Location    = New-Object System.Drawing.Point(20,  $BTN_Y_COLL)
    $btnCancel.Location  = New-Object System.Drawing.Point(302, $BTN_Y_COLL)
    $btnInstall.Location = New-Object System.Drawing.Point(400, $BTN_Y_COLL)
    [System.Windows.Forms.Application]::DoEvents()
}

# -- Run subprocess with live log output (async, non-blocking) ----------------
function Invoke-Setup([string]$Exe, [string]$CmdArgs) {
    Write-Log ""
    Write-Log "> $Exe $CmdArgs"

    # Thread-safe queue shared between .NET event callbacks and the UI thread
    $queue = [System.Collections.Concurrent.ConcurrentQueue[string]]::new()

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName               = $Exe
    $psi.Arguments              = $CmdArgs
    $psi.UseShellExecute        = $false
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError  = $true
    $psi.CreateNoWindow         = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8
    $psi.StandardErrorEncoding  = [System.Text.Encoding]::UTF8

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    # Register async output handlers; MessageData carries the queue into the callback
    $outJob = Register-ObjectEvent -InputObject $proc -EventName OutputDataReceived `
        -MessageData $queue -Action {
            if ($null -ne $Event.SourceEventArgs.Data) {
                $Event.MessageData.Enqueue($Event.SourceEventArgs.Data)
            }
        }
    $errJob = Register-ObjectEvent -InputObject $proc -EventName ErrorDataReceived `
        -MessageData $queue -Action {
            if ($null -ne $Event.SourceEventArgs.Data) {
                $Event.MessageData.Enqueue("[!] " + $Event.SourceEventArgs.Data)
            }
        }

    $proc.Start() | Out-Null
    $proc.BeginOutputReadLine()
    $proc.BeginErrorReadLine()

    # Drain queue every 100ms -- never blocks, UI stays responsive
    while (-not $proc.HasExited) {
        $line = $null
        while ($queue.TryDequeue([ref]$line)) { Write-Log $line }
        [System.Windows.Forms.Application]::DoEvents()
        Start-Sleep -Milliseconds 100
    }
    $proc.WaitForExit()          # ensures all OutputDataReceived events have fired
    Start-Sleep -Milliseconds 200
    $line = $null
    while ($queue.TryDequeue([ref]$line)) { Write-Log $line }

    Unregister-Event -SourceIdentifier $outJob.Name -ErrorAction SilentlyContinue
    Unregister-Event -SourceIdentifier $errJob.Name -ErrorAction SilentlyContinue
    Remove-Job $outJob, $errJob  -ErrorAction SilentlyContinue

    return $proc.ExitCode
}

function Find-Python {
    foreach ($exe in @("python", "python3", "py")) {
        try {
            $rc = Invoke-Setup $exe '-c "import sys; exit(0 if sys.version_info>=(3,10) else 1)"'
            if ($rc -eq 0) { return $exe }
        } catch {}
    }
    return $null
}

function Refresh-EnvPath {
    $m = [System.Environment]::GetEnvironmentVariable("PATH", [System.EnvironmentVariableTarget]::Machine)
    $u = [System.Environment]::GetEnvironmentVariable("PATH", [System.EnvironmentVariableTarget]::User)
    $env:PATH = (@($m, $u) | Where-Object { $_ }) -join ";"
}

# -- Main install routine -----------------------------------------------------
function Start-Install {
    $btnInstall.Enabled = $false
    $btnCancel.Text     = "Close"
    $PBar.Value         = 3

    Write-Log "=== NokiCam Setup  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ==="
    Write-Log "Install dir: $ScriptDir"

    # Step 0 - Python
    Set-Step 0 "active"
    Update-Status "Looking for Python 3.10+..."
    $script:PythonExe = Find-Python

    if (-not $script:PythonExe) {
        Update-Status "Python not found - installing via winget..."
        $rc = Invoke-Setup "winget" "install --id Python.Python.3.11 --source winget --accept-package-agreements --accept-source-agreements"
        if ($rc -ne 0) {
            Set-Step 0 "error"
            Update-Status "Python install failed - see details."
            return
        }
        Refresh-EnvPath
        $script:PythonExe = Find-Python
        if (-not $script:PythonExe) {
            Set-Step 0 "error"
            Update-Status "Python installed but not found in PATH - please close and re-run setup."
            return
        }
    }
    Set-Step 0 "ok"
    Write-Log "Using Python: $($script:PythonExe)"
    $PBar.Value = 14

    # Step 1 - venv
    Set-Step 1 "active"
    Update-Status "Creating virtual environment..."
    $rc = Invoke-Setup $script:PythonExe "-m venv `"$VenvDir`""
    if ($rc -ne 0) { Set-Step 1 "error"; Update-Status "Failed to create virtual environment."; return }
    Set-Step 1 "ok"
    $PBar.Value = 27

    # Step 2 - pip upgrade
    Set-Step 2 "active"
    Update-Status "Upgrading pip..."
    Invoke-Setup $VenvPy "-m pip install --upgrade pip --quiet" | Out-Null
    Set-Step 2 "ok"
    $PBar.Value = 37

    # Step 3 - core packages
    Set-Step 3 "active"
    Update-Status "Installing core packages - this may take a few minutes..."
    $req = Join-Path $ScriptDir "requirements_windows.txt"
    if (Test-Path $req) {
        $rc = Invoke-Setup $VenvPy "-m pip install -r `"$req`""
    } else {
        $rc = Invoke-Setup $VenvPy "-m pip install opencv-python-headless numpy PyQt5 mediapipe Pillow"
    }
    if ($rc -ne 0) { Set-Step 3 "error"; Update-Status "Package install failed - check internet connection."; return }
    Set-Step 3 "ok"
    $PBar.Value = 72

    # Step 4 - pyvirtualcam
    Set-Step 4 "active"
    Update-Status "Installing virtual camera support..."
    $rc = Invoke-Setup $VenvPy '-m pip install "pyvirtualcam[mediafoundation]"'
    if ($rc -ne 0) {
        Set-Step 4 "skip"
        Update-Status "pyvirtualcam unavailable (virtual cam disabled - app still works)."
    } else {
        Set-Step 4 "ok"
    }
    $PBar.Value = 84

    # Step 5 - desktop shortcut
    Set-Step 5 "active"
    Update-Status "Creating desktop shortcut..."
    try {
        $sh   = New-Object -ComObject WScript.Shell
        $link = $sh.CreateShortcut((Join-Path $sh.SpecialFolders("Desktop") "NokiCam.lnk"))
        $link.TargetPath       = $VenvPy
        $link.Arguments        = "`"$(Join-Path $ScriptDir 'main.py')`""
        $link.WorkingDirectory = $ScriptDir
        $link.Description      = "NokiCam - Webcam Fisheye Correction"
        $link.Save()
        Set-Step 5 "ok"
    } catch { Set-Step 5 "error"; Write-Log "Desktop shortcut: $_" }
    $PBar.Value = 93

    # Step 6 - start menu shortcut
    Set-Step 6 "active"
    Update-Status "Creating Start Menu shortcut..."
    try {
        $sh   = New-Object -ComObject WScript.Shell
        $link = $sh.CreateShortcut((Join-Path ([System.Environment]::GetFolderPath("StartMenu")) "Programs\NokiCam.lnk"))
        $link.TargetPath       = $VenvPy
        $link.Arguments        = "`"$(Join-Path $ScriptDir 'main.py')`""
        $link.WorkingDirectory = $ScriptDir
        $link.Description      = "NokiCam - Webcam Fisheye Correction"
        $link.Save()
        Set-Step 6 "ok"
    } catch { Set-Step 6 "error"; Write-Log "Start menu shortcut: $_" }
    $PBar.Value = 100

    # Done
    $lbStatus.ForeColor = $GREEN
    Update-Status "Installation complete!  You can now launch NokiCam."
    Write-Log "=== Done ==="
    $script:InstallDone = $true
    $btnInstall.Text    = "Launch NokiCam"
    $btnInstall.Enabled = $true
}

# -- Event handlers -----------------------------------------------------------
$btnToggle.Add_Click({
    if ($script:LogExpanded) { Collapse-Log } else { Expand-Log }
})

$btnCopy.Add_Click({
    try {
        [System.Windows.Forms.Clipboard]::SetText($rtbLog.Text)
        $btnCopy.Text = "Copied!"
        $t = New-Object System.Windows.Forms.Timer
        $t.Interval = 2000
        $t.Add_Tick({ $btnCopy.Text = "Copy debug info"; $t.Stop(); $t.Dispose() })
        $t.Start()
    } catch {}
})

$btnCancel.Add_Click({ $Form.Close() })

$btnInstall.Add_Click({
    if ($script:InstallDone) {
        Start-Process $VenvPy -ArgumentList "`"$(Join-Path $ScriptDir 'main.py')`"" -WorkingDirectory $ScriptDir
        $Form.Close()
    } else {
        Start-Install
    }
})

# -- Show ---------------------------------------------------------------------
$Form.ShowDialog() | Out-Null
