"""Opt-in geometry evidence for synthetic Qt tests; never alters layout policy.

Set TAXOPS_UI_DIAGNOSTICS_DIR to the explicit artifact directory. With no such
setting, dump_qt_geometry does not inspect, grab, create directories, or write.
"""
from __future__ import annotations

import json
import os
import platform
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

import PySide6
from PySide6.QtCore import qVersion
from PySide6.QtGui import QFontInfo
from PySide6.QtWidgets import (
    QApplication, QAbstractButton, QAbstractScrollArea, QBoxLayout, QComboBox,
    QGridLayout, QLabel, QLayout, QLineEdit, QScrollArea, QSplitter, QTabBar,
    QTabWidget, QWidget,
)


def _size(size) -> list[int]:
    return [size.width(), size.height()]


def _rect(rect) -> list[int]:
    return [rect.x(), rect.y(), rect.width(), rect.height()]


def _enum(value) -> str:
    return getattr(value, "name", str(value))


def capture_qt_geometry(
    root: QWidget,
    *,
    phase: str = "",
    named_widgets: Mapping[str, QWidget] | None = None,
) -> dict:
    """Read the existing widget/layout state, without resize/activate/events."""
    widgets = [root, *root.findChildren(QWidget)]
    widget_ids = {id(widget): f"widget-{index}" for index, widget in enumerate(widgets)}
    aliases: dict[int, list[str]] = {id(root): ["root"]}
    for owner in widgets:
        owner_name = type(owner).__name__
        for name, value in vars(owner).items():
            if isinstance(value, QWidget):
                aliases.setdefault(id(value), []).append(f"{owner_name}.{name}")
    for name, widget in (named_widgets or {}).items():
        aliases.setdefault(id(widget), []).append(name)
    layout_ids: dict[int, str] = {}
    layouts: list[dict] = []
    layout_objects: list[QLayout] = []  # Keep Python identities alive throughout the snapshot.

    def layout_record(layout: QLayout) -> str:
        key = id(layout)
        if key in layout_ids:
            return layout_ids[key]
        ident = f"layout-{len(layout_ids)}"
        layout_ids[key] = ident
        layout_objects.append(layout)
        margins = layout.contentsMargins()
        record = {
            "id": ident, "class": type(layout).__name__,
            "object_name": layout.objectName(),
            "geometry": _rect(layout.geometry()),
            "minimum_size": _size(layout.minimumSize()),
            "maximum_size": _size(layout.maximumSize()),
            "size_hint": _size(layout.sizeHint()),
            "constraint": _enum(layout.sizeConstraint()),
            "margins": [margins.left(), margins.top(), margins.right(), margins.bottom()],
            "spacing": layout.spacing(), "items": [],
        }
        layouts.append(record)
        if isinstance(layout, QBoxLayout):
            record["direction"] = _enum(layout.direction())
        if isinstance(layout, QGridLayout):
            record["rows"] = layout.rowCount()
            record["columns"] = layout.columnCount()
            record["column_minimums"] = [layout.columnMinimumWidth(i) for i in range(layout.columnCount())]
            record["column_stretches"] = [layout.columnStretch(i) for i in range(layout.columnCount())]
        for i in range(layout.count()):
            item = layout.itemAt(i)
            child, sublayout = item.widget(), item.layout()
            entry = {
                "index": i, "geometry": _rect(item.geometry()),
                "minimum_size": _size(item.minimumSize()),
                "maximum_size": _size(item.maximumSize()),
                "size_hint": _size(item.sizeHint()), "empty": item.isEmpty(),
                "alignment": _enum(item.alignment()),
            }
            if child is not None:
                entry["widget"] = widget_ids.get(id(child))
                entry["aliases"] = aliases.get(id(child), [])
            elif sublayout is not None:
                entry["layout"] = layout_record(sublayout)
            else:
                entry["spacer"] = item.spacerItem() is not None
            if isinstance(layout, QBoxLayout):
                entry["stretch"] = layout.stretch(i)
            if isinstance(layout, QGridLayout):
                entry["grid_position"] = list(layout.getItemPosition(i))
            record["items"].append(entry)
        return ident

    records = []
    for widget in widgets:
        font, info = widget.font(), QFontInfo(widget.font())
        metrics, policy = widget.fontMetrics(), widget.sizePolicy()
        pos = widget.mapTo(root, widget.rect().topLeft())
        record = {
            "id": widget_ids[id(widget)], "aliases": aliases.get(id(widget), []),
            "class": type(widget).__name__, "object_name": widget.objectName(),
            "parent": widget_ids.get(id(widget.parentWidget())),
            "visible": widget.isVisible(), "hidden": widget.isHidden(),
            "enabled": widget.isEnabled(), "geometry": _rect(widget.geometry()),
            "root_geometry": [pos.x(), pos.y(), widget.width(), widget.height()],
            "contents_rect": _rect(widget.contentsRect()),
            "minimum_size": _size(widget.minimumSize()),
            "minimum_size_hint": _size(widget.minimumSizeHint()),
            "maximum_size": _size(widget.maximumSize()),
            "size_hint": _size(widget.sizeHint()),
            "height_for_width": widget.heightForWidth(widget.width()) if widget.hasHeightForWidth() else None,
            "policy": {"horizontal": _enum(policy.horizontalPolicy()), "vertical": _enum(policy.verticalPolicy()),
                       "horizontal_stretch": policy.horizontalStretch(), "vertical_stretch": policy.verticalStretch(),
                       "retain_size_when_hidden": policy.retainSizeWhenHidden()},
            "font": {"family": font.family(), "point_size": font.pointSizeF(), "pixel_size": font.pixelSize(),
                     "resolved_family": info.family(), "resolved_point_size": info.pointSizeF(),
                     "resolved_pixel_size": info.pixelSize(), "exact_match": info.exactMatch(),
                     "weight": int(font.weight()), "letter_spacing": font.letterSpacing(),
                     "average_char_width": metrics.averageCharWidth(), "max_char_width": metrics.maxWidth(),
                     "height": metrics.height(), "sample_cjk_width": metrics.horizontalAdvance("所有案件／租約")},
            "dpi": [widget.logicalDpiX(), widget.logicalDpiY()], "device_pixel_ratio": widget.devicePixelRatioF(),
        }
        if isinstance(widget, (QLabel, QAbstractButton, QLineEdit)):
            record["text"] = widget.text()
        if isinstance(widget, QComboBox):
            record["current_text"] = widget.currentText()
            record["minimum_contents_length"] = widget.minimumContentsLength()
        if isinstance(widget, (QTabWidget, QTabBar)):
            record["current_tab"] = widget.currentIndex()
            record["tab_labels"] = [widget.tabText(i) for i in range(widget.count())]
        if isinstance(widget, QSplitter):
            record["splitter_sizes"] = widget.sizes()
            record["children_collapsible"] = widget.childrenCollapsible()
            record["handle_width"] = widget.handleWidth()
        if isinstance(widget, QAbstractScrollArea):
            record["viewport"] = _rect(widget.viewport().geometry())
            for name, bar in (("horizontal_scroll", widget.horizontalScrollBar()), ("vertical_scroll", widget.verticalScrollBar())):
                record[name] = {"minimum": bar.minimum(), "maximum": bar.maximum(), "value": bar.value(),
                                "page_step": bar.pageStep(), "visible": bar.isVisible()}
            if isinstance(widget, QScrollArea):
                record["widget_resizable"] = widget.widgetResizable()
                body = widget.widget()
                record["scroll_content"] = widget_ids.get(id(body)) if body is not None else None
        if widget.layout() is not None:
            record["layout"] = layout_record(widget.layout())
        records.append(record)
    app, screen = QApplication.instance(), root.screen()
    return {
        "phase": phase, "environment": {
            "platform": platform.platform(), "python": platform.python_version(),
            "pyside": PySide6.__version__, "qt": qVersion(),
            "qt_platform": app.platformName(), "style": app.style().objectName(),
            "source_sha": os.environ.get("GITHUB_SHA"),
            "qt_environment": {name: os.environ.get(name) for name in ("QT_QPA_PLATFORM", "QT_SCALE_FACTOR", "QT_FONT_DPI", "QT_ENABLE_HIGHDPI_SCALING")},
            "screen": None if screen is None else {"name": screen.name(), "geometry": _rect(screen.geometry()),
                "available_geometry": _rect(screen.availableGeometry()), "logical_dpi": screen.logicalDotsPerInch(),
                "physical_dpi": screen.physicalDotsPerInch(), "device_pixel_ratio": screen.devicePixelRatio()},
        }, "root": widget_ids[id(root)], "widgets": records, "layouts": layouts,
    }


def dump_qt_geometry(
    root: QWidget,
    name: str,
    *,
    named_widgets: Mapping[str, QWidget] | None = None,
    extra: Mapping | None = None,
    checkpoints: Sequence[dict] | None = None,
) -> dict | None:
    """Save JSON plus a full widget grab only in the explicit test artifact dir.

    Diagnostic errors are reported without replacing the caller's strict assert.
    A PNG grab may trigger Qt paint work, so dimensions before/after are recorded.
    Callers must retain any already-observed failing value in their assertion.
    """
    destination = os.environ.get("TAXOPS_UI_DIAGNOSTICS_DIR")
    if not destination:
        return None
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._") or "qt-widget"
    result = {"name": safe_name}
    try:
        directory = Path(destination)
        directory.mkdir(parents=True, exist_ok=True)
        document = capture_qt_geometry(root, phase="failure-before-grab", named_widgets=named_widgets)
        document["extra"] = dict(extra or {})
        document["checkpoints"] = list(checkpoints or [])
        png_path = directory / f"{safe_name}.png"
        json_path = directory / f"{safe_name}.json"
        document["png_saved"] = root.grab().save(str(png_path), "PNG")
        document["after_grab_size"] = _size(root.size())
        json_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        result.update(json=str(json_path), png=str(png_path), png_saved=document["png_saved"])
    except Exception as exc:
        result["diagnostic_error"] = f"{type(exc).__name__}: {exc}"
    print("QT_GEOMETRY_DIAGNOSTICS " + json.dumps(result, ensure_ascii=False))
    return result
