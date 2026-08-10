from __future__ import annotations

import unittest
from pathlib import Path

from phase1.catalog import CatalogItem, load_catalog
from phase1.matching import match_catalog
from phase1.local_chatgpt import normalize_title, title_length


class TitleTests(unittest.TestCase):
    def test_title_is_clamped_to_jd_limit(self) -> None:
        title = normalize_title("这是一条非常非常非常非常非常非常非常长的京东海钓装备测评标题")
        self.assertGreaterEqual(title_length(title), 5)
        self.assertLessEqual(title_length(title), 27)

    def test_short_title_gets_fallback(self) -> None:
        self.assertGreaterEqual(title_length(normalize_title("好")), 5)


class MatchingTests(unittest.TestCase):
    def test_selects_one_product_family_and_ten_skus_at_most(self) -> None:
        items = [
            CatalogItem(
                sku_id=str(800000 + index), product_code="P1", product_name=f"示例品牌远航金属纺车轮 {4000 + index}",
                merchant_sku=f"VOYAGER{4000 + index}", sales_attribute=f"{4000 + index}型", category="鱼线轮",
                store_category="纺车轮", brand="示例品牌", total_stock=10, available_stock=10,
                status="上架", product_url="", short_title="远航金属海钓纺车轮",
            )
            for index in range(12)
        ]
        items.append(CatalogItem(
            sku_id="900001", product_code="P2", product_name="示例品牌深海铁板竿", merchant_sku="ROD",
            sales_attribute="", category="鱼竿", store_category="铁板竿", brand="示例品牌", total_stock=10,
            available_stock=10, status="上架", product_url="", short_title="深海铁板竿",
        ))
        result = match_catalog("远航纺车轮实测 VOYAGER", items)
        self.assertEqual(result.family_product_code, "P1")
        self.assertLessEqual(len(result.skus), 10)
        self.assertTrue(all(sku.product_code == "P1" for sku in result.skus))

    def test_ambiguous_families_are_left_for_review(self) -> None:
        items = [
            CatalogItem(
                sku_id="1", product_code="A", product_name="翠鸟配件", merchant_sku="",
                sales_attribute="系列绿", category="配件", store_category="配件", brand="示例品牌",
                total_stock=1, available_stock=1, status="上架", product_url="", short_title="翠鸟配件",
            ),
            CatalogItem(
                sku_id="2", product_code="B", product_name="翠鸟套装", merchant_sku="",
                sales_attribute="系列蓝", category="配件", store_category="配件", brand="示例品牌",
                total_stock=1, available_stock=1, status="上架", product_url="", short_title="翠鸟套装",
            ),
        ]
        result = match_catalog("系列", items, minimum_score=0.20)
        self.assertEqual(result.skus, ())
        self.assertIn("过于接近", result.review_reason)

    def test_preferred_product_family_is_selected_exactly(self) -> None:
        items = [
            CatalogItem(
                sku_id="10001",
                product_code="PREFERRED",
                product_name="示例品牌先锋船钓竿",
                merchant_sku="MOSHOU",
                sales_attribute="1.8米",
                category="鱼竿",
                store_category="船钓竿",
                brand="示例品牌",
                total_stock=10,
                available_stock=10,
                status="上架",
                product_url="",
                short_title="先锋船钓竿",
            ),
            CatalogItem(
                sku_id="20001",
                product_code="OTHER",
                product_name="示例品牌通用海钓竿",
                merchant_sku="OTHER",
                sales_attribute="1.8米",
                category="鱼竿",
                store_category="船钓竿",
                brand="示例品牌",
                total_stock=10,
                available_stock=10,
                status="上架",
                product_url="",
                short_title="通用海钓竿",
            ),
        ]
        result = match_catalog(
            "通用海钓竿",
            items,
            preferred_product_code="PREFERRED",
        )
        self.assertEqual(result.family_product_code, "PREFERRED")
        self.assertEqual([sku.sku_id for sku in result.skus], ["10001"])


class RealCatalogTests(unittest.TestCase):
    def test_real_catalog_schema(self) -> None:
        root = Path(__file__).resolve().parents[1]
        files = list((root / "京东后台商品导出").glob("*.xlsx"))
        if not files:
            self.skipTest("没有商品库样例")
        items = load_catalog(files[0])
        self.assertGreater(len(items), 1000)
        self.assertTrue(any("海德拉" in item.product_name for item in items))


if __name__ == "__main__":
    unittest.main()
