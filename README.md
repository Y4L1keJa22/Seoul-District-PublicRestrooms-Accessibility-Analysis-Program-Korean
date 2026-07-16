# Seoul-District-PublicRestrooms-Accessibility-Analysis-Program-Korean
서울시 공중화장실 접근성 부족지역 분석 프로그램. 가천대학교 글로벌캠퍼스, 컴퓨터공학과 2학년 2학기에 빅데이터분석개론 강의에 개발하게 된 학기말 팀(6명) 프로젝트입니다. 저는 참고로 제공받은 데이터를 활용하며 "코딩 및 주석처리" 역할을 맡았습니다.

이 프로그램은 서울에서 선택한 시간과 검색한 지역에 따라 범위를 자치구 또는 행정동 구역으로 잡아서, 이 구역에 공중화장실을 분석해서 검색한 지역(지점)과 가장 가까운 5개의 공중화장실을 찾아내서, 접근성 점수/인구/부족도 등급/설치 우선도개방시간/유형/주소/거리 관련 분석 결과 및 그래프를 추출합니다. 프로그램은 파이썬 프로그래밍 언어를 통해 .csv,.json,.html,.geojson 형태의 데이터들을 분석해서 지도 API 없이 위치 추적 및 접근성 관련 결과를 추출해낼 수 있었습니다. 그래도 네이버 API와 같은 지도 API가 있었으면 정확성 및 검색 범위를 향상시킬 수 있었던 단점이 있습니다. 이 대신 프로그램은 API에 의존할 필요가 없어서 '계정' 유지 및 코드 관리가 더 좋은 장점이 있습니다.

필수 준비:

1. 아래에 제공한 활용 데이터 출처 링크들을 접속 -> 활용 데이터 다운로드. 정확성을 위해 데이터 양이 워낙 커서 참고하시기 바랍니다.
2. 다운로드해야할 활용 데이터: toilet_score.csv, toilet_score_report.html, dong_boundary_1.geojson, 서울시 공중화장실 위치정보.csv, 서울시 공중화장실 위치정보.json, 자치구 단위 서울 생활인구(내국인).csv, 집계구 단위 서울 생활인구(내국인).csv = 총 7개입니다
3. 파일/폴더들 옆에 일반적인 파이썬 venv 만들기

*파일 실행 방법* (cmd 터미널에서 파일/폴더들보다 높은 부모 디렉터리에 있는 상태):

1. 팀프로젝트_빅분개/projectEnvironment/Scripts/activate
=> (부모 디렉터리인 팀프로젝트_빅분개 디렉터리에 있는 상태) cd projectEnvironment => cd Scripts => activate

2. (cd ../../해서 다시 팀프로젝트_빅분개 디렉터리에 있는 상태) streamlit run ancient_monarch.py
cmd 터미널에 이렇게 출력될 것입니다
=>
날짜 시간 Uvicorn server started on IP주소:포트

  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:포트
  Network URL: http://네트워크IP주소

3. 화면에 뜬 웹페이지 확인하기

활용 데이터 출처:

https://data.seoul.go.kr/dataList/OA-22586/S/1/datasetView.do
- 서울시 공중 화장실 위치 정보

https://data.seoul.go.kr/dataList/OA-14991/S/1/datasetView.do
- 행정동 단위 서울 생활 인구

https://data.seoul.go.kr/dataList/OA-15439/S/1/datasetView.do
- 자치구 단위 서울 생활 인구

https://data.seoul.go.kr/dataList/OA-14979/F/1/datasetView.do
- 서울 생활 인구

https://data.seoul.go.kr/bsp/wgs/dataView/data300View/10080.do
- 서울 행정구역 법정동 경계 데이터(지도 시각화, 법정동 목록, 자치구 집계)

실행 결과:
<img width="959" height="440" alt="image" src="https://github.com/user-attachments/assets/72ff1fb7-9c70-4f66-af00-86bae8fe24a4" />
<img width="941" height="352" alt="image" src="https://github.com/user-attachments/assets/70351904-0bfe-4183-a408-92144019a8e2" />
<img width="922" height="373" alt="image" src="https://github.com/user-attachments/assets/f697d3c7-5574-43a5-af7c-9e9f68790e1f" />
<img width="911" height="224" alt="image" src="https://github.com/user-attachments/assets/eeec2bad-e218-4f03-9cf0-52be399339c6" />


최근 수정일: 2026년 6월 15일

연락처: stasishat06@gmail.com
