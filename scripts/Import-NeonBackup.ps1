$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'NeonDialog.ps1')

function Invoke-NeonImportStep([string]$Step, [Security.SecureString]$Credential) {
    $start = New-Object Diagnostics.ProcessStartInfo
    $start.FileName = $python
    $start.WorkingDirectory = $project
    $start.Arguments = "-E -s -B -m database.neon_import $Step"
    $start.UseShellExecute = $false
    foreach ($key in @($start.EnvironmentVariables.Keys)) {
        if ($key -match '^PG') { $start.EnvironmentVariables.Remove([string]$key) }
    }
    $buffer = [IntPtr]::Zero
    $child = $null
    try {
        try {
            $buffer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Credential)
            $start.EnvironmentVariables['ANIVRUM_IMPORT_DATABASE_URL'] =
                [Runtime.InteropServices.Marshal]::PtrToStringBSTR($buffer)
            $child = [Diagnostics.Process]::Start($start)
        } finally {
            $start.EnvironmentVariables.Remove('ANIVRUM_IMPORT_DATABASE_URL')
            if ($buffer -ne [IntPtr]::Zero) {
                [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($buffer)
            }
        }
        $child.WaitForExit()
        return $child.ExitCode
    } finally {
        if ($null -ne $child) { $child.Dispose() }
    }
}

$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Host 'AniVrum .venv Python topilmadi.'
    exit 1
}
$credential = $null
$result = 1
try {
    $credential = Read-NeonUrl
    if ($null -eq $credential) {
        Write-Host 'Import bekor qilindi.'
        exit 1
    }
    $result = Invoke-NeonImportStep 'check' $credential
    if ($result -ne 0) {
        [void][Windows.Forms.MessageBox]::Show(
            "Tekshiruvdan o‘tilmadi. Import bajarilmadi. Tafsilot terminalda.",
            'AniVrum import', 'OK', 'Warning')
        exit $result
    }
    $confirmation = @"
Neon bo‘sh, TLS va SQLite yaxlitligi tasdiqlandi.

Zaxira: anivrum-20261119T223530827917Z.db
3 anime, 4 fasl, 39 qism, 39 video file_id
4 tarixiy kod va 37 ko‘rish yozuvi

Neon Dashboard’da URL production branch’iga tegishli ekanini tekshiring.
Ushbu zaxirani Neon neondb bazasiga import qilishni tasdiqlaysizmi?
"@
    $choice = [Windows.Forms.MessageBox]::Show(
        $confirmation, 'AniVrum importini tasdiqlash', 'YesNo', 'Warning', 'Button2')
    if ($choice -ne [Windows.Forms.DialogResult]::Yes) {
        Write-Host 'Import bekor qilindi.'
        exit 1
    }
    $result = Invoke-NeonImportStep 'confirmed-import' $credential
    if ($result -eq 0) {
        [void][Windows.Forms.MessageBox]::Show(
            'Import muvaffaqiyatli. Barcha jadvallar mos, 39 ta video file_id saqlandi.',
            'AniVrum import', 'OK', 'Information')
    } elseif ($result -eq 3) {
        [void][Windows.Forms.MessageBox]::Show(
            "Import saqlandi, ammo yakuniy tekshiruv o‘tmadi. Qayta import qilmang.",
            'AniVrum import', 'OK', 'Warning')
    } else {
        [void][Windows.Forms.MessageBox]::Show(
            'Import natijasi tasdiqlanmadi. Qayta urinishdan oldin terminal natijasini va Neon holatini tekshiring.',
            'AniVrum import', 'OK', 'Error')
    }
} catch {
    Write-Host 'Import oynasi amalni yakunlay olmadi. Neon holatini tekshiring.'
    $result = 1
} finally {
    if ($null -ne $credential) { $credential.Dispose() }
}
exit $result
