param(
    [Parameter(Mandatory=$true)][string]$EnvFile,
    [ValidateSet('config','build','start','stop','status','logs')][string]$Action='status'
)
$ErrorActionPreference='Stop'
$repoRoot=Split-Path -Parent $PSScriptRoot
$resolvedEnv=(Resolve-Path -LiteralPath $EnvFile).Path
$projectLine=Get-Content -LiteralPath $resolvedEnv | Where-Object { $_ -match '^COMPOSE_PROJECT_NAME=' } | Select-Object -First 1
$project=($projectLine -split '=',2)[1]
if ($project -notmatch '^global-store-[a-z0-9][a-z0-9-]*$') { throw 'Expected an independent global-store-* Compose project name' }
if ($Action -eq 'start') {
    $marker=Join-Path (Split-Path -Parent $resolvedEnv) 'migration_verified.json'
    if (-not (Test-Path -LiteralPath $marker)) { throw 'Complete one-time data migration and verification before starting user-facing services' }
    $verified=Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json
    if ($verified.project -ne $project -or $verified.status -ne 'PASS') { throw 'Migration verification marker does not match this project' }
}
$dockerArgs=@('compose','--project-directory',$repoRoot,'-f',(Join-Path $repoRoot 'docker-compose.yml'),'--env-file',$resolvedEnv,'-p',$project)
switch ($Action) {
    'config' { $dockerArgs+=@('config','--quiet') }
    'build' { $dockerArgs+=@('build') }
    'start' { $dockerArgs+=@('up','-d') }
    'stop' { $dockerArgs+=@('stop') }
    'status' { $dockerArgs+=@('ps') }
    'logs' { $dockerArgs+=@('logs','--tail','100','app','web') }
}
& docker @dockerArgs
exit $LASTEXITCODE
