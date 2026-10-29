"""Write the icon files a build needs. Usage: python packaging/make_icon.py OUT_DIR [PICTURE]

Copies the app's icon picture to OUT_DIR/icon.png (1024 px) and writes OUT_DIR/icon.ico
from it; the macOS build turns the PNG into an .icns with iconutil. The picture itself
is src/ytktv/ui/assets/icon.png, redrawn with packaging/draw_icon.py; YTKTV Desk passes
src/ytktv/desk/assets/icon.png as PICTURE.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402

from ytktv.ui.icon import ICON_FILE  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icon")
    picture = Path(sys.argv[2]) if len(sys.argv) > 2 else ICON_FILE
    out.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])
    image = QImage(str(picture))
    if image.isNull() or image.width() < 256:
        sys.exit(f"the icon picture {picture} is missing or too small")
    shutil.copy(picture, out / "icon.png")
    small = image.scaled(
        256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    if not small.save(str(out / "icon.ico")):
        sys.exit("could not write icon.ico")
    del app


if __name__ == "__main__":
    main()
