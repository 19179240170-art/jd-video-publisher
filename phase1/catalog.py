from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def _column_index(cell_ref: str) -> int:
    letters = re.match(r"[A-Z]+", cell_ref.upper())
    if not letters:
        return 0
    value = 0
    for char in letters.group(0):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for item in root.findall(f"{{{MAIN_NS}}}si"):
        values.append("".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t")))
    return values


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    first_sheet = workbook.find(f".//{{{MAIN_NS}}}sheet")
    if first_sheet is None:
        raise ValueError("商品库工作簿没有工作表")
    rel_id = first_sheet.attrib[f"{{{OFFICE_REL_NS}}}id"]

    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall(f"{{{REL_NS}}}Relationship"):
        if rel.attrib.get("Id") == rel_id:
            target = rel.attrib["Target"].replace("\\", "/")
            if target.startswith("/"):
                return target.lstrip("/")
            return f"xl/{target}" if not target.startswith("xl/") else target
    raise ValueError("无法定位商品库的第一个工作表")


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "inlineStr":
        return "".join(node.text or "" for node in cell.iter(f"{{{MAIN_NS}}}t"))
    value_node = cell.find(f"{{{MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return ""
    raw = value_node.text
    if cell_type == "s":
        try:
            return shared[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def read_first_sheet(path: Path) -> tuple[list[str], list[list[str]]]:
    """使用标准库读取 xlsx 的第一个工作表，所有值按文本返回。"""
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        sheet_root = ET.fromstring(archive.read(_first_sheet_path(archive)))

    matrix: list[list[str]] = []
    for row in sheet_root.findall(f".//{{{MAIN_NS}}}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{{{MAIN_NS}}}c"):
            values[_column_index(cell.attrib.get("r", "A1"))] = _cell_value(cell, shared)
        if not values:
            continue
        width = max(values) + 1
        matrix.append([values.get(index, "") for index in range(width)])

    if not matrix:
        raise ValueError("商品库没有数据")
    headers = [str(value).strip() for value in matrix[0]]
    rows = [row + [""] * (len(headers) - len(row)) for row in matrix[1:]]
    return headers, [row[: len(headers)] for row in rows]


@dataclass(frozen=True)
class CatalogItem:
    sku_id: str
    product_code: str
    product_name: str
    merchant_sku: str
    sales_attribute: str
    category: str
    store_category: str
    brand: str
    total_stock: int
    available_stock: int
    status: str
    product_url: str
    short_title: str

    @property
    def searchable_text(self) -> str:
        return " ".join(
            value
            for value in (
                self.product_name,
                self.merchant_sku,
                self.sales_attribute,
                self.category,
                self.store_category,
                self.brand,
                self.short_title,
            )
            if value
        )


def _integer(value: str) -> int:
    try:
        return int(float(value or 0))
    except ValueError:
        return 0


def load_catalog(path: Path) -> list[CatalogItem]:
    headers, rows = read_first_sheet(path)
    index = {header: position for position, header in enumerate(headers)}
    required = {"SKUID", "商品编码", "商品名称", "商家SKU", "商品状态"}
    missing = sorted(required - set(index))
    if missing:
        raise ValueError(f"商品库缺少字段：{', '.join(missing)}")

    def value(row: list[str], name: str) -> str:
        position = index.get(name)
        return row[position].strip() if position is not None and position < len(row) else ""

    items: list[CatalogItem] = []
    for row in rows:
        sku_id = value(row, "SKUID")
        if not sku_id:
            continue
        category = "/".join(
            part
            for part in (value(row, "一级类目"), value(row, "二级类目"), value(row, "三级类目"), value(row, "末级类目"))
            if part and part != "--"
        )
        items.append(
            CatalogItem(
                sku_id=sku_id,
                product_code=value(row, "商品编码") or sku_id,
                product_name=value(row, "商品名称"),
                merchant_sku=value(row, "商家SKU"),
                sales_attribute=value(row, "销售属性"),
                category=category,
                store_category=value(row, "店内分类"),
                brand=value(row, "品牌"),
                total_stock=_integer(value(row, "商品总库存")),
                available_stock=_integer(value(row, "商品可用库存")),
                status=value(row, "商品状态"),
                product_url=value(row, "商品链接"),
                short_title=value(row, "短标题"),
            )
        )
    return items


def active_items(items: Iterable[CatalogItem]) -> list[CatalogItem]:
    return [item for item in items if not item.status or item.status == "上架"]
