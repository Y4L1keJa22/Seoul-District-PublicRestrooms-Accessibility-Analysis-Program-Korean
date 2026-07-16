# Seoul-District-PublicRestrooms-Accessibility-Analysis-Program-Korean
서울시 공중화장실 접근성 부족지역 분석 프로그램. 가천대학교 글로벌캠퍼스, 컴퓨터공학과 2학년 2학기에 빅데이터분석개론을 수강하면서 개발하게 된 학기말 팀(6명) 프로젝트입니다. 저는 참고로 제공받은 데이터를 활용하며 "코딩 및 주석처리" 역할을 맡았습니다.

필수 준비:

1.

*파일 실행 방법* (cmd 터미널에서 부모 폴더 위치[=팀프로젝트_빅분개]):

1. 팀프로젝트_빅분개/팀프로젝트_빅분개/projectEnvironment/Scripts/activate
=> (팀프로젝트_빅분개 디렉터리에 있는 상태) cd projectEnvironment => cd Scripts => activate

2. (다시 팀프로젝트_빅분개 디렉터리에 있는 상태) streamlit run ancient_monarch.py
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

최근 수정일: 2026년 6월 15일

연락처: stasishat06@gmail.com
