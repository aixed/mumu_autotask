[CmdletBinding()]
param(
    [string]$Serial = "127.0.0.1:16384",
    [string]$Adb = "D:\Program Files\Netease\MuMu\nx_main\adb.exe",
    [string]$Output,
    [switch]$EnableInlineHook
)

$ErrorActionPreference = "Stop"
$workspace = Split-Path -Parent $PSScriptRoot
if (-not $Output) {
    $Output = Join-Path $PSScriptRoot "bin\libmumu_bridge.so"
}
$resolvedOutput = [System.IO.Path]::GetFullPath($Output)
$linkDirectory = Join-Path $env:TEMP "mumu_autotask_arm64_link"
$libdl = Join-Path $linkDirectory "libdl.so"

New-Item -ItemType Directory -Force -Path $linkDirectory | Out-Null
& $Adb -s $Serial pull /system/lib64/arm64/nb/libdl.so $libdl
if ($LASTEXITCODE -ne 0) {
    throw "failed to pull ARM64 libdl.so from $Serial"
}

Push-Location $workspace
try {
    $definitions = @()
    if ($EnableInlineHook) {
        $definitions += "-DENABLE_UNSAFE_INLINE_HOOK=1"
    }
    python -m ziglang cc `
        -target aarch64-linux-android `
        -shared `
        -fPIC `
        -nostdlib `
        -fno-builtin `
        -fno-sanitize=all `
        @definitions `
        "-Wl,-soname,libmumu_bridge.so" `
        -o $resolvedOutput `
        "native\mumu_bridge.c" `
        $libdl
    if ($LASTEXITCODE -ne 0) {
        throw "ARM64 bridge compilation failed"
    }
} finally {
    Pop-Location
}

Get-Item -LiteralPath $resolvedOutput | Format-List FullName, Length, LastWriteTime
Get-FileHash -LiteralPath $resolvedOutput -Algorithm SHA256 | Format-List Hash, Path
