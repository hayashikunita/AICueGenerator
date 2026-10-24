param([string]$DataDir = $(if ($env:AICUE_DATA_DIR) { $env:AICUE_DATA_DIR } else { Join-Path $env:USERPROFILE '.aicuegenerator' }))
$ErrorActionPreference = 'Stop'
$cueBackend = Split-Path -Parent $PSScriptRoot
$cuePython = Join-Path $cueBackend '.venv\Scripts\python.exe'
$cueAiEnv = Join-Path $cueBackend '.venv-ai'
$cueAiPython = Join-Path $cueAiEnv 'Scripts\python.exe'
& $cuePython -m venv $cueAiEnv
if ($LASTEXITCODE -ne 0) { throw 'AI環境を作成できませんでした。' }
& $cueAiPython -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.14.1+cpu'
if ($LASTEXITCODE -ne 0) { throw 'CPU版PyTorchを導入できませんでした。' }
& $cueAiPython -m pip install 'demucs-infer @ git+https://github.com/openmirlab/demucs-infer.git@ffe0080ef96336a34e3f0ee8ba22ceaa0623a36c'
if ($LASTEXITCODE -ne 0) { throw '音源分離環境を導入できませんでした。' }
$cueModels = Join-Path $DataDir 'ai-models'
& $cueAiPython (Join-Path $cueBackend 'app\analysis\stem_worker.py') --prepare --model-dir $cueModels --output (Join-Path $cueModels 'ready.json')
if ($LASTEXITCODE -ne 0) { throw '学習済みモデルを読み込めませんでした。' }
Write-Output 'AI補助の準備ができました。アプリを更新すると選択できます。'
