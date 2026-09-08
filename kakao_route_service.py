import math
import os
import re
import time
from functools import lru_cache
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests
from settings import get_setting

from database import (
    get_address_cache,
    get_route_cache,
    initialize_database,
    save_address_cache,
    save_route_cache,
)

initialize_database()

KAKAO_LOCAL_REST_API_KEY = get_setting("KAKAO_LOCAL_REST_API_KEY")
KAKAO_MOBILITY_REST_API_KEY = get_setting("KAKAO_MOBILITY_REST_API_KEY")

SLEEP_SEC = 0.05

CAR_FUEL = "DIESEL"
CAR_HIPASS = True

VEHICLE_TYPE_MAP = {
    "1톤": 1,
    "2.5톤": 2,
    "3.5톤": 2,
    "5톤": 3,
    "8톤": 3,
    "11톤": 4,
    "25톤": 4,
    "트레일러": 5,
}

KOR_LON_MIN, KOR_LON_MAX = 124.0, 132.0
KOR_LAT_MIN, KOR_LAT_MAX = 33.0, 39.0


def check_api_keys() -> None:
    if not KAKAO_LOCAL_REST_API_KEY or not KAKAO_MOBILITY_REST_API_KEY:
        raise RuntimeError(
            "카카오 API 키가 설정되지 않았습니다. 배포 Secrets 또는 .env 파일에 "
            "KAKAO_LOCAL_REST_API_KEY, KAKAO_MOBILITY_REST_API_KEY를 입력하세요."
        )


def is_missing(value) -> bool:
    return value is None or (
        isinstance(value, float) and math.isnan(value)
    )


def in_korea_bbox(x: float, y: float) -> bool:
    return (
        KOR_LON_MIN <= x <= KOR_LON_MAX
        and KOR_LAT_MIN <= y <= KOR_LAT_MAX
    )


def normalize_xy(
    x,
    y,
) -> Tuple[Optional[float], Optional[float], Optional[str]]:
    if is_missing(x) or is_missing(y):
        return None, None, "좌표없음"

    try:
        x = float(x)
        y = float(y)
    except (TypeError, ValueError):
        return None, None, "좌표형식오류"

    if in_korea_bbox(x, y):
        return round(x, 6), round(y, 6), None

    if in_korea_bbox(y, x):
        return round(y, 6), round(x, 6), "좌표스왑수정"

    return None, None, "좌표범위이탈"


def _request_with_retry(
    url: str,
    headers=None,
    params=None,
    max_retry: int = 3,
    timeout: int = 20,
):
    for attempt in range(max_retry):
        try:
            response = requests.get(
                url,
                headers=headers,
                params=params,
                timeout=timeout,
            )
            response.raise_for_status()
            return response
        except Exception:
            if attempt == max_retry - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def normalize_address_text(address: str) -> str:
    """공백·줄바꿈·탭과 일부 구분기호를 정리한다."""
    text = "" if address is None else str(address)
    text = text.replace("\u3000", " ")
    text = re.sub(r"[\r\n\t]+", " ", text)
    text = re.sub(r"[|·ㆍ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ,;")




SIDO_ALIASES = {
    "서울": "서울특별시", "서울시": "서울특별시", "서울특별시": "서울특별시",
    "부산": "부산광역시", "부산시": "부산광역시", "부산광역시": "부산광역시",
    "대구": "대구광역시", "대구시": "대구광역시", "대구광역시": "대구광역시",
    "인천": "인천광역시", "인천시": "인천광역시", "인천광역시": "인천광역시",
    "광주": "광주광역시", "광주시": "광주광역시", "광주광역시": "광주광역시",
    "대전": "대전광역시", "대전시": "대전광역시", "대전광역시": "대전광역시",
    "울산": "울산광역시", "울산시": "울산광역시", "울산광역시": "울산광역시",
    "세종": "세종특별자치시", "세종시": "세종특별자치시", "세종특별자치시": "세종특별자치시",
    "경기": "경기도", "경기도": "경기도",
    "강원": "강원특별자치도", "강원도": "강원특별자치도", "강원특별자치도": "강원특별자치도",
    "충북": "충청북도", "충청북도": "충청북도",
    "충남": "충청남도", "충청남도": "충청남도",
    "전북": "전북특별자치도", "전라북도": "전북특별자치도", "전북특별자치도": "전북특별자치도",
    "전남": "전라남도", "전라남도": "전라남도",
    "경북": "경상북도", "경상북도": "경상북도",
    "경남": "경상남도", "경상남도": "경상남도",
    "제주": "제주특별자치도", "제주도": "제주특별자치도", "제주특별자치도": "제주특별자치도",
}


def insert_admin_spaces(address: str) -> str:
    """붙어 있는 시·군·구/읍·면/리 경계에 제한적으로 공백을 추가한다."""
    text = normalize_address_text(address)
    previous = None

    # 예: 화성시팔탄면 -> 화성시 팔탄면, 진천군초평면 -> 진천군 초평면
    patterns = [
        (r"([가-힣]{1,12}(?:시|군|구))(?=[가-힣]{1,12}(?:읍|면|동)\b)", r"\1 "),
        (r"([가-힣]{1,12}(?:읍|면))(?=[가-힣]{1,12}리\b)", r"\1 "),
        (r"([가-힣]{1,12}(?:구))(?=[가-힣]{1,12}동\b)", r"\1 "),
    ]

    while previous != text:
        previous = text
        for pattern, replacement in patterns:
            text = re.sub(pattern, replacement, text)
        text = normalize_address_text(text)

    return text


def extract_admin_components(address: str) -> Dict[str, str]:
    """주소 문자열에서 비교 가능한 행정구역 단서를 추출한다."""
    text = insert_admin_spaces(address)
    tokens = text.split()
    result = {"시도": "", "시군구": "", "읍면동": "", "리": ""}

    for token in tokens:
        clean = re.sub(r"[^가-힣]", "", token)
        if not clean:
            continue
        if not result["시도"] and clean in SIDO_ALIASES:
            result["시도"] = SIDO_ALIASES[clean]
            continue
        if not result["시군구"] and re.fullmatch(r"[가-힣]{1,12}(?:시|군|구)", clean):
            # 광역시 토큰은 시군구로 중복 저장하지 않는다.
            if clean not in SIDO_ALIASES:
                result["시군구"] = clean
                continue
        if not result["읍면동"] and re.fullmatch(r"[가-힣]{1,12}(?:읍|면|동)", clean):
            result["읍면동"] = clean
            continue
        if not result["리"] and re.fullmatch(r"[가-힣]{1,12}리", clean):
            result["리"] = clean

    # 공백이 잘못된 문자열에서도 직접 탐색한다.
    compact = re.sub(r"\s+", "", text)
    if not result["시군구"]:
        match = re.search(r"([가-힣]{1,12}(?:시|군|구))(?=[가-힣])", compact)
        if match and match.group(1) not in SIDO_ALIASES:
            result["시군구"] = match.group(1)
    if not result["읍면동"]:
        match = re.search(r"([가-힣]{1,12}(?:읍|면|동))(?=[가-힣0-9])", compact)
        if match:
            result["읍면동"] = match.group(1)
    if not result["리"]:
        match = re.search(r"([가-힣]{1,12}리)(?=산?\d|\s|$)", compact)
        if match:
            result["리"] = match.group(1)

    return result


def validate_keyword_match(original: str, matched_address: str) -> Tuple[bool, str]:
    """키워드 검색 결과가 원본 주소의 핵심 행정구역과 일치하는지 검사한다."""
    source = extract_admin_components(original)
    target = extract_admin_components(matched_address)

    checked = 0
    matched = 0
    labels = []

    for key in ("시도", "시군구", "읍면동"):
        source_value = source.get(key, "")
        target_value = target.get(key, "")
        if not source_value:
            continue
        checked += 1
        if target_value == source_value:
            matched += 1
            labels.append(f"{key} 일치")
        elif target_value:
            return False, f"{key} 불일치({source_value} ≠ {target_value})"
        else:
            labels.append(f"{key} 확인불가")

    # 시군구와 읍면동이 모두 있는 원본은 두 항목이 모두 맞아야 자동 채택한다.
    required = sum(bool(source.get(key)) for key in ("시군구", "읍면동"))
    if required >= 2:
        if target.get("시군구") != source.get("시군구") or target.get("읍면동") != source.get("읍면동"):
            return False, "시군구·읍면동 동시 일치 조건 미충족"

    if checked == 0:
        return False, "원본에서 비교할 행정구역을 추출하지 못함"
    if matched == 0:
        return False, "일치하는 행정구역 없음"

    return True, ", ".join(labels)

def remove_bracket_text(address: str) -> str:
    """괄호·대괄호·중괄호 안의 부가정보를 제거한다."""
    text = address
    previous = None

    while previous != text:
        previous = text
        text = re.sub(r"\([^()]*\)", " ", text)
        text = re.sub(r"\[[^\[\]]*\]", " ", text)
        text = re.sub(r"\{[^{}]*\}", " ", text)

    return normalize_address_text(text)


DETAIL_PATTERNS = [
    r"\b지하\s*\d+\s*층\b",
    r"\bB\d+\s*층?\b",
    r"\b\d+\s*층\b",
    r"\b\d+\s*호\b",
    r"\b\d+\s*동\b",
    r"\b[A-Za-z가-힣]\s*동\b",
    r"\b\d+\s*번\s*도크\b",
    r"\b도크\s*\d+\s*번?\b",
    r"\b게이트\s*\d+\s*번?\b",
    r"\b\d+\s*번\s*게이트\b",
]

DETAIL_WORDS = [
    "하역장",
    "상하차장",
    "경비실",
    "후문",
    "정문",
    "입구",
    "출입구",
    "주차장",
    "사무실",
    "본관",
    "별관",
    "창고동",
]


def remove_detail_location(address: str) -> str:
    """층·호·동·도크·하역장 등 상세 위치 표현을 제거한다."""
    text = address

    for pattern in DETAIL_PATTERNS:
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE)

    for word in DETAIL_WORDS:
        text = re.sub(
            rf"(?<![가-힣A-Za-z0-9]){re.escape(word)}(?![가-힣A-Za-z0-9])",
            " ",
            text,
        )

    return normalize_address_text(text)


ROAD_NUMBER_PATTERN = re.compile(
    r"^(.*?"
    r"(?:대로|로|길|번길|거리)\s*"
    r"\d+(?:-\d+)?"
    r")(?:\s+.*)?$"
)

JIBUN_PATTERN = re.compile(
    r"^(.*?"
    r"(?:읍|면|동|리|가)\s*"
    r"(?:산\s*)?\d+(?:-\d+)?"
    r")(?:\s+.*)?$"
)


def remove_building_name(address: str) -> str:
    """
    도로명 번지 또는 지번 뒤에 붙은 건물명·센터명을 제거한다.
    주소 숫자까지 명확히 인식되는 경우에만 잘라 과도한 축약을 방지한다.
    """
    text = normalize_address_text(address)

    road_match = ROAD_NUMBER_PATTERN.match(text)
    if road_match:
        return normalize_address_text(road_match.group(1))

    jibun_match = JIBUN_PATTERN.match(text)
    if jibun_match:
        return normalize_address_text(jibun_match.group(1))

    return text


def _unique_candidates(
    candidates: Iterable[Tuple[str, str]],
) -> List[Tuple[str, str]]:
    seen = set()
    result = []

    for step, address in candidates:
        cleaned = normalize_address_text(address)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append((step, cleaned))

    return result


def build_address_candidates(original_address: str) -> List[Tuple[str, str]]:
    """
    정확도가 높은 순서대로 주소검색 후보를 만든다.

    1. 원본조회
    2. 기본정리
    3. 행정구역공백보정
    4. 괄호제거
    5. 상세주소제거
    6. 건물명제거
    """
    original = "" if original_address is None else str(original_address)
    basic = normalize_address_text(original)
    admin_spaced = insert_admin_spaces(basic)
    no_brackets = remove_bracket_text(admin_spaced)
    no_detail = remove_detail_location(no_brackets)
    no_building = remove_building_name(no_detail)

    return _unique_candidates([
        ("원본조회", original),
        ("기본정리", basic),
        ("행정구역공백보정", admin_spaced),
        ("괄호제거", no_brackets),
        ("상세주소제거", no_detail),
        ("건물명제거", no_building),
    ])


@lru_cache(maxsize=20000)
def _address_search_cached(
    query: str,
) -> Tuple[Optional[float], Optional[float], str]:
    check_api_keys()

    url = "https://dapi.kakao.com/v2/local/search/address.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_LOCAL_REST_API_KEY}"}
    params = {"query": query}

    response = _request_with_retry(
        url,
        headers=headers,
        params=params,
        timeout=10,
    )
    documents = response.json().get("documents", [])

    if not documents:
        return None, None, ""

    document = documents[0]

    try:
        x = float(document["x"])
        y = float(document["y"])
    except (KeyError, TypeError, ValueError):
        return None, None, ""

    matched_address = (
        (document.get("road_address") or {}).get("address_name")
        or (document.get("address") or {}).get("address_name")
        or document.get("address_name")
        or query
    )

    return x, y, matched_address


@lru_cache(maxsize=20000)
def _keyword_search_cached(
    query: str,
) -> Tuple[Tuple[float, float, str, str, str], ...]:
    """정확도순 키워드 후보를 최대 5개 반환한다.

    반환값: 경도, 위도, 도로명주소, 지번주소, 장소명
    """
    check_api_keys()

    url = "https://dapi.kakao.com/v2/local/search/keyword.json"
    headers = {"Authorization": f"KakaoAK {KAKAO_LOCAL_REST_API_KEY}"}
    params = {
        "query": query,
        "size": 5,
        "sort": "accuracy",
    }

    response = _request_with_retry(
        url,
        headers=headers,
        params=params,
        timeout=10,
    )
    documents = (response.json() or {}).get("documents") or []
    results = []

    for document in documents:
        try:
            x = float(document["x"])
            y = float(document["y"])
        except (KeyError, TypeError, ValueError):
            continue

        road_address = document.get("road_address_name") or ""
        jibun_address = document.get("address_name") or ""
        place_name = document.get("place_name") or ""
        results.append((x, y, road_address, jibun_address, place_name))

    return tuple(results)


def _call_cached_search(
    search_function,
    query: str,
) -> Tuple[
    Optional[float],
    Optional[float],
    str,
    bool,
]:
    before_hits = search_function.cache_info().hits
    x, y, matched_address = search_function(query)
    after_hits = search_function.cache_info().hits
    cache_used = after_hits > before_hits

    return x, y, matched_address, cache_used


def geocode_with_cleaning(address: str) -> Dict[str, Any]:
    """
    주소를 단계적으로 정제해 좌표를 조회하고,
    실제 조회주소·정제단계·캐시사용여부·소요시간을 반환한다.
    """
    started_at = time.perf_counter()
    original_address = "" if address is None else str(address)
    cache_key = normalize_address_text(original_address)

    if cache_key:
        cached = get_address_cache(cache_key)
        if cached is not None:
            return {
                "원본주소": original_address,
                "조회주소": cached["matched_address"],
                "API검색어": cached["search_query"],
                "정제단계": cached["cleaning_step"],
                "좌표상태": cached["coordinate_status"],
                "경도": cached["longitude"],
                "위도": cached["latitude"],
                "좌표메모": cached["coordinate_note"],
                "캐시사용여부": "Y",
                "조회소요시간_초": round(
                    time.perf_counter() - started_at, 4
                ),
            }

    candidates = build_address_candidates(original_address)

    if not candidates:
        return {
            "원본주소": original_address,
            "조회주소": "",
            "API검색어": "",
            "정제단계": "조회실패",
            "좌표상태": "실패",
            "경도": None,
            "위도": None,
            "좌표메모": "빈 주소",
            "캐시사용여부": "N",
            "조회소요시간_초": round(time.perf_counter() - started_at, 4),
        }

    cache_used_any = False

    for step, query in candidates:
        x, y, matched_address, cache_used = _call_cached_search(
            _address_search_cached,
            query,
        )
        cache_used_any = cache_used_any or cache_used

        nx, ny, note = normalize_xy(x, y)
        if nx is not None and ny is not None:
            coordinate_status = (
                "성공"
                if step == "원본조회"
                else "정제후성공"
            )
            result = {
                "원본주소": original_address,
                "조회주소": matched_address or query,
                "API검색어": query,
                "정제단계": step,
                "좌표상태": coordinate_status,
                "경도": nx,
                "위도": ny,
                "좌표메모": note or "",
                "캐시사용여부": "Y" if cache_used else "N",
                "조회소요시간_초": round(
                    time.perf_counter() - started_at,
                    4,
                ),
            }
            if cache_key:
                save_address_cache(cache_key, result)
            return result

    # 주소검색이 모두 실패했을 때 장소명 키워드 검색 후 행정구역 일치 검증
    keyword_queries = _unique_candidates([
        ("장소명검색", insert_admin_spaces(normalize_address_text(original_address))),
        ("장소명검색", insert_admin_spaces(remove_bracket_text(original_address))),
        ("장소명검색", insert_admin_spaces(remove_detail_location(remove_bracket_text(original_address)))),
    ])

    keyword_reject_reasons = []

    for _, query in keyword_queries:
        before_hits = _keyword_search_cached.cache_info().hits
        keyword_results = _keyword_search_cached(query)
        after_hits = _keyword_search_cached.cache_info().hits
        cache_used = after_hits > before_hits
        cache_used_any = cache_used_any or cache_used

        for x, y, road_address, jibun_address, place_name in keyword_results:
            # 도로명주소에는 읍면동이 생략되는 경우가 많다.
            # 따라서 카카오가 함께 반환한 지번주소를 우선 검증하고,
            # 지번주소가 없거나 통과하지 못한 경우에만 도로명주소를 검증한다.
            validation_attempts = []
            if jibun_address:
                validation_attempts.append(("지번주소", jibun_address))
            if road_address and road_address != jibun_address:
                validation_attempts.append(("도로명주소", road_address))

            accepted = False
            validation_note = "검증 가능한 주소 없음"
            validation_basis = ""
            reject_notes = []

            for basis, candidate_address in validation_attempts:
                candidate_accepted, candidate_note = validate_keyword_match(
                    original_address,
                    candidate_address,
                )
                if candidate_accepted:
                    accepted = True
                    validation_note = candidate_note
                    validation_basis = basis
                    break
                reject_notes.append(f"{basis} {candidate_address}: {candidate_note}")

            if not accepted:
                display_candidate = road_address or jibun_address or place_name or query
                keyword_reject_reasons.append(
                    f"{display_candidate}: "
                    + (" / ".join(reject_notes) if reject_notes else validation_note)
                )
                continue

            nx, ny, note = normalize_xy(x, y)
            if nx is None or ny is None:
                continue

            memo_parts = [
                f"장소명 결과 {validation_basis} 기준 행정구역 검증 통과({validation_note})"
            ]
            if jibun_address:
                memo_parts.append(f"지번주소: {jibun_address}")
            if place_name:
                memo_parts.append(f"장소명: {place_name}")
            if note:
                memo_parts.append(note)

            result = {
                "원본주소": original_address,
                "조회주소": road_address or jibun_address or place_name or query,
                "API검색어": query,
                "정제단계": "장소명검색_검증통과",
                "좌표상태": "정제후성공",
                "경도": nx,
                "위도": ny,
                "좌표메모": " / ".join(memo_parts),
                "캐시사용여부": "Y" if cache_used else "N",
                "조회소요시간_초": round(
                    time.perf_counter() - started_at,
                    4,
                ),
            }
            if cache_key:
                save_address_cache(cache_key, result)
            return result

    return {
        "원본주소": original_address,
        "조회주소": "",
        "API검색어": keyword_queries[-1][1] if keyword_queries else "",
        "정제단계": "조회실패",
        "좌표상태": "실패",
        "경도": None,
        "위도": None,
        "좌표메모": (
            "장소명 후보가 행정구역 검증을 통과하지 못함: "
            + " | ".join(keyword_reject_reasons[:3])
            if keyword_reject_reasons
            else "주소 및 장소명 검색 결과 없음"
        ),
        "캐시사용여부": "Y" if cache_used_any else "N",
        "조회소요시간_초": round(
            time.perf_counter() - started_at,
            4,
        ),
    }


@lru_cache(maxsize=50000)
def _route_distance_toll_cached(
    ox: float,
    oy: float,
    dx: float,
    dy: float,
    car_type: int,
) -> Tuple[Optional[float], Optional[float], Optional[int]]:
    check_api_keys()

    url = "https://apis-navi.kakaomobility.com/v1/directions"
    headers = {"Authorization": f"KakaoAK {KAKAO_MOBILITY_REST_API_KEY}"}
    params = {
        "origin": f"{ox},{oy}",
        "destination": f"{dx},{dy}",
        "priority": "RECOMMEND",
        "car_type": car_type,
        "car_fuel": CAR_FUEL,
        "car_hipass": str(CAR_HIPASS).lower(),
        "alternatives": "false",
        "summary": "true",
    }

    response = _request_with_retry(
        url,
        headers=headers,
        params=params,
        timeout=20,
    )
    data = response.json() or {}
    routes = data.get("routes") or []

    if not routes or routes[0].get("result_code", 0) != 0:
        return None, None, None

    summary = routes[0].get("summary") or {}
    dist_m = summary.get("distance")
    dur_s = summary.get("duration")
    toll = (summary.get("fare") or {}).get("toll")

    return dist_m, dur_s, toll


def route_distance_toll(
    origin_xy,
    destination_xy,
    car_type: int,
) -> Tuple[
    Optional[float],
    Optional[float],
    Optional[int],
    bool,
]:
    ox, oy = origin_xy
    dx, dy = destination_xy

    if any(is_missing(v) for v in (ox, oy, dx, dy)):
        return None, None, None, False

    origin_lon = round(float(ox), 6)
    origin_lat = round(float(oy), 6)
    destination_lon = round(float(dx), 6)
    destination_lat = round(float(dy), 6)
    normalized_car_type = int(car_type)

    db_result = get_route_cache(
        origin_lon,
        origin_lat,
        destination_lon,
        destination_lat,
        normalized_car_type,
    )
    if db_result is not None:
        return (*db_result, True)

    before_hits = _route_distance_toll_cached.cache_info().hits
    result = _route_distance_toll_cached(
        origin_lon,
        origin_lat,
        destination_lon,
        destination_lat,
        normalized_car_type,
    )
    after_hits = _route_distance_toll_cached.cache_info().hits
    memory_cache_used = after_hits > before_hits

    distance_m, duration_s, toll_won = result
    if distance_m is not None:
        save_route_cache(
            origin_lon,
            origin_lat,
            destination_lon,
            destination_lat,
            normalized_car_type,
            float(distance_m),
            float(duration_s or 0),
            int(toll_won or 0),
        )

    return (*result, memory_cache_used)


def _endpoint_result(
    prefix: str,
    geocode_result: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        f"{prefix}_원본주소": geocode_result["원본주소"],
        f"{prefix}_조회주소": geocode_result["조회주소"],
        f"{prefix}_API검색어": geocode_result["API검색어"],
        f"{prefix}_정제단계": geocode_result["정제단계"],
        f"{prefix}_좌표상태": geocode_result["좌표상태"],
        f"{prefix}_경도": geocode_result["경도"],
        f"{prefix}_위도": geocode_result["위도"],
        f"{prefix}_좌표메모": geocode_result["좌표메모"],
        f"{prefix}_캐시사용여부": geocode_result["캐시사용여부"],
        f"{prefix}_조회소요시간_초": geocode_result["조회소요시간_초"],
    }


def lookup_route(
    origin: str,
    destination: str,
    vehicle_name: str,
) -> Dict[str, Any]:
    total_started_at = time.perf_counter()

    vehicle_name = str(vehicle_name).strip()
    car_type = VEHICLE_TYPE_MAP.get(vehicle_name)

    origin_result = geocode_with_cleaning(origin)
    destination_result = geocode_with_cleaning(destination)

    result = {
        "출발지": origin,
        "도착지": destination,
        "차종": vehicle_name,
    }
    result.update(_endpoint_result("출발지", origin_result))
    result.update(_endpoint_result("도착지", destination_result))

    if car_type is None:
        result.update({
            "적용_car_type": None,
            "주행거리_km": None,
            "예상시간_분": None,
            "톨비_원": None,
            "경로캐시사용여부": "N",
            "API상태": f"지원하지 않는 차종: {vehicle_name}",
            "전체조회소요시간_초": round(
                time.perf_counter() - total_started_at,
                4,
            ),
        })
        return result

    result["적용_car_type"] = car_type

    ox = origin_result["경도"]
    oy = origin_result["위도"]
    dx = destination_result["경도"]
    dy = destination_result["위도"]

    if any(is_missing(v) for v in (ox, oy, dx, dy)):
        result.update({
            "주행거리_km": None,
            "예상시간_분": None,
            "톨비_원": None,
            "경로캐시사용여부": "N",
            "API상태": "지오코딩 실패",
            "전체조회소요시간_초": round(
                time.perf_counter() - total_started_at,
                4,
            ),
        })
        return result

    if abs(ox - dx) < 1e-6 and abs(oy - dy) < 1e-6:
        result.update({
            "주행거리_km": 0.0,
            "예상시간_분": 0.0,
            "톨비_원": 0,
            "경로캐시사용여부": "N",
            "API상태": "자기지선",
            "전체조회소요시간_초": round(
                time.perf_counter() - total_started_at,
                4,
            ),
        })
        return result

    dist_m, dur_s, toll, route_cache_used = route_distance_toll(
        (ox, oy),
        (dx, dy),
        car_type,
    )

    if dist_m is None:
        result.update({
            "주행거리_km": None,
            "예상시간_분": None,
            "톨비_원": None,
            "경로캐시사용여부": "Y" if route_cache_used else "N",
            "API상태": "경로 탐색 불가",
            "전체조회소요시간_초": round(
                time.perf_counter() - total_started_at,
                4,
            ),
        })
        return result

    result.update({
        "주행거리_km": round(dist_m / 1000, 2),
        "예상시간_분": round((dur_s or 0) / 60, 1),
        "톨비_원": int(toll or 0),
        "경로캐시사용여부": "Y" if route_cache_used else "N",
        "API상태": "OK",
        "전체조회소요시간_초": round(
            time.perf_counter() - total_started_at,
            4,
        ),
    })

    return result


def lookup_routes_from_df(
    df: pd.DataFrame,
    selected_vehicles: Optional[Iterable[str]] = None,
    progress_callback: Optional[Callable[[int, int, Dict[str, Any]], None]] = None,
) -> pd.DataFrame:
    """
    원본 칼럼을 유지한 채 조회 결과 칼럼을 추가한다.

    selected_vehicles가 지정되면 화면 선택값을 우선 적용한다.
    여러 차종을 선택하면 각 원본 행을 차종별로 반복 조회한다.
    selected_vehicles가 없으면 원본의 '차종' 칼럼을 사용하며,
    해당 칼럼도 없으면 5톤을 기본값으로 사용한다.
    """
    source_df = df.copy()
    source_df.columns = source_df.columns.map(str).str.strip()

    required = {"출발지", "도착지"}
    if not required.issubset(source_df.columns):
        raise ValueError(
            "엑셀에는 '출발지', '도착지' 컬럼이 반드시 있어야 합니다."
        )

    vehicles = [
        str(value).strip()
        for value in (selected_vehicles or [])
        if str(value).strip()
    ]

    output_rows = []
    total_count = len(source_df) * (len(vehicles) if vehicles else 1)
    completed_count = 0

    for _, row in source_df.iterrows():
        row_dict = row.to_dict()

        if vehicles:
            row_vehicles = vehicles
        else:
            raw_vehicle = row_dict.get("차종", "5톤")
            if pd.isna(raw_vehicle) or not str(raw_vehicle).strip():
                raw_vehicle = "5톤"
            row_vehicles = [str(raw_vehicle).strip()]

        for vehicle_name in row_vehicles:
            result = lookup_route(
                str(row_dict.get("출발지", "")),
                str(row_dict.get("도착지", "")),
                vehicle_name,
            )

            combined = dict(row_dict)
            combined.update(result)
            output_rows.append(combined)
            completed_count += 1

            if progress_callback is not None:
                progress_callback(
                    completed_count,
                    total_count,
                    {
                        "출발지": row_dict.get("출발지", ""),
                        "도착지": row_dict.get("도착지", ""),
                        "차종": vehicle_name,
                        "API상태": result.get("API상태", ""),
                    },
                )

            time.sleep(SLEEP_SEC)

    return pd.DataFrame(output_rows)
