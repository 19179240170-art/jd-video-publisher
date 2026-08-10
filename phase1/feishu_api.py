from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FeishuConfig:
    app_id: str
    app_secret: str
    app_token: str = ""
    table_id: str = ""
    base_url: str = "https://open.feishu.cn/open-apis"


class FeishuClient:
    def __init__(self, config: FeishuConfig, timeout: int = 60):
        self.config = config
        self.timeout = timeout
        self._token: str | None = None

    def _json_request(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        token: str | None = None,
    ) -> dict:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            url,
            data=None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")[:2000]
            raise RuntimeError(f"飞书 API 请求失败 HTTP {error.code}: {body}") from error
        if result.get("code", 0) != 0:
            raise RuntimeError(f"飞书 API 返回错误：{result.get('code')} {result.get('msg')}")
        return result

    def tenant_token(self) -> str:
        if self._token:
            return self._token
        result = self._json_request(
            "POST",
            f"{self.config.base_url.rstrip('/')}/auth/v3/tenant_access_token/internal",
            {"app_id": self.config.app_id, "app_secret": self.config.app_secret},
        )
        token = result.get("tenant_access_token")
        if not token:
            raise RuntimeError("飞书认证成功但未返回tenant_access_token")
        self._token = token
        return token

    def _authorized_request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        query: dict[str, str | int] | None = None,
    ) -> dict:
        url = f"{self.config.base_url.rstrip('/')}/{path.lstrip('/')}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        return self._json_request(method, url, payload, self.tenant_token())

    def create_base(self, name: str) -> dict[str, Any]:
        result = self._authorized_request("POST", "/bitable/v1/apps", {"name": name})
        app = result.get("data", {}).get("app", {})
        if not app.get("app_token"):
            raise RuntimeError("飞书多维表格创建成功，但未返回 app_token")
        return app

    def list_tables(self, app_token: str | None = None) -> list[dict[str, Any]]:
        token = app_token or self.config.app_token
        if not token:
            raise ValueError("缺少飞书多维表格 app_token")
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            query: dict[str, str | int] = {"page_size": 100}
            if page_token:
                query["page_token"] = page_token
            result = self._authorized_request("GET", f"/bitable/v1/apps/{token}/tables", query=query)
            data = result.get("data", {})
            items.extend(data.get("items", []))
            if not data.get("has_more"):
                return items
            page_token = str(data.get("page_token", ""))

    def create_table(
        self,
        name: str,
        fields: list[dict[str, Any]],
        app_token: str | None = None,
        default_view_name: str = "全部视频",
    ) -> dict[str, Any]:
        token = app_token or self.config.app_token
        if not token:
            raise ValueError("缺少飞书多维表格 app_token")
        payload = {
            "table": {
                "name": name,
                "default_view_name": default_view_name,
                "fields": fields,
            }
        }
        result = self._authorized_request("POST", f"/bitable/v1/apps/{token}/tables", payload)
        data = result.get("data", {})
        table = data.get("table", data)
        if not table.get("table_id"):
            raise RuntimeError("飞书数据表创建成功，但未返回 table_id")
        return table

    def list_fields(
        self,
        app_token: str | None = None,
        table_id: str | None = None,
    ) -> list[dict[str, Any]]:
        app = app_token or self.config.app_token
        table = table_id or self.config.table_id
        if not app or not table:
            raise ValueError("缺少飞书多维表格 app_token 或 table_id")
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            query: dict[str, str | int] = {"page_size": 100}
            if page_token:
                query["page_token"] = page_token
            result = self._authorized_request(
                "GET",
                f"/bitable/v1/apps/{app}/tables/{table}/fields",
                query=query,
            )
            data = result.get("data", {})
            items.extend(data.get("items", []))
            if not data.get("has_more"):
                return items
            page_token = str(data.get("page_token", ""))

    def create_field(
        self,
        field: dict[str, Any],
        app_token: str | None = None,
        table_id: str | None = None,
    ) -> dict[str, Any]:
        app = app_token or self.config.app_token
        table = table_id or self.config.table_id
        if not app or not table:
            raise ValueError("缺少飞书多维表格 app_token 或 table_id")
        result = self._authorized_request(
            "POST",
            f"/bitable/v1/apps/{app}/tables/{table}/fields",
            field,
        )
        return result.get("data", {}).get("field", {})

    def list_records(
        self,
        app_token: str | None = None,
        table_id: str | None = None,
    ) -> list[dict[str, Any]]:
        app = app_token or self.config.app_token
        table = table_id or self.config.table_id
        if not app or not table:
            raise ValueError("缺少飞书多维表格 app_token 或 table_id")
        items: list[dict[str, Any]] = []
        page_token = ""
        while True:
            query: dict[str, str | int] = {"page_size": 500}
            if page_token:
                query["page_token"] = page_token
            result = self._authorized_request(
                "GET",
                f"/bitable/v1/apps/{app}/tables/{table}/records",
                query=query,
            )
            data = result.get("data", {})
            items.extend(data.get("items", []))
            if not data.get("has_more"):
                return items
            page_token = str(data.get("page_token", ""))

    def create_record(self, fields: dict, client_token: str) -> str:
        if not self.config.app_token or not self.config.table_id:
            raise ValueError("缺少飞书多维表格 app_token 或 table_id")
        url = (
            f"{self.config.base_url.rstrip('/')}/bitable/v1/apps/{self.config.app_token}"
            f"/tables/{self.config.table_id}/records"
        )
        result = self._json_request("POST", url, {"fields": fields}, self.tenant_token())
        record = result.get("data", {}).get("record", {})
        record_id = record.get("record_id")
        if not record_id:
            raise RuntimeError("飞书新增记录成功但未返回record_id")
        return record_id

    def update_record(self, record_id: str, fields: dict) -> str:
        if not self.config.app_token or not self.config.table_id:
            raise ValueError("缺少飞书多维表格 app_token 或 table_id")
        result = self._authorized_request(
            "PUT",
            (
                f"/bitable/v1/apps/{self.config.app_token}/tables/"
                f"{self.config.table_id}/records/{record_id}"
            ),
            {"fields": fields},
        )
        record = result.get("data", {}).get("record", {})
        return str(record.get("record_id") or record_id)
