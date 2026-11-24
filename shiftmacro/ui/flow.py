"""Layout que quebra linha quando falta largura (painel de execução em janelas estreitas)."""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QSizePolicy, QWidgetItem


class FlowLayout(QLayout):
    def __init__(self, parent=None, hspacing: int = 18, vspacing: int = 6):
        super().__init__(parent)
        self._items: list = []
        self.h = hspacing
        self.v = vspacing

    def addItem(self, item):
        self._items.append(item)

    def addWidget(self, w):  # noqa: N802 (API do Qt)
        self.addChildWidget(w)
        self.addItem(QWidgetItem(w))

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do(QRect(0, 0, width, 0), dry=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, dry=False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect: QRect, dry: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, line_h = r.x(), r.y(), 0
        rows: list[list] = [[]]
        for it in self._items:
            if it.widget() is not None and not it.widget().isVisible() and not dry:
                continue
            hint = it.sizeHint()
            if x + hint.width() > r.right() + 1 and line_h > 0:
                x = r.x()
                y += line_h + self.v
                line_h = 0
                rows.append([])
            rows[-1].append((it, QPoint(x, y), hint))
            x += hint.width() + self.h
            line_h = max(line_h, hint.height())
        if not dry:
            # o último item de cada linha (contador) encosta à direita se for "stretch"
            for row in rows:
                if not row:
                    continue
                hmax = max(h.height() for _, _, h in row)
                for it, p, hint in row:
                    w = it.widget()
                    if w is not None and w.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding and (it, p, hint) == row[-1]:
                        it.setGeometry(QRect(QPoint(p.x(), p.y() + (hmax - hint.height()) // 2), QSize(r.right() - p.x() + 1, hint.height())))
                    else:
                        it.setGeometry(QRect(QPoint(p.x(), p.y() + (hmax - hint.height()) // 2), hint))
        return y + line_h - rect.y() + m.bottom()
