"""Import only result workbooks from a legacy backup; never extract ZIP paths."""
import hashlib
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import ZipFile
import pandas as pd
from cloud_history import CloudHistory


def legacy_results(data):
    if len(data) > 50 * 1024 * 1024:
        raise ValueError("백업 ZIP은 50MB 이하로 올려주세요.")
    with ZipFile(BytesIO(data)) as archive:
        entries = [i for i in archive.infolist()
                   if "results" in PurePosixPath(i.filename).parts
                   and i.filename.lower().endswith(".xlsx")]
        if not entries or len(entries) > 100 or sum(i.file_size for i in entries) > 100 * 1024 * 1024:
            raise ValueError("results 폴더의 엑셀 1~100개, 압축 해제 크기 합계 100MB 이하만 복원할 수 있습니다.")
        results = []
        for entry in entries:
            name = PurePosixPath(entry.filename).name
            if not entry.flag_bits & 0x800:
                try:
                    name = name.encode("cp437").decode("cp949")
                except (UnicodeError, LookupError):
                    pass
            content = archive.read(entry)
            with ZipFile(BytesIO(content)) as workbook_zip:
                if sum(i.file_size for i in workbook_zip.infolist()) > 100 * 1024 * 1024:
                    raise ValueError("엑셀 압축 해제 크기가 너무 큽니다.")
            book = pd.ExcelFile(BytesIO(content))
            frame = pd.read_excel(book, sheet_name="조회결과" if "조회결과" in book.sheet_names else 0)
            count = len(frame)
            ok = int(frame["API상태"].eq("OK").sum()) if "API상태" in frame else 0
            results.append((hashlib.sha256(content).hexdigest(), content, {
                "job_name": name.removesuffix(".xlsx"), "original_file_name": name,
                "result_file_name": name, "row_count": count,
                "success_count": ok, "failure_count": count - ok,
            }))
        return results


def import_results(results):
    store = CloudHistory()
    existing = {r["id"] for r in store.list()}
    imported = 0
    for identity, content, record in results:
        if identity not in existing:
            store.save(content, record, record_id=identity)
            existing.add(identity)
            imported += 1
    return imported
