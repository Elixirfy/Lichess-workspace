param(
    [ValidateSet('prepare', 'build', 'live', 'check', 'browser', 'live-browser', 'asr', 'matrix')]
    [string]$Action = 'check'
)
$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path $PSScriptRoot -Parent
Push-Location $workspaceRoot
function Run-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}
function Compose {
    Run-Checked docker (@('compose', '-f', 'infra/compose.yml', '--profile', 'prediction', '--profile', 'voice') + $args)
}
function Prepare-Model {
    Compose run --rm --no-deps -v "${workspaceRoot}:/workspace" prediction python /workspace/scripts/voice_model.py
}
function Prepare-SecondaryModel {
    & uv run --no-project --python 3.12 python -m scripts.voice_service_model --check
    if ($LASTEXITCODE -eq 0) { return }
    if ($LASTEXITCODE -ne 2) { throw 'Serving model verification failed; preserve the cache and inspect the checksum error.' }
    $benchPython = '.cache/voice-benchmark-venv/Scripts/python.exe'
    if (!(Test-Path -LiteralPath $benchPython)) {
        Run-Checked uv @('venv', '.cache/voice-benchmark-venv', '--python', '3.12')
    }
    Run-Checked uv @('pip', 'install', '--python', $benchPython, '-r', 'scripts/requirements-voice-tuning.txt')
    Run-Checked $benchPython @('-m', 'scripts.voice_service_model')
}
try {
    switch ($Action) {
        'prepare' { Prepare-Model }
        'live' {
            Prepare-SecondaryModel
            Prepare-Model
            Compose build voice_asr
            Compose up -d --wait voice_asr
            Compose run --rm --no-deps ui bash ./ui/build --no-install -p
            Compose restart lila
            Compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile
            $ready = $false
            for ($attempt = 0; $attempt -lt 45; $attempt++) {
                try {
                    $response = Invoke-WebRequest 'http://127.0.0.1:8080/' -UseBasicParsing -TimeoutSec 3
                    if ($response.StatusCode -eq 200) { $ready = $true; break }
                } catch { }
                Start-Sleep -Seconds 1
            }
            if (!$ready) { throw 'Lila did not become ready; inspect scripts/dev.ps1 logs.' }
            Write-Host 'Vietnamese voice with local PhoWhisper/VAD is enabled at http://localhost:8080.'
        }
        'build' {
            Prepare-Model
            Compose run --rm --no-deps ui pnpm install --frozen-lockfile
            Compose run --rm --no-deps ui bash ./ui/build --no-install -p
            Compose restart lila
        }
        'check' {
            Run-Checked uv @('run', '--project', 'services/voice', '--frozen', 'python', '-m', 'pytest', 'services/voice/tests', '-q')
            Run-Checked uv @('run', '--project', 'services/voice', '--frozen', 'ruff', 'check', 'services/voice/app', 'services/voice/tests', 'scripts/voice_service_model.py')
            Run-Checked uv @('run', '--project', 'services/voice', '--frozen', 'ruff', 'format', '--check', 'services/voice/app', 'services/voice/tests', 'scripts/voice_service_model.py')
            Compose run --rm --no-deps -v "${workspaceRoot}:/workspace" -w /workspace prediction python -m unittest discover -s scripts/tests -v
            Compose run --rm --no-deps ui node ui/test --test-concurrency=2
            Compose run --rm --no-deps ui pnpm exec oxlint --type-aware ui/voice/src ui/voice/tests ui/round/src/ctrl.ts
            Compose run --rm --no-deps ui pnpm exec oxfmt --check ui/voice/src ui/voice/tests ui/voice/package.json ui/voice/tsconfig.json ui/voice/makeGrammar.mts ui/voice/lexicon/move-vi-lex.json ui/voice/grammar/move-vi.json ui/round/src/ctrl.ts
        }
        { $_ -in @('browser', 'live-browser', 'asr', 'matrix') } {
            $cli = Get-Item 'infra/lila-docker/repos/lila/node_modules/.pnpm/playwright-core@*/node_modules/playwright-core/cli.js' | Select-Object -First 1 -ExpandProperty FullName
            if (!$cli) { throw 'Run dev.ps1 bootstrap first.' }
            $previousCache = $env:PLAYWRIGHT_BROWSERS_PATH
            try {
                $env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $workspaceRoot '.cache/playwright'
                Run-Checked node @($cli, 'install', 'chromium', '--only-shell')
                $script = switch ($Action) {
                    'browser' { 'scripts/voice-browser-smoke.mjs' }
                    'live-browser' { 'scripts/voice-live-smoke.mjs' }
                    'matrix' { 'scripts/voice-matrix.mjs' }
                    default { 'scripts/voice-asr-probe.mjs' }
                }
                Run-Checked node @($script)
            } finally { $env:PLAYWRIGHT_BROWSERS_PATH = $previousCache }
        }
    }
} finally { Pop-Location }
