$ErrorActionPreference = 'Stop'
$runtimeDir = Split-Path -Parent $PSCommandPath
$manifest = Get-Content -Raw -LiteralPath (Join-Path $runtimeDir 'runtime_manifest.json') | ConvertFrom-Json
$archive = Join-Path $env:TEMP 'ameath-hermes-runtime.zip'
Invoke-WebRequest -Uri $manifest.url -OutFile $archive
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $archive).Hash.ToLowerInvariant()
if ($hash -ne $manifest.sha256.ToLowerInvariant()) { throw '运行环境校验失败，安装已停止。' }
Expand-Archive -LiteralPath $archive -DestinationPath (Split-Path -Parent $runtimeDir) -Force
Remove-Item -LiteralPath $archive -Force
