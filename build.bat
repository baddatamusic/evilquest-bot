@echo off
echo Installing dependencies...
pip install pyinstaller pillow cryptography requests

echo.
echo Building EvilBot.exe...
pyinstaller --onefile --windowed --name EvilBot ^
    --hidden-import cryptography ^
    --hidden-import cryptography.hazmat.primitives.ciphers.aead ^
    --hidden-import PIL ^
    --hidden-import PIL.Image ^
    --hidden-import PIL.ImageTk ^
    --hidden-import PIL.ImageDraw ^
    --hidden-import PIL.ImageFont ^
    --hidden-import requests ^
    --hidden-import bot ^
    --hidden-import pathfinder ^
    --hidden-import ws_transport ^
    --add-data "gameassets\ui\stone-dark.png;gameassets\ui" ^
    --add-data "gameassets\maps\kcmap\walls.json;gameassets\maps\kcmap" ^
    --add-data "gameassets\maps\kcmap\tiles;gameassets\maps\kcmap\tiles" ^
    gui.py

echo.
if exist dist\EvilBot.exe (
    echo Build complete! EvilBot.exe is in the dist\ folder.
) else (
    echo Build may have failed. Check the output above.
)
pause
