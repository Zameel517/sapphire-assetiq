"""
build_assets.py
===============
Creates the files build.ps1 hands to PyInstaller: the EXE's icon (app.ico) and
the version details Windows shows in the EXE's Properties (version_info.txt).

    python tools/build_assets.py <output folder>
"""

import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
sys.path.insert(0, SRC)

from app_info import APP_FULL_NAME, APP_NAME, APP_VERSION  # noqa: E402
from gui.icon import ico_bytes  # noqa: E402


def version_info() -> str:
    numbers = tuple(([int(p) for p in APP_VERSION.split(".")] + [0, 0, 0, 0])[:4])
    return f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Sapphire IT'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{APP_VERSION}'),
      StringStruct('InternalName', 'SapphireAssetIQ'),
      StringStruct('OriginalFilename', 'SapphireAssetIQ.exe'),
      StringStruct('ProductName', '{APP_FULL_NAME}'),
      StringStruct('ProductVersion', '{APP_VERSION}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main(out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "app.ico"), "wb") as fh:
        fh.write(ico_bytes())
    with open(os.path.join(out_dir, "version_info.txt"), "w", encoding="utf-8") as fh:
        fh.write(version_info())
    print(f"wrote {os.path.join(out_dir, 'app.ico')} and version_info.txt")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build")
