# 웹앱 배포

## GitHub

이 폴더를 별도 비공개 저장소 `kakao-route-webapp`로 업로드합니다.
`.env`, 실제 `secrets.toml`, DB, 조회 결과 엑셀, 압축파일은 업로드하지 않습니다.
원본 압축파일의 기존 조회 데이터는 이 배포 폴더에 포함하지 않았습니다.

## Streamlit Community Cloud

1. https://share.streamlit.io/ 에 로그인합니다.
2. 새 앱에서 GitHub 저장소와 배포 브랜치, 진입 파일 `app.py`를 선택합니다.
3. Advanced settings에서 Python 3.12를 선택하고 Secrets에 아래 항목을 등록합니다.
   `.streamlit/secrets.toml.example`의 빈 값을 실제 값으로 채웁니다.
   - `KAKAO_LOCAL_REST_API_KEY`: 카카오 주소 검색 키
   - `KAKAO_MOBILITY_REST_API_KEY`: 카카오 길찾기 키
   - `APP_PASSWORD`: 접속 비밀번호
4. Deploy 후 생성된 HTTPS 주소에서 로그인과 실제 노선 조회를 확인합니다.

키와 비밀번호는 소스코드 또는 README에 기록하지 않습니다.
비밀번호를 아는 사람은 동일한 조회 이력에 접근합니다.

## 데이터 보관

GitHub는 프로그램의 버전 관리용입니다. 실행 중 생성된 DB와 결과 파일을 자동으로 저장하지 않습니다.
현재 앱은 SQLite와 결과 엑셀을 사용합니다. Community Cloud 로컬 저장소의 영구 보존을 전제로 사용하지 마세요.
중요한 결과는 다운로드해야 합니다. 지속적인 이력 관리에는 외부 DB/파일 저장소 연결 또는 영구 디스크를 지원하는 호스팅이 필요합니다.
영구 디스크를 사용하는 서버에서는 `DATA_DIR`을 디스크 마운트 경로로 지정하면 그 아래 `database/`, `results/`에 저장합니다.
디렉터리 설정만으로 영구 디스크가 생성되지는 않습니다.

## 로컬 실행

Python 3.12 이상에서 `pip install -r requirements.txt`를 실행합니다.
`.streamlit/secrets.toml.example`을 `.streamlit/secrets.toml`로 복사하고 값을 입력한 뒤 `streamlit run app.py`로 실행합니다.

## 배포 전 검증 범위

실제 API 키가 원본 압축에 없어 실제 카카오 응답 검증은 키 등록 후 수행해야 합니다.
