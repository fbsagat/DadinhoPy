# Atualiza a API do Dadinho na VPS apos um push (Fase 46/VPS).
# Copia o codigo com tar (preservando .env e cloudflared/config.yml, que sao
# especificos da instalacao e gitignored), rebuilda a api e recrea o tunnel
# apenas se docker-compose.yml mudou (o ingress vive so na VPS). Smoke test
# local e publico no final.
#
# Uso: .\atualizar_vps.ps1 [-Chave <caminho da chave SSH>] [-HostVps <ip>] [-Usuario <user>]
# Ex.: .\atualizar_vps.ps1 -Chave "D:\Downloads\Meme_Trigger\chave_nova\memetrigger-vps.key"

param(
    [string]$Chave,
    [string]$HostVps = "167.126.27.4",
    [string]$Usuario = "ubuntu"
)

$ErrorActionPreference = "Stop"
$dirRepo = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not $Chave) {
    Write-Host "ERRO: informe a chave SSH com -Chave <caminho>." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path -LiteralPath $Chave)) {
    Write-Host "ERRO: chave nao encontrada em $Chave" -ForegroundColor Red
    exit 1
}

$sshBase = @('-i', $Chave, '-o', 'StrictHostKeyChecking=no', "${Usuario}@${HostVps}")
$cmdR = { param([string]$c) & ssh @sshBase $c; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }

Write-Host "==> Copiando codigo para /opt/dadinho (tar com excludes) ..." -ForegroundColor Cyan
# Exclui o que nao vai: VCS, ambiente local, deploy da Vercel e os arquivos
# especificos da instalacao (.env, cloudflared/config.yml) — preservados.
tar -czf - `
    --exclude=".git" --exclude=".venv" --exclude=".idea" --exclude="__pycache__" `
    --exclude="*.pyc" --exclude=".vercel" --exclude=".env*" --exclude="material" `
    --exclude="cloudflared/config.yml" `
    -C $dirRepo . |
    & ssh @sshBase "cd /opt/dadinho && sudo tar -xzf -"
if ($LASTEXITCODE -ne 0) { Write-Host "ERRO: copia falhou." -ForegroundColor Red; exit 1 }

Write-Host "==> Rebuild da API (image dadinho-api) e do nginx ..." -ForegroundColor Cyan
# Fase 61: `api` tem o `build: .`; api2/3/4 usam a MESMA image `dadinho-api`
# (sem build próprio) — um build sobe as 4 réplicas.
& $cmdR "cd /opt/dadinho && sudo docker compose up -d --build api api2 api3 api4 nginx"

# O tunnel so recria quando a definicao do servico mudou (docker-compose.yml).
# O config.yml do ingress vive so na VPS e nunca vem do repo.
$hashLocal = (Get-FileHash "$dirRepo\docker-compose.yml" -Algorithm MD5).Hash
$hashRemoto = (& ssh @sshBase "sudo md5sum /opt/dadinho/docker-compose.yml | cut -d' ' -f1").Trim()
if ($hashLocal -ne $hashRemoto) {
    Write-Host "==> docker-compose.yml mudou: recriando tunnel ..." -ForegroundColor Yellow
    & $cmdR "cd /opt/dadinho && sudo docker compose up -d --force-recreate tunnel"
} else {
    Write-Host "==> docker-compose.yml inalterado: tunnel nao mexido." -ForegroundColor Green
}

Write-Host "==> Smoke test local ..." -ForegroundColor Cyan
# A réplica 1 em 8000 (loopback), as demais em 8001-8003, e a borda nginx em
# 8080 (por onde o tunnel passa).
& $cmdR "curl -s -o /dev/null -w 'robots_local:%{http_code}\n' http://127.0.0.1:8000/robots.txt && curl -s 'http://127.0.0.1:8000/socket.io/?EIO=4&transport=polling' | head -c 120 && echo && curl -s -o /dev/null -w 'robots_nginx:%{http_code}\n' http://127.0.0.1:8080/robots.txt && curl -s 'http://127.0.0.1:8080/socket.io/?EIO=4&transport=polling' | head -c 120 && echo"

Write-Host "==> Smoke test publico (via tunnel) ..." -ForegroundColor Cyan
curl.exe -s -o /dev/null -w "robots_pub:%{http_code}\n" "https://dadinho-api.memetrigger.com/robots.txt"
$hand = curl.exe -s "https://dadinho-api.memetrigger.com/socket.io/?EIO=4&transport=polling"
Write-Host ($hand.Substring(0, [Math]::Min(120, $hand.Length)))

Write-Host "==> Concluido. Valide em 2+ abas (pagina da Vercel, socket para a VPS)." -ForegroundColor Green