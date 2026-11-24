"""Desenho das colunas Ação e Descrição: barra de cor do tipo, ícone e recuo
com guias para blocos (If, Loop, While, Função)."""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from . import icons, theme
from .models import ACTION, CURRENT_ROLE, DEPTH_ROLE, DESC, KIND_ROLE, NAME_ROLE, STEP

INDENT = 16


class StepDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        col = index.column()
        t = theme.current()
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        kind = index.data(KIND_ROLE) or "flow"
        color = QColor(t.kinds.get(kind, t.muted))
        current = bool(index.data(CURRENT_ROLE))

        if col not in (ACTION, DESC):
            super().paint(painter, option, index)
            if col == STEP and current:
                painter.fillRect(QRect(option.rect.left(), option.rect.top(), 3, option.rect.height()), QColor(t.accent))
            return

        # fundo (seleção / linha atual) desenhado pelo estilo, sem o texto
        text = opt.text
        opt.text = ""
        opt.icon = opt.icon.__class__()
        style = opt.widget.style() if opt.widget else None
        if style:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = option.rect
        fg = opt.palette.color(QPalette.ColorRole.Text)
        brush = index.data(Qt.ItemDataRole.ForegroundRole)
        if brush is not None:
            fg = QColor(brush) if not hasattr(brush, "color") else brush.color()
        font = index.data(Qt.ItemDataRole.FontRole) or opt.font
        painter.setFont(font)

        if col == ACTION:
            painter.fillRect(QRect(r.left(), r.top() + 4, 3, r.height() - 8), color)
            dpr = painter.device().devicePixelRatioF() if painter.device() else 1.0
            pm = icons.kind_pixmap(kind, color.name(), 15, dpr)
            painter.drawPixmap(r.left() + 10, r.top() + (r.height() - 15) // 2, pm)
            tr = QRect(r.left() + 32, r.top(), r.width() - 36, r.height())
            painter.setPen(fg)
            name = index.data(NAME_ROLE) or ""
            fm = painter.fontMetrics()
            label = fm.elidedText(text, Qt.TextElideMode.ElideRight, tr.width())
            painter.drawText(tr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
            if name:
                used = fm.horizontalAdvance(label) + 8
                if used < tr.width() - 20:
                    painter.setPen(QColor(t.faint))
                    rest = QRect(tr.left() + used, tr.top(), tr.width() - used, tr.height())
                    painter.drawText(rest, Qt.AlignmentFlag.AlignVCenter, fm.elidedText(f"· {name}", Qt.TextElideMode.ElideRight, rest.width()))
        else:
            depth = int(index.data(DEPTH_ROLE) or 0)
            guide = QColor(t.line)
            pen = QPen(guide, 1)
            painter.setPen(pen)
            for d in range(depth):
                x = r.left() + 8 + d * INDENT
                painter.drawLine(x, r.top(), x, r.bottom())
            left = r.left() + 6 + depth * INDENT
            tr = QRect(left, r.top(), r.right() - left - 4, r.height())
            # condições e loops ganham a cor do tipo (estrutura salta aos olhos);
            # etapas desativadas mantêm a cor apagada
            normal = opt.palette.color(QPalette.ColorRole.Text)
            painter.setPen(color if kind in ("condition", "loop") and fg == normal else fg)
            fm = painter.fontMetrics()
            painter.drawText(tr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             fm.elidedText(text, Qt.TextElideMode.ElideRight, tr.width()))
        painter.restore()

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        s.setHeight(max(s.height(), 28))
        return s
