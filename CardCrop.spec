# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('fonts', 'fonts'), ('mobile', 'mobile')]
binaries = []
hiddenimports = ['identify', 'listing', 'engine', 'tether', 'ebay', 'stats', 'card3d', 'market', 'grading', 'calibrate', 'layers', 'anim', 'animui', 'gltf_export', 'sounds', 'ui_base', 'ui_widgets', 'ui_tasks', 'ui_editor', 'ui_live', 'ui_dialogs', 'ui_store', 'ui_list', 'ui_market', 'ui_reports', 'ui_viewer3d', 'ui_motion', 'ui_marks', 'main_shoot', 'main_queue', 'main_session', 'main_ebay', 'main_reports', 'main_export', 'main_pipeline', 'sales', 'prices', 'phone_server', 'phone_link', 'phone_tools', 'phone_push', 'scans', 'centering', 'ui_centering', 'segno', 'cryptography', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtSvg', 'level', 'shiptrack', 'ui_ship', 'usps_web', 'PySide6.QtWebEngineCore']
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('rawpy')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pillow_heif')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('imageio_ffmpeg')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'matplotlib', 'pandas', 'skimage', 'imageio', 'tkinter', 'IPython', 'PySide6.QtPdf', 'PySide6.QtMultimedia', 'PySide6.Qt3DCore'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='CardCrop',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['CardCrop.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='CardCrop',
)
app = BUNDLE(
    coll,
    name='CardCrop.app',
    icon='CardCrop.icns',
    bundle_identifier='art.zack3d.cardcrop',
)
