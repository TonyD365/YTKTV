"""Receipts on 58 mm or 80 mm thermal paper, printed through the system's printer driver.

Any receipt printer that is installed as a printer works: its driver turns the page into
the printer's own commands, Chinese included, and can be set to cut the paper.
"""

from __future__ import annotations

import time
from html import escape

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

from ytktv.desk.billing import Bill
from ytktv.desk.store import DeskStore

WIDTHS = (58, 80)  # millimetres of paper
ASK = "Ask each time"


def printers() -> list[str]:
    return [ASK, *QPrinterInfo.availablePrinterNames()]


def receipt_html(bill: Bill, shop: str, footer: str, width: int = 58) -> str:
    """A narrow receipt: big shop name, the lines, the total, how it was paid."""
    size = 9 if width == 58 else 11
    c = bill.currency
    rows = "".join(
        f"<tr><td>{escape(text)}</td><td align='right'>{amount:.2f}</td></tr>"
        for text, amount in bill.lines
    )
    extras = []
    if bill.minimum > bill.subtotal:
        extras.append(("Minimum spend", f"{bill.minimum:.2f}"))
    if bill.member:
        extras.append((f"Member {bill.member}", f"−{bill.member_off:g}%"))
    if bill.discount:
        extras.append(("Discount", f"−{bill.discount:g}%"))
    if bill.round_to:
        extras.append(("Small change", "dropped"))
    extra_rows = "".join(
        f"<tr><td>{escape(a)}</td><td align='right'>{escape(b)}</td></tr>" for a, b in extras
    )
    return (
        f"<div style='font-size:{size}pt;color:black'>"
        f"<p align='center' style='font-size:{size + 5}pt'><b>{escape(shop or 'YTKTV')}</b></p>"
        f"<p align='center'>{escape(bill.room)}{' · ' + escape(bill.guest) if bill.guest else ''}"
        f"<br>{time.strftime('%Y-%m-%d %H:%M')}</p><hr>"
        f"<table width='100%' cellspacing='0' cellpadding='1'>{rows}</table><hr>"
        f"<table width='100%' cellspacing='0' cellpadding='1'>{extra_rows}"
        f"<tr><td><b>TOTAL</b></td><td align='right'><b>{c}{bill.total:.2f}</b></td></tr>"
        f"<tr><td>Paid by</td><td align='right'>{escape(bill.payment)}</td></tr></table>"
        + (f"<hr><p align='center'>{escape(footer)}</p>" if footer else "")
        + "</div>"
    )


def receipt_printer(name: str, width: int, pdf: str = "") -> QPrinter:
    """A printer set up for a long strip of *width* mm paper with thin margins.

    With *pdf* it writes that file instead (for checking the layout without a printer).
    """
    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    # Choose where it goes first: switching printer or format resets the page size.
    if pdf:
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(pdf)
    elif name and name != ASK:
        printer.setPrinterName(name)
    fit_paper(printer, width)
    return printer


def fit_paper(printer: QPrinter, width: int) -> None:
    page = QPageSize(QSizeF(width, 297), QPageSize.Unit.Millimeter, f"Receipt {width} mm")
    printer.setPageSize(page)
    printer.setPageMargins(QMarginsF(2, 2, 2, 2), QPageLayout.Unit.Millimeter)


def document(html: str, printer: QPrinter) -> QTextDocument:
    doc = QTextDocument()
    doc.setDocumentMargin(0)
    doc.setHtml(html)
    doc.setPageSize(printer.pageLayout().paintRect(QPageLayout.Unit.Point).size())
    return doc


def print_receipt(store: DeskStore, bill: Bill, printer: QPrinter | None = None) -> QPrinter:
    """Print the receipt with the desk's settings; returns the printer it used."""
    width = int(store.setting("receipt_width", "58"))
    if printer is None:
        printer = receipt_printer(store.setting("receipt_printer", ASK), width)
    html = receipt_html(
        bill,
        store.setting("shop_name", "YTKTV"),
        store.setting("receipt_footer", "Thank you! See you again."),
        width,
    )
    copies = max(1, int(store.setting("receipt_copies", "1")))
    doc = document(html, printer)
    for _ in range(copies):
        doc.print_(printer)
    return printer
