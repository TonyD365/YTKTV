from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QFrame, QPushButton

from tests.helpers import FakeSource
from ytktv.ui.main_window import MainWindow
from ytktv.ui.mv_window import MvWindow


def test_buttons_do_not_overlap_at_the_minimum_width(qtbot, ktv) -> None:
    controller, _, _ = ktv
    mv = MvWindow(None)
    main = MainWindow(controller, FakeSource(), mv, "http://192.168.0.2:8765")  # type: ignore[arg-type]
    qtbot.addWidget(main)
    qtbot.addWidget(mv)
    main.resize(main.minimumWidth(), 900)
    main.show()
    QApplication.processEvents()
    bar = main.findChild(QFrame, "controlBar")
    assert bar is not None
    assert bar.minimumSizeHint().width() <= bar.width()
    boxes = [
        QRect(b.mapTo(bar, b.rect().topLeft()), b.size())
        for b in bar.findChildren(QPushButton)
        if b.isVisible()
    ]
    assert len(boxes) > 20
    assert not any(a.intersects(b) for i, a in enumerate(boxes) for b in boxes[i + 1 :])
    assert all(bar.rect().contains(box) for box in boxes)
    main.close()
