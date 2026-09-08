"""Private result storage. Credentials stay on the Streamlit server."""
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from uuid import uuid4
import requests
from settings import get_setting


class StorageError(RuntimeError):
    pass


def cloud_enabled():
    return bool(get_setting("SUPABASE_URL") or get_setting("SUPABASE_SERVICE_ROLE_KEY"))


class CloudHistory:
    bucket = "kakao-route-results"
    table = "kakao_route_history"

    def __init__(self):
        self.url = get_setting("SUPABASE_URL").rstrip("/")
        key = get_setting("SUPABASE_SERVICE_ROLE_KEY")
        if not self.url or not key:
            raise StorageError("SUPABASE_URL과 SUPABASE_SERVICE_ROLE_KEY를 모두 설정하세요.")
        if urlparse(self.url).scheme != "https":
            raise StorageError("저장소 주소는 HTTPS여야 합니다.")
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}"}

    def request(self, method, path, **kwargs):
        headers = dict(self.headers)
        headers.update(kwargs.pop("headers", {}))
        try:
            response = requests.request(method, self.url + path, headers=headers,
                                        timeout=60, allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise StorageError("저장소에 연결하지 못했습니다. 잠시 후 다시 시도하세요.") from None
        if not 200 <= response.status_code < 300:
            raise StorageError(f"저장소 요청 실패({response.status_code}). 연결 설정과 저장소 초기화를 확인하세요.")
        return response

    def save(self, content, record, record_id=None):
        record_id = record_id or uuid4().hex
        # Stable IDs allow a legacy import to be retried safely.
        path = f"{record_id}/result.xlsx"
        self.request("POST", f"/storage/v1/object/{self.bucket}/{quote(path, safe='/')}",
                     data=content, headers={"Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "x-upsert": "true"})
        payload = dict(record, id=record_id, storage_path=path, deleted_at=None)
        payload.pop("result_file_path", None)
        payload.setdefault("created_at", datetime.now(timezone.utc).isoformat())
        # Never delete a successfully uploaded file on an ambiguous network failure.
        # A retry with the same record ID completes the metadata write.
        self.request("POST", f"/rest/v1/{self.table}?on_conflict=id", json=payload,
                     headers={"Prefer": "resolution=merge-duplicates,return=minimal"})
        return dict(payload, result_file_path=path)

    def list(self):
        records = []
        offset = 0
        while True:
            batch = self.request("GET", f"/rest/v1/{self.table}", params={
                "select": "*", "deleted_at": "is.null", "order": "created_at.desc,id.desc",
                "limit": 500, "offset": offset}).json()
            records.extend(dict(row, result_file_path=row["storage_path"]) for row in batch)
            if len(batch) < 500:
                return records
            offset += len(batch)

    def download(self, record):
        path = quote(record["storage_path"], safe="/")
        return self.request("GET", f"/storage/v1/object/{self.bucket}/{path}").content

    def delete(self, record_id):
        # Soft-delete: retain the file so an accidental action is recoverable.
        rows = self.request("PATCH", f"/rest/v1/{self.table}",
                            params={"id": f"eq.{record_id}", "deleted_at": "is.null"},
                            json={"deleted_at": datetime.now(timezone.utc).isoformat()},
                            headers={"Prefer": "return=representation"}).json()
        return bool(rows)
