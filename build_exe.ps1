$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$appVersion = "V1.1.0"
$appName = "装饰画图片管理"
$distName = "$appName$appVersion"

if (-not (Test-Path $venvPython)) {
    throw "未找到虚拟环境 Python：$venvPython"
}

& $venvPython -m pip install pyinstaller
if ($LASTEXITCODE -ne 0) {
    throw "安装 PyInstaller 失败。"
}

$env:PYTHONPATH = Join-Path $projectRoot "src"

$distPath = Join-Path $projectRoot "dist\$distName"
$zipPath = Join-Path $projectRoot "dist\$distName.zip"
$specPath = Join-Path $projectRoot "$appName.spec"

if (Test-Path $distPath) {
    Remove-Item $distPath -Recurse -Force
}
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}

& $venvPython -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --name $appName `
    --distpath (Join-Path $projectRoot "dist") `
    --workpath (Join-Path $projectRoot "build") `
    --specpath $projectRoot `
    --paths (Join-Path $projectRoot "src") `
    --hidden-import PySide6.QtCore `
    --hidden-import PySide6.QtGui `
    --hidden-import PySide6.QtWidgets `
    --exclude-module PySide6.Qt3DAnimation `
    --exclude-module PySide6.Qt3DCore `
    --exclude-module PySide6.Qt3DExtras `
    --exclude-module PySide6.Qt3DInput `
    --exclude-module PySide6.Qt3DLogic `
    --exclude-module PySide6.Qt3DRender `
    --exclude-module PySide6.QtAsyncio `
    --exclude-module PySide6.QtAxContainer `
    --exclude-module PySide6.QtBluetooth `
    --exclude-module PySide6.QtCharts `
    --exclude-module PySide6.QtConcurrent `
    --exclude-module PySide6.QtDBus `
    --exclude-module PySide6.QtDataVisualization `
    --exclude-module PySide6.QtDesigner `
    --exclude-module PySide6.QtGraphs `
    --exclude-module PySide6.QtGraphsWidgets `
    --exclude-module PySide6.QtHelp `
    --exclude-module PySide6.QtHttpServer `
    --exclude-module PySide6.QtLocation `
    --exclude-module PySide6.QtMultimedia `
    --exclude-module PySide6.QtMultimediaWidgets `
    --exclude-module PySide6.QtNetworkAuth `
    --exclude-module PySide6.QtNfc `
    --exclude-module PySide6.QtOpenGL `
    --exclude-module PySide6.QtOpenGLWidgets `
    --exclude-module PySide6.QtPdf `
    --exclude-module PySide6.QtPdfWidgets `
    --exclude-module PySide6.QtPositioning `
    --exclude-module PySide6.QtPrintSupport `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtQuick3D `
    --exclude-module PySide6.QtQuickControls2 `
    --exclude-module PySide6.QtQuickTest `
    --exclude-module PySide6.QtQuickWidgets `
    --exclude-module PySide6.QtRemoteObjects `
    --exclude-module PySide6.QtScxml `
    --exclude-module PySide6.QtSensors `
    --exclude-module PySide6.QtSerialBus `
    --exclude-module PySide6.QtSerialPort `
    --exclude-module PySide6.QtSpatialAudio `
    --exclude-module PySide6.QtSql `
    --exclude-module PySide6.QtStateMachine `
    --exclude-module PySide6.QtSvg `
    --exclude-module PySide6.QtSvgWidgets `
    --exclude-module PySide6.QtTest `
    --exclude-module PySide6.QtTextToSpeech `
    --exclude-module PySide6.QtUiTools `
    --exclude-module PySide6.QtWebChannel `
    --exclude-module PySide6.QtWebEngineCore `
    --exclude-module PySide6.QtWebEngineQuick `
    --exclude-module PySide6.QtWebEngineWidgets `
    --exclude-module PySide6.QtWebSockets `
    --exclude-module PySide6.QtWebView `
    --exclude-module PySide6.QtXml `
    (Join-Path $projectRoot "src\pdd_art_manager\app.py")

if ($LASTEXITCODE -ne 0) {
    throw "打包失败。"
}

$builtDistPath = Join-Path $projectRoot "dist\$appName"
if (-not (Test-Path $builtDistPath)) {
    throw "未找到打包输出目录：$builtDistPath"
}

Rename-Item -Path $builtDistPath -NewName $distName
Compress-Archive -Path (Join-Path $distPath '*') -DestinationPath $zipPath -Force

if (Test-Path $specPath) {
    Remove-Item $specPath -Force
}
