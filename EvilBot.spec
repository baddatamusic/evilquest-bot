# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=[
        # UI assets
        ('gameassets\\ui\\stone-dark.png',         'gameassets\\ui'),
        # Item sprites used in login screen and sidebar
        ('gameassets\\sprites\\items',              'gameassets\\sprites\\items'),
        # Map data — walls, water tiles, height chunks
        ('gameassets\\maps\\kcmap\\walls.json',     'gameassets\\maps\\kcmap'),
        ('gameassets\\maps\\kcmap\\tiles',          'gameassets\\maps\\kcmap\\tiles'),
        ('gameassets\\maps\\kcmap\\heights',        'gameassets\\maps\\kcmap\\heights'),
    ],
    hiddenimports=[
        'cryptography',
        'cryptography.hazmat.primitives.ciphers.aead',
        'PIL',
        'PIL.Image',
        'PIL.ImageTk',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'requests',
        'bot',
        'pathfinder',
        'ws_transport',
        'protocol',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='EvilBot-V3',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
