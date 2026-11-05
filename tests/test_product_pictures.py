"""Pictures for menu items: chosen on the desk, made small, and sent to the rooms."""

from __future__ import annotations

import base64

from ytktv.desk.server import products_message
from ytktv.desk.store import DeskStore, Product


def test_pictures_are_stored_apart_and_sent_with_the_menu():
    store = DeskStore()
    cola = store.save_product(Product(0, "Cola", "Drinks", 3.0))
    store.set_product_picture(cola, "abc=")
    store.save_product(Product(cola, "Cola", "Drinks", 3.5))  # saving the item keeps it
    assert products_message(store)["items"][0]["picture"] == "abc="
    store.set_product_picture(cola, "")
    assert products_message(store)["items"][0]["picture"] == ""
    store.set_product_picture(cola, "xyz=")
    store.remove_product(cola)
    assert store.product_pictures() == {}


def test_desk_makes_the_picture_small(qtbot, tmp_path):
    from PySide6.QtGui import QColor, QImage

    from ytktv.desk.panels import ShopSettings
    from ytktv.ui.service_dialog import menu_picture

    big = QImage(1200, 800, QImage.Format.Format_RGB32)
    big.fill(QColor("orange"))
    path = tmp_path / "cola.png"
    big.save(str(path))
    store = DeskStore()
    store.save_product(Product(0, "Cola", "Drinks", 3.0))
    told: list[bool] = []
    shop = ShopSettings(store, lambda: told.append(True))
    qtbot.addWidget(shop)
    shop.choose_picture(shop.table.cellWidget(0, 5), str(path))
    jpeg = next(iter(store.product_pictures().values()))
    image = QImage.fromData(base64.b64decode(jpeg))
    assert max(image.width(), image.height()) == 160 and told
    assert menu_picture(jpeg) is not None and menu_picture("") is None
