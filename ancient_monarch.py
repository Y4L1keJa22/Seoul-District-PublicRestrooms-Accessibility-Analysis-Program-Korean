import os
import streamlit as st
import pandas as pd
import pydeck as pdk
from virtuoso import search_region, get_shortage_ranking, get_dong_shortage_ranking, get_gu_dong_ranking
import plotly.graph_objects as go
from datetime import datetime
import pytz

# ─── 페이지 설정 ──────────────────────────────────────────────────────────────
st.set_page_config(page_title='서울시 공중화장실 접근성 분석', layout='wide')
st.markdown("""
<style>
button[data-testid="baseButton-primary"] {
    background-color: #1E6FD9 !important;
    border-color: #1E6FD9 !important;
}
button[data-testid="baseButton-primary"]:hover {
    background-color: #1557A8 !important;
    border-color: #1557A8 !important;
}
</style>
""", unsafe_allow_html=True)

# ─── 제목 / 설명 ──────────────────────────────────────────────────────────────
st.title('서울시 공중화장실 접근성 부족지역 분석 프로그램')
st.markdown(
    '시간대별 유동인구와 공중화장실 공급 현황을 결합하여 부족지역을 분석하고, 현재 영업중인 가까운 화장실을 추천합니다.'
)
st.info(
    '**단순 위치 안내를 넘어**, 시간대별 유동인구 기반으로 **지금 서울 어디에 공중화장실이 가장 필요한지** 데이터로 말합니다.'
)
st.caption('부족도 지수가 100점에 가까울수록 수요 대비 공중화장실 공급이 부족한 지역을 의미합니다.')

_csv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '서울시 공중화장실 위치정보.csv')
if not os.path.exists(_csv_path):
    st.warning('데이터 파일(서울시 공중화장실 위치정보.csv)을 찾을 수 없습니다.')

st.divider()

# ─── 세션 상태 ────────────────────────────────────────────────────────────────
if 'display_time_mode' not in st.session_state:
    st.session_state.display_time_mode = 'current'
if 'search_result' not in st.session_state:
    st.session_state.search_result = None
if 'selected_hour' not in st.session_state:
    st.session_state.selected_hour = datetime.now(pytz.timezone('Asia/Seoul')).hour


def get_display_time():
    korea_tz = pytz.timezone('Asia/Seoul')
    if st.session_state.display_time_mode == 'current':
        return datetime.now(korea_tz)
    now = datetime.now(korea_tz)
    return now.replace(hour=st.session_state.selected_hour, minute=0, second=0)


# ─── 검색 입력 영역 ────────────────────────────────────────────────────────────
col_search, col_clock = st.columns([3, 1])
with col_search:
    selected_hour = st.slider(
        '분석 기준 시간대', 0, 23,
        value=st.session_state.selected_hour,
        format='%d시',
        help='선택한 시간대의 유동인구 데이터를 기반으로 부족도를 분석합니다.',
    )
    st.session_state.selected_hour = selected_hour
    st.session_state.display_time_mode = 'selected'

    query = st.text_input(
        '검색할 지역명',
        placeholder='예: 서울역, 서대문구, 홍제동, 인왕시장길',
    )
    search_button = st.button('분석 시작', type='primary')

with col_clock:
    display_time = get_display_time()
    time_label = (
        '현재 시간' if st.session_state.display_time_mode == 'current'
        else f'선택 시간 ({st.session_state.selected_hour:02d}시)'
    )
    st.metric(time_label, display_time.strftime('%H:%M'))
    if st.button('현재 시간으로', help='현재 시간대로 초기화'):
        korea_tz = pytz.timezone('Asia/Seoul')
        st.session_state.selected_hour = datetime.now(korea_tz).hour
        st.session_state.display_time_mode = 'current'
        st.rerun()

st.info('건물 이름보다 도로명 주소로 검색하면 더 정확합니다. 예: 연세대학교 → 서울 서대문구 연세로 50')

if search_button:
    st.session_state.search_result = search_region(query, hour=st.session_state.selected_hour)

st.divider()

# ─── 개별 지역 분석 결과 ──────────────────────────────────────────────────────
result = st.session_state.search_result

if result is not None:
    if result.get('error'):
        st.warning(result['error'])
    else:
        location = result['location']
        hour_disp = st.session_state.selected_hour

        if result.get('used_fallback'):
            st.warning(
                f'⚠️ {hour_disp:02d}시에 영업중인 화장실 정보가 없어 전체 공중화장실 기준으로 추천합니다.'
            )

        # 행정동 기준 사용 여부 판단
        dong_shortage_index = result.get('dong_shortage_index')
        use_dong = dong_shortage_index is not None

        if use_dong:
            active_shortage_index   = dong_shortage_index
            active_grade            = result.get('dong_display_grade', '-')
            active_priority         = result.get('dong_display_priority', '-')
            active_toilet_count     = result.get('dong_toilet_count', '-')
            active_rank             = result.get('dong_rank')
            active_total_count      = result.get('total_dong_count', '')
            active_rank_label       = f'{active_rank}위 / {active_total_count}개' if active_rank else '집계 불가'
            analysis_unit_label     = '동 단위 기준 분석'
            region_label = (
                f"{location.get('gu', '')} {location.get('dong', '')}"
            ).strip()
        else:
            active_shortage_index   = result.get('shortage_index')
            active_grade            = result.get('display_grade', '-')
            active_priority         = result.get('display_priority', '-')
            active_toilet_count     = result.get('toilet_count', '-')
            active_rank             = result.get('gu_rank')
            active_total_count      = result.get('total_gu_count', 25)
            active_rank_label       = f'{active_rank}위 / {active_total_count}개 구' if active_rank else '집계 불가'
            analysis_unit_label     = '자치구 기준 보조 분석'
            region_label            = location.get('gu') or location.get('name') or '-'

        pop_val = location.get('population')

        # ─── 핵심 분석 결과 ──────────────────────────────────────────────────
        st.subheader('핵심 분석 결과')
        st.caption(f'분석 단위: {analysis_unit_label}')

        col_a, col_b, col_c, col_d, col_e = st.columns([1.3, 1.2, 1.0, 1.1, 1.1])
        with col_a:
            st.metric('분석 지역', region_label)
            st.caption('동 단위 기준' if use_dong else '자치구 단위 기준')
        with col_b:
            idx_str = f"{active_shortage_index:.1f}점" if active_shortage_index is not None else '데이터 없음'
            st.metric('공중화장실 부족도 지수', idx_str)
            st.caption('등급 기준: 0\~33 충분 · 34\~66 보통 · 67\~100 부족')
        with col_c:
            st.metric('접근성 등급', active_grade)
            st.metric('설치 우선도', active_priority)
        with col_d:
            st.metric('서울시 내 순위', active_rank_label)
            st.caption('전체 동 부족도 기준')
        with col_e:
            if use_dong:
                _gu_r = result.get('dong_gu_rank')
                _gu_t = result.get('total_gu_dong_count', '')
                _gu_rank_lbl = f'{_gu_r}위 / {_gu_t}개' if _gu_r else '집계 불가'
                st.metric('자치구 내 순위', _gu_rank_lbl)
                st.caption(f'{location.get("gu", "")} 내 순위')
            else:
                st.metric('자치구 내 순위', '—')
                st.caption('동 분석 시 표시')

        # ─── 분석 해석 문장 ──────────────────────────────────────────────────
        # 자치구 내 순위 강조 문구 (등급과 독립적으로 상대순위만 강조)
        _gu_rank_note = ''
        if use_dong:
            _gu_r_note = result.get('dong_gu_rank')
            _gu_nm_note = location.get('gu', '')
            if _gu_r_note == 1:
                _gu_rank_note = (
                    f' 단, **{_gu_nm_note} 내에서는 부족도 1위**로 '
                    '상대적 우선순위가 가장 높습니다.'
                )
            elif _gu_r_note and _gu_r_note <= 3:
                _gu_rank_note = (
                    f' **{_gu_nm_note} 내 {_gu_r_note}위**로, '
                    '상대적 우선순위가 높은 편입니다.'
                )
        interp_map = {
            '부족': (
                f'**{region_label}**은 {hour_disp:02d}시 기준 추정 유동인구 대비 '
                '공중화장실 공급이 **부족**한 지역으로, '
                f'추가 설치 또는 개방 화장실 확대 검토가 필요합니다.{_gu_rank_note}'
            ),
            '보통': (
                f'**{region_label}**은 {hour_disp:02d}시 기준 추정 유동인구 대비 '
                '공중화장실 공급이 **보통** 수준입니다. '
                f'특정 시간대에 수요가 증가할 수 있으므로 모니터링이 권장됩니다.{_gu_rank_note}'
            ),
            '충분': (
                f'**{region_label}**은 {hour_disp:02d}시 기준 추정 유동인구 대비 '
                '공중화장실 공급이 **충분**한 지역입니다. '
                f'현재 공급 수준은 적절하며, 추가 설치 우선순위는 낮습니다.{_gu_rank_note}'
            ),
        }
        st.markdown(interp_map.get(active_grade, ''))

        # ─── 지도 ────────────────────────────────────────────────────────────
        st.subheader('지도')
        layers = []
        if location.get('boundary_geojson'):
            layers.append(pdk.Layer(
                'GeoJsonLayer',
                data=location['boundary_geojson'],
                stroked=True, filled=False,
                get_line_color=[255, 0, 0],
                line_width_min_pixels=3,
                pickable=False,
            ))

        map_rows, label_rows = [], []
        if location.get('x') is not None and location.get('y') is not None:
            map_rows.append({
                'lon': location['x'], 'lat': location['y'],
                'label': location.get('name', '추정 지역'),
                'rank': '추정 지역', 'color': [0, 128, 255], 'radius': 80,
            })
            label_rows.append({'lon': location['x'], 'lat': location['y'], 'text': '●'})

        for idx_r, item in enumerate(result['recommendations'], start=1):
            if item.get('x') is not None and item.get('y') is not None:
                map_rows.append({
                    'lon': item['x'], 'lat': item['y'],
                    'label': item['name'] or item['address'],
                    'rank': f'{idx_r}위', 'color': [255, 100, 0], 'radius': 50,
                })
                label_rows.append({'lon': item['x'], 'lat': item['y'], 'text': str(idx_r)})

        if map_rows:
            layers.append(pdk.Layer(
                'ScatterplotLayer', data=pd.DataFrame(map_rows),
                get_position='[lon, lat]', get_fill_color='color', get_radius='radius',
                pickable=True, auto_highlight=True,
            ))
            if label_rows:
                layers.append(pdk.Layer(
                    'TextLayer', data=pd.DataFrame(label_rows),
                    get_position='[lon, lat]', get_text='text',
                    get_color=[255, 255, 255], get_size=36,
                    get_text_anchor='middle', get_alignment_baseline='center',
                    pickable=False,
                ))
            st.pydeck_chart(pdk.Deck(
                layers=layers,
                initial_view_state=pdk.ViewState(
                    longitude=location['x'], latitude=location['y'],
                    zoom=13, min_zoom=8, max_zoom=17, pitch=0,
                ),
                tooltip={
                    'html': '<b>{rank}</b><br/>{label}',
                    'style': {'backgroundColor': 'rgba(0,0,0,0.8)', 'color': 'white'},
                },
            ))
        else:
            st.write('지도에 표시할 위치가 없습니다.')

        # ─── 참고용 TOP 5 ─────────────────────────────────────────────────────
        st.subheader('주변 공중화장실 TOP 5')
        st.caption(
            '선택한 시간대 기준으로 영업중인 가까운 공중화장실 목록입니다.'
        )

        top5_df = pd.DataFrame(result['recommendations'])
        if not top5_df.empty:
            display_df = top5_df.drop(columns=['x', 'y'], errors='ignore').copy()

            # 영업상태 표시값 변환 (-→정보없음)
            if '영업상태' in display_df.columns:
                display_df['영업상태'] = display_df['영업상태'].replace({'-': '정보없음'})

            # 거리 단위 추가 (m)
            if 'distance_m' in display_df.columns:
                display_df['distance_m'] = display_df['distance_m'].apply(lambda x: f'{x}m')

            display_df = display_df.rename(columns={
                'rank': '순위',
                '영업상태': '영업상태',
                'name': '이름',
                'distance_m': '거리',
                'address': '주소',
                '유형': '유형',
                'open_time': '개방시간',
                'accessibility_score': '접근성 점수',
            })
            col_order = ['순위', '영업상태', '이름', '거리', '주소', '유형', '개방시간', '접근성 점수']
            col_order = [c for c in col_order if c in display_df.columns]
            st.dataframe(
                display_df[col_order].set_index('순위'),
                use_container_width=True,
            )

            if '영업상태' in display_df.columns:
                if '역사 운영시간' in display_df['영업상태'].values:
                    st.caption('※ "역사 운영시간": 원본 데이터에 정확한 시간이 없어 지하철 역사 운영시간 기준으로 표시한 항목입니다.')
                if '확인 필요' in display_df['영업상태'].values:
                    st.caption('※ "확인 필요": 원본 데이터만으로 영업 여부를 판단하기 어려운 항목입니다.')
        else:
            st.info('추천할 공중화장실이 없습니다.')

        # ─── 현재 분석 지역 근거 지표 ───────────────────────────────────────────
        st.subheader(f'{region_label} 분석 근거 지표')
        st.caption(f'※ {region_label} 분석 지역 기준입니다.')
        pop_per_toilet = result.get('pop_per_toilet')
        seoul_avg = result.get('seoul_avg_per_toilet')
        col_i1, col_i2, col_i3 = st.columns(3)
        with col_i1:
            st.metric(
                f'{hour_disp:02d}시 유동인구',
                f"{int(pop_val):,}명" if pop_val is not None else '데이터 없음',
            )
            pop_type = location.get('population_type', '')
            label_map = {
                'dong_hourly': '동 단위·시간대 기준',
                'dong_area_weighted': '동 단위·면적비례 추정값',
                'gu_hourly': '자치구·시간대 기준',
                'dong': '행정동 기준',
                'gu': '자치구 기준',
            }
            if pop_type:
                st.caption(label_map.get(pop_type, pop_type))
        with col_i2:
            st.metric(
                '분석 단위 내 공중화장실 수',
                f'{active_toilet_count}개' if active_toilet_count and active_toilet_count != '-' else '-',
            )
        with col_i3:
            if pop_per_toilet is not None:
                st.metric('화장실 1개당 담당 인구', f'약 {pop_per_toilet:,}명')
                if seoul_avg is not None:
                    ratio = pop_per_toilet / seoul_avg
                    if ratio >= 1.2:
                        compare = '서울 평균 대비 높음 ▲'
                    elif ratio <= 0.8:
                        compare = '서울 평균 대비 낮음 ▽'
                    else:
                        compare = '서울 평균 수준 ─'
                    st.caption(f'{compare}  (서울 평균: {seoul_avg:,}명)')
            else:
                st.metric('화장실 1개당 담당 인구', '계산 불가')

        # ─── 해당 자치구 내 추가 설치 우선지역 ───────────────────────────────────
        if use_dong:
            _gu_nm_disp = location.get('gu', '')
            _gu_dong_rows = get_gu_dong_ranking(_gu_nm_disp) if _gu_nm_disp else []
            if _gu_dong_rows:
                st.subheader(f'{_gu_nm_disp} 공중화장실 추가 설치 우선지역')
                st.caption(f'현재 검색 지역이 속한 {_gu_nm_disp} 내 동별 부족도 순위입니다.')
                _cur_dc = str(location.get('dong_code') or '')
                _cur_dn = location.get('dong', '')
                _cur_in_gu = next(
                    (r['순위'] for r in _gu_dong_rows if r.get('_dong_code') == _cur_dc), None
                )
                if _cur_in_gu:
                    st.caption(
                        f'현재 검색 지역 **{_cur_dn}**은 '
                        f'{_gu_nm_disp} 내 **{_cur_in_gu}위** / {len(_gu_dong_rows)}개 동입니다.'
                    )
                _disp_df = pd.DataFrame(_gu_dong_rows[:10]).drop(columns=['_dong_code'], errors='ignore')
                st.dataframe(_disp_df.set_index('순위'), use_container_width=True)

        # ─── 시간대별 유동인구 그래프 ─────────────────────────────────────────
        hourly_pop_data = result.get('hourly_pop_data', {})
        if hourly_pop_data:
            st.subheader('선택 지역 시간대별 유동인구 변화')
            hours_sorted = sorted(hourly_pop_data.keys())
            pops = [hourly_pop_data[h] for h in hours_sorted]

            fig_pop = go.Figure()
            fig_pop.add_trace(go.Scatter(
                x=hours_sorted, y=pops,
                mode='lines+markers', name='유동인구',
                line=dict(color='royalblue', width=2),
                marker=dict(size=5),
            ))
            if hour_disp in hourly_pop_data:
                fig_pop.add_trace(go.Scatter(
                    x=[hour_disp], y=[hourly_pop_data[hour_disp]],
                    mode='markers',
                    name=f'선택 시간 ({hour_disp:02d}시)',
                    marker=dict(color='red', size=12, symbol='star'),
                ))
            fig_pop.update_layout(
                xaxis=dict(
                    title='시간대',
                    tickmode='array',
                    tickvals=list(range(0, 24, 2)),
                    ticktext=[f'{h:02d}시' for h in range(0, 24, 2)],
                ),
                yaxis_title='유동인구 수',
                height=320,
                legend=dict(orientation='h', y=1.1),
                margin=dict(t=40, b=40),
            )
            st.plotly_chart(fig_pop, use_container_width=True)
        else:
            st.caption('⚠️ 현재 데이터 구조상 시간대별 인구 차이를 계산할 수 없습니다.')

st.divider()

# ─── 서울시 전체 TOP 10 (하단, expander) ──────────────────────────────────────
_dong_ranking = get_dong_shortage_ranking()
_gu_ranking = get_shortage_ranking() if not _dong_ranking else []
with st.expander('서울시 동 단위 공중화장실 추가 설치 우선지역 TOP 10 보기', expanded=False):
    if _dong_ranking:
        st.caption(
            '자치구 시간대별 유동인구를 동별 면적 비율로 배분한 추정값과 공중화장실 수를 결합해 '
            '산출한 상대적 부족도 지수입니다. 부족도 지수 = 0~100점 (높을수록 추가 설치 우선)'
        )
        _top10_df = pd.DataFrame(_dong_ranking[:10])
        st.dataframe(_top10_df.set_index('순위'), use_container_width=True, height=420)
    elif _gu_ranking:
        st.caption('toilet_score.csv 기반 · 부족도 지수 = 0~100점')
        _top10_df = pd.DataFrame(_gu_ranking[:10])
        st.dataframe(_top10_df.set_index('순위'), use_container_width=True, height=420)
    else:
        st.info('순위 데이터를 불러올 수 없습니다.')
