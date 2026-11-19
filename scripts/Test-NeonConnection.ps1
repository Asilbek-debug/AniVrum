$ErrorActionPreference = 'Stop'

. (Join-Path $PSScriptRoot 'NeonDialog.ps1')

$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Error "AniVrum .venv Python topilmadi. Avval loyiha kutubxonalarini o‘rnating."
    exit 1
}

$secure = $null
$buffer = [IntPtr]::Zero
$start = $null
$child = $null
$result = 1
try {
    $secure = Read-NeonUrl
    if ($null -eq $secure -or $secure.Length -eq 0) {
        Write-Host 'Tekshiruv bekor qilindi yoki URL kiritilmadi.'
        exit 1
    }
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = $python
    $start.WorkingDirectory = $project
    $start.Arguments = '-I -B database/neon_preflight.py'
    $start.UseShellExecute = $false
    foreach ($key in @($start.EnvironmentVariables.Keys)) {
        if ($key -match '^PG') { $start.EnvironmentVariables.Remove([string]$key) }
    }
    $buffer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    $start.EnvironmentVariables['ANIVRUM_IMPORT_DATABASE_URL'] =
        [Runtime.InteropServices.Marshal]::PtrToStringBSTR($buffer)
    $child = [Diagnostics.Process]::Start($start)
    $start.EnvironmentVariables.Remove('ANIVRUM_IMPORT_DATABASE_URL')
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($buffer)
    $buffer = [IntPtr]::Zero
    $child.WaitForExit()
    $result = $child.ExitCode
} catch {
    Write-Host "Tekshiruvni boshlash imkoni bo‘lmadi. Windows ish stolida PowerShell buyrug‘ini bajaring."
} finally {
    if ($null -ne $start) {
        $start.EnvironmentVariables.Remove('ANIVRUM_IMPORT_DATABASE_URL')
    }
    if ($buffer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($buffer)
    }
    if ($null -ne $secure) { $secure.Dispose() }
    if ($null -ne $child) { $child.Dispose() }
}
exit $result
