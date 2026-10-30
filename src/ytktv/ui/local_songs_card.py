"""The Local Songs card in Settings: folders of video files to sing from."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
)

from ytktv.core.controller import KTVController


class LocalSongsCard(QFrame):
    def __init__(self, controller: KTVController) -> None:
        super().__init__()
        self.controller = controller
        self.setObjectName("settingsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        head = QLabel("LOCAL SONGS")
        head.setObjectName("settingsHead")
        layout.addWidget(head)
        note = QLabel(
            "Sing video files from this computer (MP4, MKV and more). Karaoke MKVs with two"
            " audio tracks switch between original and instrumental at once; an .lrc file with"
            " the same name gives the lyrics. They show first in Search and on the Local page."
        )
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        self.folders = QListWidget()
        self.folders.setMaximumHeight(110)
        layout.addWidget(self.folders)
        row = QHBoxLayout()
        add = QPushButton("Add Folder…")
        add.clicked.connect(lambda: self.add_folder())
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_folder)
        rescan = QPushButton("Look Again")
        rescan.setToolTip("Find files added to the folders since")
        rescan.clicked.connect(self.rescan)
        self.count = QLabel()
        self.count.setObjectName("muted")
        self.add_button, self.remove_button = add, remove
        for button in (add, remove, rescan):
            row.addWidget(button)
        row.addStretch()
        row.addWidget(self.count)
        layout.addLayout(row)
        self.load()

    def load(self) -> None:
        # A room bound to a staff terminal gets its folders from there.
        managed = bool(self.controller.settings.desk_url)
        self.add_button.setEnabled(not managed)
        self.remove_button.setEnabled(not managed)
        self.add_button.setToolTip("Set by the staff terminal" if managed else "")
        self.folders.clear()
        self.folders.addItems(self.controller.settings.local_folders)
        local = self.controller.local
        if local is None:
            self.count.setText("")
        elif managed and not local.scanning:
            self.count.setText(f"{len(local.songs())} songs · folders set by the staff terminal")
        elif local.scanning:
            self.count.setText("Looking…")
        else:
            self.count.setText(f"{len(local.songs())} songs")

    def _save(self, folders: list[str]) -> None:
        self.controller.settings.local_folders = folders
        self.controller.store.save()
        self.rescan()

    def add_folder(self, folder: str | None = None) -> None:
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self, "Folder of songs")
        if folder and folder not in self.controller.settings.local_folders:
            self._save([*self.controller.settings.local_folders, folder])

    def remove_folder(self) -> None:
        row = self.folders.currentRow()
        if row >= 0:
            folders = list(self.controller.settings.local_folders)
            del folders[row]
            self._save(folders)

    def rescan(self) -> None:
        local = self.controller.local
        if local is not None:
            local.scan_soon()
        self.load()
