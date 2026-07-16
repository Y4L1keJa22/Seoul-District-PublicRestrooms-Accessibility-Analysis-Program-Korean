import csv
import functools
import json
import math
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

GEOJSON_FILE = os.path.join(SCRIPT_DIR, 'dong_boundary_1.geojson') #행정동 경계 및 중심좌표 계산
HTML_FILE = os.path.join(SCRIPT_DIR, 'toilet_score_report.html') #maxScore, minScore 추출
CSV_SCORE_FILE = os.path.join(SCRIPT_DIR, 'toilet_score.csv') #자치구별 부족도 점수
CSV_TOILET_FILE = os.path.join(SCRIPT_DIR, '서울시 공중화장실 위치정보.csv') #화장실 위치 데이터
JSON_FILE = os.path.join(SCRIPT_DIR, '서울시 공중화장실 위치정보.json') #화장실 위치 데이터 (CSV 없을 때 대체 보완)
GU_POP_CSV_FILE = os.path.join(SCRIPT_DIR, '자치구 단위 서울 생활인구(내국인).csv') #자치구 인구
DONG_POP_JSON_FILE = os.path.join(SCRIPT_DIR, '행정동 단위 서울 생활인구(내국인).json') #행정동 인구(CSV 없을 때 대체)
DONG_POP_CSV_FILE = os.path.join(SCRIPT_DIR, '행정동 단위 서울 생활인구(내국인).csv') #행정동 인구
JIBGYEGU_POP_CSV_FILE = os.path.join(SCRIPT_DIR, '집계구 단위 서울 생활인구(내국인).csv') #행정동 인구 보완

# 공중화장실 CSV 실제 컬럼명
NAME_COL      = '건물명'
ADDR_COL      = '도로명주소'
JIBUN_COL     = '지번주소'
LON_COL       = 'x 좌표'   # 경도 (x)
LAT_COL       = 'y 좌표'   # 위도 (y)
GU_COL        = '구 명칭'
TYPE_COL      = '유형'
OPEN_COL      = '개방시간'
PLACE_COL     = '소재지'

# dong_boundary_1.geojson 실제 컬럼명 (geopandas로 확인)
BOUNDARY_DONG_CD_COL  = 'dong_cd'
BOUNDARY_DONG_NM_COL  = 'dong_nm'
BOUNDARY_GU_NM_COL    = 'gu_nm'
BOUNDARY_GU_CD_COL    = 'gu_cd'

# 경계 GeoDataFrame 모듈 수준 캐시 (find_dong_for_point 성능용)
_boundary_gdf_cache = None

#1
# 파일을 열 때 인코딩 오류가 발생할 수 있으므로, 오류를 무시하고 열도록 합니다.
def try_open(path, mode='r', encoding=None):
    if encoding:
        return open(path, mode, encoding=encoding, errors='replace')
    return open(path, mode, encoding='utf-8', errors='replace')

#2
#사용자가 입력한 문자열과 데이터의 문자열을 비교하기 쉽게 정규화합니다.
def normalize_text(text):
    if not isinstance(text, str):
        return ''
    normalized = text.lower()
    normalized = re.sub(r'[^0-9가-힣a-z]', '', normalized)
    return normalized

# #3 이 함수 사용 안 함.
# # 입력된 쿼리와 데이터의 텍스트를 정규화하여 비교합니다. 쿼리가 데이터의 텍스트에 포함되는지 여부를 확인합니다.
# def match_text(query, target):
#     query_norm = normalize_text(query) #2
#     target_norm = normalize_text(target) #2
#     return bool(query_norm and target_norm and query_norm in target_norm)

#4
# 행정동 이름에서 '동', '읍', '면' 등의 접미사를 제거하여 검색어와의 매칭을 개선합니다.
def strip_dong_suffix(name):
    if not name:
        return name
    for suffix in ['동', '읍', '면']:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[:-len(suffix)]
    return name

#5
# 주소명에서 '역', '지하철역', '역사', '번지' 등의 접미사를 제거하여 검색어와의 매칭을 개선합니다.
def strip_address_suffix(name):
    if not name:
        return name
    if name.endswith('지하철역'):
        return name[:-4]
    if name.endswith('역사'):
        return name[:-2]
    if name.endswith('역') and len(name) > 1:
        return name[:-1]
    if '번지' in name:
        return name.replace('번지', '')
    return name

#6
# 행정동 이름과 주소명에서 다양한 변형을 생성하여 검색어와의 매칭 가능성을 높입니다.
def generate_name_variants(name):
    normalized = normalize_text(name) #2
    if not normalized:
        return {''}

    variants = {normalized}
    stripped_dong = strip_dong_suffix(normalized) #4
    if stripped_dong and stripped_dong != normalized:
        variants.add(stripped_dong)

    stripped_addr = strip_address_suffix(normalized) #5
    if stripped_addr and stripped_addr != normalized:
        variants.add(stripped_addr)

    if '번지' in normalized:
        variants.add(normalized.replace('번지', ''))

    return variants

#7
# 검색어에서 한글과 숫자 토큰을 분리하여 매칭에 활용할 수 있도록 합니다. (예: '강남역 123' → ['강남', '역', '123'])
def split_query_tokens(query):
    tokens = re.split(r'[^0-9가-힣]+', query)
    return [normalize_text(token) for token in tokens if normalize_text(token)] #2

#8
# 검색어에서 다양한 변형을 생성하여 매칭 가능성을 높입니다. (예: '강남역 123' → {'강남역123', '강남역', '강남', '123'})
def generate_query_variants(query):
    query_norm = normalize_text(query) #2
    tokens = split_query_tokens(query) #7
    variants = {query_norm}
    for token in tokens:
        variants.add(token)
        stripped_dong = strip_dong_suffix(token) #4
        if stripped_dong:
            variants.add(stripped_dong)
        stripped_addr = strip_address_suffix(token) #5
        if stripped_addr:
            variants.add(stripped_addr)
        if '번지' in token:
            variants.add(token.replace('번지', ''))
    return {v for v in variants if v}

#9
# 사용자가 입력한 지역명과 행정동 경계 데이터를 활용하여 가장 적합한 행정동을 찾습니다. 
# 검색어와 행정동 이름의 다양한 변형을 비교하여 매칭 정확성을 높입니다.
def find_best_dong_match(query, query_norm, dong_info, gu_info, dong_alias_map):
    tokens = split_query_tokens(query) #7
    tokens.append(query_norm)

    # alias_map 조회: 토큰이 정확히 alias와 일치해야 하고,
    # 쿼리 전체가 alias보다 지나치게 길면 우연한 포함으로 간주
    for token in tokens:
        if token in dong_alias_map:
            alias_len = len(token)
            # 쿼리가 alias의 2배를 초과하면 부분 포함일 가능성 때문에 스킵
            if len(query_norm) <= alias_len * 2:
                return dong_alias_map[token]

    best = None
    for dong_norm, info in dong_info.items():
        dong_variants = generate_name_variants(dong_norm) #6
        # 1글자 이하의 너무 짧은 variant는 매칭에서 제외 (예: '다동' → '다')
        valid_variants = {v for v in dong_variants if len(v) >= 2}
        if not valid_variants:
            continue

        max_variant_len = max(len(v) for v in valid_variants)

        matched_token = None
        for token in tokens:
            if not token:
                continue
            for v in valid_variants:
                # variant가 token에 포함되거나 token이 variant에 포함
                if v in token or token in v:
                    matched_token = token
                    break
            if matched_token:
                break
        if not matched_token:
            continue

        # 매칭된 토큰 길이가 행정동 이름 길이의 50% 미만이면 너무 짧은 부분에 일치해서 제외
        if len(matched_token) < max_variant_len * 0.5:
            continue

        gu_norm = normalize_text(info.get('gu', '')) #2
        has_gu_hint = bool(gu_norm and any(gu_norm in tok for tok in tokens))

        # 자치구 힌트 없이 쿼리가 행정동 이름보다 2배 초과로 길면 신뢰도 낮아서 제외
        if not has_gu_hint and len(query_norm) > max_variant_len * 2:
            continue

        score = max_variant_len
        if has_gu_hint:
            score += 100
        if best is None or score > best[0]:
            best = (score, dong_norm)
    return best[1] if best else None

#10
# 두 지점 간의 거리를 계산하는 함수입니다. 위도와 경도를 입력받아 하버사인 
# 공식을 사용하여 거리를 미터 단위로 반환합니다.
def haversine(lon1, lat1, lon2, lat2):
    radius = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius * c

#11
# (행정동의 경계선 계산)행정동 경계의 지오메트리를 입력받아 중심 좌표(centroid)를
#  계산하는 함수입니다. 폴리곤과 멀티폴리곤 형태의 지오메트리를 지원하며,
#  중심 좌표를 반환합니다.
def compute_geometry_centroid(geometry):
    if not geometry or 'type' not in geometry or 'coordinates' not in geometry:
        return None, None

    points = []
    geom_type = geometry.get('type')
    coords = geometry.get('coordinates')

    if geom_type == 'Polygon':
        for ring in coords:
            for lon, lat in ring:
                points.append((lon, lat))
    elif geom_type == 'MultiPolygon':
        for polygon in coords:
            for ring in polygon:
                for lon, lat in ring:
                    points.append((lon, lat))
    else:
        return None, None

    if not points:
        return None, None

    lon_sum = sum(pt[0] for pt in points)
    lat_sum = sum(pt[1] for pt in points)
    count = len(points)
    return lon_sum / count, lat_sum / count

#12
# 행정동 경계 데이터를 로드하여 행정동과 자치구 정보를 추출합니다. 
# 각 행정동에 대해 이름, 코드, 자치구, 중심 좌표, 지오메트리를 저장하며, 
# 자치구별로도 중심 좌표와 지오메트리를 수집하여 나중에 지도 시각화에 
# 활용할 수 있도록 합니다.
def load_dong_boundary():
    if not os.path.exists(GEOJSON_FILE):
        return {}, {}

    with try_open(GEOJSON_FILE) as f: #1
        data = json.load(f)

    dong_info = {}
    gu_info = {}
    for feature in data.get('features', []):
        prop = feature.get('properties', {})
        dong = prop.get('dong_nm') or prop.get('DONG_NM') or ''
        gu = prop.get('gu_nm') or prop.get('GU_NM') or ''
        dong_code = prop.get('dong_cd') or prop.get('DONG_CD') or ''
        gu_code = prop.get('gu_cd') or prop.get('GU_CD') or ''
        centroid = compute_geometry_centroid(feature.get('geometry', {})) #11

        if not dong:
            continue

        dong_norm = normalize_text(dong) #2
        dong_info[dong_norm] = {
            'name': dong,
            'code': dong_code,
            'gu': gu,
            'centroid': centroid,
            'geometry': feature.get('geometry'),
        }

        gu_norm = normalize_text(gu) #2
        if gu_norm not in gu_info:
            gu_info[gu_norm] = {
                'name': gu,
                'code': gu_code,
                'centroid_points': [],
                'geometries': [],
            }
        if centroid[0] is not None:
            gu_info[gu_norm]['centroid_points'].append(centroid)
        if feature.get('geometry'):
            gu_info[gu_norm]['geometries'].append(feature.get('geometry'))

    for info in gu_info.values():
        points = info.pop('centroid_points', [])
        if points:
            lon_sum = sum(pt[0] for pt in points)
            lat_sum = sum(pt[1] for pt in points)
            info['centroid'] = (lon_sum / len(points), lat_sum / len(points))
        else:
            info['centroid'] = (None, None)

    dong_alias_map = build_dong_alias_map(dong_info) #13
    return dong_info, gu_info, dong_alias_map

#13
# 행정동 이름에서 다양한 변형을 생성하여 검색어와의 매칭 가능성을 높이는 alias 맵을 구축합니다.
def build_dong_alias_map(dong_info):
    alias_map = {}
    for dong_norm, info in dong_info.items():
        variants = generate_name_variants(info['name']) #6
        variants.add(dong_norm)
        for variant in variants:
            if variant:
                alias_map[variant] = dong_norm
    return alias_map

#14
# 지오메트리 목록을 입력받아 GeoJSON FeatureCollection 형식으로 변환하는 함수입니다.
def build_geojson_feature_collection(geometries):
    if not geometries:
        return None
    features = []
    for geometry in geometries:
        if geometry and isinstance(geometry, dict):
            features.append({'type': 'Feature', 'geometry': geometry, 'properties': {}})
    return {'type': 'FeatureCollection', 'features': features} if features else None

#15
# 자치구 이름을 입력받아 해당 자치구의 경계선을 GeoJSON 형식으로 반환하는 함수입니다.
def get_boundary_geojson_for_gu(gu_norm, gu_info):
    info = gu_info.get(gu_norm)
    if not info:
        return None
    return build_geojson_feature_collection(info.get('geometries')) #14

#16
# CSV 파일에서 행정동 또는 자치구 단위의 인구 데이터를 로드하는 함수입니다.
def load_population_csv(path, code_index=2, total_index=3):
    result = {}
    if not os.path.exists(path):
        return result

    with try_open(path, encoding='cp949') as f: #1
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return result

        for row in reader:
            if len(row) <= max(code_index, total_index):
                continue
            code = row[code_index].strip()
            try:
                total = float(row[total_index])
            except (ValueError, TypeError):
                continue
            if code:
                result[code] = total
    return result

#17_hour
# 시간대별 행정동 인구 데이터를 로드하는 함수입니다.
# CSV 파일에서 시간대(시간대구분)별로 인구 데이터를 딕셔너리로 반환합니다.
# 반환 형식: {행정동코드: {시간대: 인구수, ...}, ...}
def load_dong_population_csv_by_hour():
    result = {}
    if not os.path.exists(DONG_POP_CSV_FILE):
        return result

    with try_open(DONG_POP_CSV_FILE, encoding='cp949') as f: #1
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return result

        for row in reader:
            if len(row) <= 3:
                continue
            try:
                hour = int(float(row[1].strip()))  # 시간대구분 (0-23)
                code = row[2].strip()
                total = float(row[3])
                if code:
                    if code not in result:
                        result[code] = {}
                    result[code][hour] = total
            except (ValueError, TypeError, IndexError):
                continue
    return result

#17_hour_gu
# 시간대별 자치구 인구 데이터를 로드합니다.
# 반환 형식: {자치구코드: {시간대: 인구수, ...}, ...}
def load_gu_population_csv_by_hour():
    result = {}
    if not os.path.exists(GU_POP_CSV_FILE):
        return result
    with try_open(GU_POP_CSV_FILE, encoding='cp949') as f: #1
        reader = csv.reader(f)
        try:
            next(reader)
        except StopIteration:
            return result
        for row in reader:
            if len(row) <= 3:
                continue
            try:
                hour = int(float(row[1].strip()))
                code = row[2].strip()
                total = float(row[3])
                if code:
                    if code not in result:
                        result[code] = {}
                    result[code][hour] = total
            except (ValueError, TypeError, IndexError):
                continue
    return result

#17
# 행정동 단위 인구 데이터를 CSV 파일에서 로드하는 함수입니다.
def load_dong_population_csv():
    result = {}
    if not os.path.exists(DONG_POP_CSV_FILE):
        return result

    with try_open(DONG_POP_CSV_FILE, encoding='cp949') as f: #1
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return result

        for row in reader:
            if len(row) <= 3:
                continue
            code = row[2].strip()
            try:
                total = float(row[3])
            except (ValueError, TypeError):
                continue
            if code:
                result[code] = total
    return result

#18
# 행정동 단위 인구 데이터를 로드하는 함수입니다.
#  CSV 파일이 존재하면 우선적으로 로드하며, CSV 파일이
#  없을 경우 JSON 파일에서 데이터를 로드합니다. JSON 파일에서는 
# 'DATA' 키 아래의 레코드를 순회하며 행정동 코드를 추출하고, 
# 해당 코드에 대한 인구 수를 저장합니다. 인구 수가 유효하지
#  않은 경우에는 해당 레코드를 건너뜁니다.
def load_dong_population():
    result = load_dong_population_csv() #17
    if result:
        return result

    if os.path.exists(DONG_POP_JSON_FILE):
        with try_open(DONG_POP_JSON_FILE) as f: #1
            data = json.load(f)

        for record in data.get('DATA', []):
            code = record.get('adstrd_code_se') or record.get('ADSTRD_CODE_SE')
            total = record.get('tot_lvpop_co') or record.get('TOT_LVPOP_CO')
            if not code or total is None:
                continue
            try:
                result[code.strip()] = float(total)
            except (ValueError, TypeError):
                continue
    return result

#19
# 행정동 코드와 자치구 코드를 입력받아 해당 행정동의 인구 수를 반환하는 함수입니다.
# hour: 시간대 (0-23), None이면 전체 인구 수 반환
def get_population_for_dong(code, dong_pop, gu_pop=None, gu_code=None, hour=None):
    if not code:
        return None, None
    
    # 시간대별 인구 데이터 형식: {행정동코드: {시간대: 인구수, ...}, ...}
    # 일반 인구 데이터 형식: {행정동코드: 인구수, ...}
    
    # 행정동 인구 우선 조회
    if hour is not None and isinstance(dong_pop.get(code), dict):
        # 시간대별 데이터에서 조회
        population = dong_pop.get(code, {}).get(hour)
    else:
        # 전체 인구 데이터에서 조회
        population = dong_pop.get(code)
    
    if population is not None:
        return population, 'dong'
    
    # 행정동 인구가 없으면 자치구 인구 사용
    if gu_pop is not None and gu_code:
        population = gu_pop.get(gu_code)
        if population is not None:
            return population, 'gu'
    
    # 둘 다 없으면 동 코드 앞 5자리(자치구 단위) 합산. 예: [1141055500 + 1141056500 + 1141066000 + ...]
    if dong_pop is not None and len(str(code)) >= 5:
        prefix = str(code)[:5]
        prefix_values = []
        for key, value in dong_pop.items():
            if str(key).startswith(prefix):
                if hour is not None and isinstance(value, dict):
                    hour_value = value.get(hour)
                    if hour_value is not None:
                        prefix_values.append(hour_value)
                elif hour is None and not isinstance(value, dict):
                    prefix_values.append(value)
        if prefix_values:
            return sum(prefix_values), 'gu'

    return None, None

#20
# 집계구 단위 인구 데이터를 로드하는 함수입니다. 
# CSV 파일에서 행정동 코드와 인구 수를 추출하여 저장합니다.
def load_jibgye_population():
    result = {}
    if not os.path.exists(JIBGYEGU_POP_CSV_FILE):
        return result

    with try_open(JIBGYEGU_POP_CSV_FILE, encoding='cp949') as f: #1
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return result

        for row in reader:
            if len(row) < 5:
                continue
            dong_code = row[2].strip()
            try:
                total = float(row[4])
            except (ValueError, TypeError):
                continue
            if dong_code:
                result[dong_code] = result.get(dong_code, 0.0) + total
    return result

#21
# 공중화장실 위치 데이터와 자치구별 부족도 점수, 
# 행정동 경계 정보, 인구 데이터를 로드하는 함수입니다.
def load_toilet_data():
    toilets = []
    if os.path.exists(JSON_FILE):
        with try_open(JSON_FILE) as f: #1
            data = json.load(f)
        for item in data.get('DATA', []):
            try:
                x = float(item.get('coord_x') or item.get('COORD_X') or 0)
                y = float(item.get('coord_y') or item.get('COORD_Y') or 0)
            except (TypeError, ValueError):
                continue
            gu_value = (item.get('gu_name') or item.get('GU_NAME') or '').strip()
            addr_new = (item.get('addr_new') or item.get('ADDR_NEW') or '').strip()
            addr_old = (item.get('addr_old') or item.get('ADDR_OLD') or '').strip()
            if not gu_value:
                match = re.search(r'서울특별시\s*([^\s]+구)', addr_new + ' ' + addr_old)
                if match:
                    gu_value = match.group(1)
            toilets.append({
                'name': (item.get('conts_name') or item.get('CONTS_NAME') or '').strip(),
                'addr_new': addr_new,
                'addr_old': addr_old,
                'gu': gu_value,
                'x': x,
                'y': y,
                'full_type': (item.get('value_01') or item.get('VALUE_01') or '').strip(),
                'open_time': (item.get('value_02') or item.get('VALUE_02') or '').strip(),
                'location_type': (item.get('value_08') or item.get('VALUE_08') or '').strip(),
            })

    if os.path.exists(CSV_TOILET_FILE):
        with try_open(CSV_TOILET_FILE, encoding='cp949') as f: #1
            reader = csv.reader(f)
            try:
                header = next(reader)
            except StopIteration:
                header = []
            normalized = [normalize_text(col) for col in header] #2
            index = {name: idx for idx, name in enumerate(normalized)}

            # 컬럼 인덱스 사전 계산 (normalize_text로 공백 처리된 컬럼명 기준, fallback은 실제 열 위치)
            i_lon   = index.get(normalize_text(LON_COL),   3)
            i_lat   = index.get(normalize_text(LAT_COL),   4)
            i_name  = index.get(normalize_text(NAME_COL),  5)
            i_addr  = index.get(normalize_text(ADDR_COL),  1)
            i_jibun = index.get(normalize_text(JIBUN_COL), 2)
            i_gu    = index.get(normalize_text(GU_COL),    6)
            i_type  = index.get(normalize_text(TYPE_COL),  8)
            i_open  = index.get(normalize_text(OPEN_COL),  9)
            i_place = index.get(normalize_text(PLACE_COL), 15)

            def _cell(row, i):
                return row[i].strip() if i < len(row) else ''

            for row in reader:
                if len(row) < 5:
                    continue
                try:
                    x = float(row[i_lon])
                    y = float(row[i_lat])
                except (ValueError, TypeError, IndexError):
                    continue
                raw_name = _cell(row, i_name)
                raw_addr = _cell(row, i_addr)
                raw_place = _cell(row, i_place)
                toilets.append({
                    'name': raw_name or raw_addr or raw_place,
                    'addr_new': raw_addr,
                    'addr_old': _cell(row, i_jibun),
                    'gu': _cell(row, i_gu),
                    'x': x,
                    'y': y,
                    'full_type': _cell(row, i_type),
                    'open_time': _cell(row, i_open),
                    'location_type': raw_place,
                })

    unique = []
    seen = set()
    for toilet in toilets:
        key = (
            round(toilet['x'], 6),
            round(toilet['y'], 6),
            normalize_text(toilet['name'] or toilet['addr_new'] or toilet['addr_old']), #2
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(toilet)

    return unique

#22
# 부족도 점수 데이터를 CSV 파일에서 로드하는 함수입니다.
#  자치구 이름과 부족도 점수를 추출하여 딕셔너리 형태로 반환합니다.
def load_shortage_scores():
    scores = {}
    if not os.path.exists(CSV_SCORE_FILE):
        return scores
    with try_open(CSV_SCORE_FILE) as f: #1
        reader = csv.DictReader(f)
        for row in reader:
            gu = row.get('자치구명') or row.get('자치구')
            score_text = row.get('부족도점수') or row.get('부족도 점수')
            if not gu:
                continue
            try:
                score = float(score_text)
            except (TypeError, ValueError):
                score = None
            gu_norm = normalize_text(gu) #2
            scores[gu_norm] = score
    return scores

#22b
# 자치구별 부족도 전체 테이블 로드 (TOP 10 표시 및 min/max 계산용)
# toilet_score.csv는 UTF-8 BOM 파일이므로 헤더를 스킵하고 인덱스로 읽음
def load_toilet_score_table():
    rows = []
    if not os.path.exists(CSV_SCORE_FILE):
        return rows
    try:
        with try_open(CSV_SCORE_FILE) as f: #1
            reader = csv.reader(f)
            next(reader, None)  # 헤더 스킵
            for row in reader:
                if len(row) < 6:
                    continue
                gu = row[1].strip()
                if not gu:
                    continue
                try:
                    toilet_count = int(float(row[2]))
                    population = float(row[3])
                    per_10k = float(row[4])
                    raw_score = float(row[5])
                except (ValueError, IndexError):
                    continue
                rows.append({
                    'gu': gu,
                    'gu_norm': normalize_text(gu), #2
                    'toilet_count': toilet_count,
                    'population': population,
                    'per_10k': per_10k,
                    'raw_score': raw_score,
                })
    except Exception:
        pass
    return rows

#23
# HTML 파일에서 최대 점수와 최소 점수를 추출하는 함수입니다.
def load_html_metrics():
    if not os.path.exists(HTML_FILE):
        return None, None
    with try_open(HTML_FILE) as f: #1
        html = f.read()
    max_match = re.search(r'maxScore\s*=\s*([\-\d.]+)', html)
    min_match = re.search(r'minScore\s*=\s*([\-\d.]+)', html)
    max_score = float(max_match.group(1)) if max_match else None
    min_score = float(min_match.group(1)) if min_match else None
    return max_score, min_score




#23b
# 공중화장실 좌표를 행정동 Polygon에 공간조인해 sjoin_dong_code 등 필드를 추가합니다.
# geopandas가 없거나 파일이 없으면 원본 list를 그대로 반환합니다.
def assign_dong_by_spatial_join(toilets):
    try:
        import geopandas as gpd
        from shapely.geometry import Point
    except ImportError:
        return toilets
    if not os.path.exists(GEOJSON_FILE):
        return toilets
    try:
        boundary_gdf = gpd.read_file(GEOJSON_FILE)
        if boundary_gdf.crs is None:
            boundary_gdf = boundary_gdf.set_crs('EPSG:4326')
        elif str(boundary_gdf.crs).upper() != 'EPSG:4326':
            boundary_gdf = boundary_gdf.to_crs('EPSG:4326')

        pts_data = []
        for i, t in enumerate(toilets):
            x, y = t.get('x'), t.get('y')
            if x and y:
                pts_data.append({'_orig_idx': i, 'geometry': Point(x, y)})
        if not pts_data:
            return toilets

        toilet_gdf = gpd.GeoDataFrame(pts_data, geometry='geometry', crs='EPSG:4326')
        bcols = [BOUNDARY_DONG_CD_COL, BOUNDARY_DONG_NM_COL,
                 BOUNDARY_GU_NM_COL, BOUNDARY_GU_CD_COL, 'geometry']
        joined = gpd.sjoin(
            toilet_gdf,
            boundary_gdf[bcols],
            how='left', predicate='within',
        )
        # 경계선 위 중복 → 첫 번째 유지
        joined = joined[~joined.index.duplicated(keep='first')]

        result = [dict(t) for t in toilets]
        for _, row in joined.iterrows():
            orig = int(row['_orig_idx'])
            result[orig]['sjoin_dong_code'] = str(row.get(BOUNDARY_DONG_CD_COL) or '')
            result[orig]['sjoin_dong_nm']   = str(row.get(BOUNDARY_DONG_NM_COL) or '')
            result[orig]['sjoin_gu_nm']     = str(row.get(BOUNDARY_GU_NM_COL)   or '')
            result[orig]['sjoin_gu_cd']     = str(row.get(BOUNDARY_GU_CD_COL)   or '')
        return result
    except Exception:
        return toilets


#23b_gdf
# 경계 GeoDataFrame을 모듈 수준에서 캐시합니다.
def _get_boundary_gdf():
    global _boundary_gdf_cache
    if _boundary_gdf_cache is not None:
        return _boundary_gdf_cache
    try:
        import geopandas as gpd
        if not os.path.exists(GEOJSON_FILE):
            return None
        gdf = gpd.read_file(GEOJSON_FILE)
        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326')
        elif str(gdf.crs).upper() != 'EPSG:4326':
            gdf = gdf.to_crs('EPSG:4326')
        _boundary_gdf_cache = gdf
        return gdf
    except Exception:
        return None


#23b_pip
# 좌표(lon, lat) → 동 Polygon 매칭. dong_cd/dong_nm/gu_nm/gu_cd 딕셔너리 반환.
# assign_dong_by_spatial_join과 동일하게 gpd.sjoin을 사용해 안정성 확보.
# 경계 밖이거나 geopandas 없으면 None 반환.
def find_dong_for_point(lon, lat):
    try:
        import geopandas as gpd
        from shapely.geometry import Point
        gdf = _get_boundary_gdf()
        if gdf is None:
            return None
        pt_gdf = gpd.GeoDataFrame(
            [{}], geometry=[Point(lon, lat)], crs='EPSG:4326'
        )
        cols = [BOUNDARY_DONG_CD_COL, BOUNDARY_DONG_NM_COL,
                BOUNDARY_GU_NM_COL, BOUNDARY_GU_CD_COL, 'geometry']
        joined = gpd.sjoin(pt_gdf, gdf[cols], how='left', predicate='within')
        if len(joined) > 0:
            row = joined.iloc[0]
            dong_cd = str(row.get(BOUNDARY_DONG_CD_COL) or '')
            if dong_cd and dong_cd not in ('nan', 'None', ''):
                return {
                    'dong_cd': dong_cd,
                    'dong_nm': str(row.get(BOUNDARY_DONG_NM_COL) or ''),
                    'gu_nm':   str(row.get(BOUNDARY_GU_NM_COL)   or ''),
                    'gu_cd':   str(row.get(BOUNDARY_GU_CD_COL)   or ''),
                }
        return None
    except Exception as e:
        print(f"[DEBUG] find_dong_for_point 오류: {e}")
        return None


#23c
# 공간조인 결과 + 자치구 시간대 인구를 면적 비율로 분배해 법정동 단위 부족도 테이블 생성.
# raw_score = 면적 비례 추정 인구 / 화장실 수 (높을수록 부족)
# 배경: boundary(법정동코드)와 생활인구(행정동코드) 코드가 달라 직접 매칭 불가.
#        자치구 인구 × (법정동 면적 / 자치구 전체 면적) 으로 법정동 인구를 추정.
def build_dong_shortage_table(toilets_with_sjoin, gu_pop_by_hour,
                               dong_area_map, gu_area_map, dong_to_gu_map):
    # 법정동별 화장실 수 집계
    dong_data = {}  # {dong_cd: {'toilet_count', 'dong_nm', 'gu_nm', 'gu_cd'}}
    for t in toilets_with_sjoin:
        code = t.get('sjoin_dong_code', '')
        if not code or code in ('', 'nan', 'None', 'nan'):
            continue
        if code not in dong_data:
            dong_data[code] = {
                'toilet_count': 0,
                'dong_nm': t.get('sjoin_dong_nm', ''),
                'gu_nm': t.get('sjoin_gu_nm', ''),
                'gu_cd': t.get('sjoin_gu_cd', ''),
            }
        dong_data[code]['toilet_count'] += 1

    if not dong_data:
        return [], None, None

    rows = []
    for dong_code, info in dong_data.items():
        gu_cd = info['gu_cd'] or dong_to_gu_map.get(dong_code, '')
        if not gu_cd:
            continue

        dong_area = dong_area_map.get(dong_code, 0.0)
        gu_total  = gu_area_map.get(gu_cd, 0.0)
        if gu_total <= 0 or dong_area <= 0:
            continue

        gu_hourly = gu_pop_by_hour.get(gu_cd, {})
        if not gu_hourly:
            continue

        area_ratio = dong_area / gu_total
        avg_gu_pop = sum(gu_hourly.values()) / len(gu_hourly)
        avg_pop    = avg_gu_pop * area_ratio

        tc  = info['toilet_count']
        raw = avg_pop / tc if tc > 0 else None

        rows.append({
            'dong_code':  dong_code,
            'dong_nm':    info['dong_nm'],
            'gu_nm':      info['gu_nm'],
            'gu_cd':      gu_cd,
            'area_km2':   dong_area,
            'area_ratio': area_ratio,
            'toilet_count': tc,
            'avg_pop':    round(avg_pop),
            'raw_score':  raw,
            'shortage_index': None,
            'grade': '-',
            'priority': '-',
        })

    if not rows:
        return [], None, None

    valid_raw = [r['raw_score'] for r in rows if r['raw_score'] is not None]
    if not valid_raw:
        return rows, None, None

    # log1p 변환으로 극단값(화장실 1개 지역) 완화 후 min-max 정규화
    log_scores = [math.log1p(s) for s in valid_raw]
    log_min = min(log_scores)
    log_max = max(log_scores)
    for r in rows:
        if r['raw_score'] is not None:
            log_s = math.log1p(r['raw_score'])
            idx = (log_s - log_min) / (log_max - log_min) * 100 if log_max > log_min else 0.0
            r['shortage_index'] = round(max(0.0, min(100.0, idx)), 1)
        else:
            r['shortage_index'] = 0.0
        r['grade']    = grade_from_index(r['shortage_index']) #25_grade
        r['priority'] = priority_from_grade(r['grade']) #25_priority
    # log_min/log_max를 반환 → search_region의 개별 동 지수 계산에 사용
    return rows, log_min, log_max

#24
# load_app_data()는
# 애플리케이션에서 필요한 데이터를 로드하는 함수입니다. 
# 공중화장실 위치 데이터, 부족도 점수, 행정동 경계 정보, 
# 인구 데이터를 로드하여 딕셔너리 형태로 반환합니다. 
# LRU 캐시를 사용하여 데이터 로딩을 최적화합니다.
# @functools.lru_cache(maxsize=1)는 
# 자기의 아래에 있는 함수의 호출을 cache 메모리로 저장하고, 
# 가장 최근의 호출만 저장하도록 합니다
# 연산해야 할 데이터를 로드해야 하기 때문에 속도가 중요합니다.
@functools.lru_cache(maxsize=1)
def load_app_data():
    toilets = load_toilet_data() #21
    toilets = assign_dong_by_spatial_join(toilets) #23b  공간조인으로 행정동 코드 부여
    score_map = load_shortage_scores() #22
    score_table = load_toilet_score_table() #22b
    _raw_scores = [r['raw_score'] for r in score_table if r['raw_score'] is not None]
    score_min = min(_raw_scores) if _raw_scores else None
    score_max = max(_raw_scores) if _raw_scores else None
    _total_pop = sum(r['population'] for r in score_table)
    _total_toilets = sum(r['toilet_count'] for r in score_table)
    seoul_avg_per_toilet = round(_total_pop / _total_toilets) if _total_toilets > 0 else None
    dong_info, gu_info, dong_alias_map = load_dong_boundary() #12
    gu_pop = load_population_csv(GU_POP_CSV_FILE, code_index=2, total_index=3) #16
    gu_pop_by_hour = load_gu_population_csv_by_hour() #17_hour_gu
    dong_pop = load_dong_population() #18
    dong_pop_by_hour = load_dong_population_csv_by_hour() #17_hour
    jibgye_pop = load_jibgye_population() #20
    for code, total in jibgye_pop.items():
        if code not in dong_pop:
            dong_pop[code] = total
    html_max, html_min = load_html_metrics() #23

    # boundary에서 법정동/자치구 면적 맵 구축 (인구 추정용)
    dong_area_map  = {}  # {boundary_dong_cd: area_km2}
    gu_area_map    = {}  # {gu_cd: total_area_km2}
    dong_to_gu_map = {}  # {boundary_dong_cd: gu_cd}
    if os.path.exists(GEOJSON_FILE):
        try:
            import geopandas as gpd
            _bnd = gpd.read_file(GEOJSON_FILE)
            for _, _row in _bnd.iterrows():
                _dc   = str(_row[BOUNDARY_DONG_CD_COL])
                _gc   = str(_row[BOUNDARY_GU_CD_COL])
                _area = float(_row.get('area_km2') or 0)
                dong_area_map[_dc]  = _area
                gu_area_map[_gc]    = gu_area_map.get(_gc, 0.0) + _area
                dong_to_gu_map[_dc] = _gc
        except Exception:
            pass

    dong_shortage_table, dong_raw_min, dong_raw_max = build_dong_shortage_table( #23c
        toilets, gu_pop_by_hour, dong_area_map, gu_area_map, dong_to_gu_map
    )
    return {
        'toilets': toilets,
        'score_map': score_map,
        'dong_info': dong_info,
        'gu_info': gu_info,
        'dong_alias_map': dong_alias_map,
        'gu_pop': gu_pop,
        'gu_pop_by_hour': gu_pop_by_hour,
        'dong_pop': dong_pop,
        'dong_pop_by_hour': dong_pop_by_hour,
        'html_max': html_max,
        'html_min': html_min,
        'score_table': score_table,
        'score_min': score_min,
        'score_max': score_max,
        'seoul_avg_per_toilet': seoul_avg_per_toilet,
        'dong_shortage_table': dong_shortage_table,
        'dong_raw_min': dong_raw_min,
        'dong_raw_max': dong_raw_max,
        'dong_area_map': dong_area_map,
        'gu_area_map': gu_area_map,
        'dong_to_gu_map': dong_to_gu_map,
    }

#25_idx
# raw 부족도 점수를 0~100 지수로 min-max 정규화합니다.
def compute_shortage_index(raw_score, score_min, score_max):
    if raw_score is None or score_min is None or score_max is None:
        return None
    if score_max <= score_min:
        return None
    idx = (raw_score - score_min) / (score_max - score_min) * 100
    return round(max(0.0, min(100.0, idx)), 1)

#25_grade
# 0~100 지수 기반 등급 반환 (0~33:충분 / 34~66:보통 / 67~100:부족)
def grade_from_index(idx):
    if idx is None:
        return '-'
    if idx >= 67:
        return '부족'
    if idx >= 34:
        return '보통'
    return '충분'

#25_priority
# 등급 기반 설치 우선도 반환
def priority_from_grade(grade):
    return {'부족': '높음', '보통': '보통', '충분': '낮음'}.get(grade, '-')

#25_open
# 화장실 개방시간 문자열과 선택 시간을 비교하여 영업 여부를 반환합니다.
# 반환값: True(영업중), False(영업종료), None(알 수 없음)
def is_open(open_time_str, selected_hour):
    if not open_time_str:
        return None
    s = open_time_str.strip()
    if not s or s in ('-', '미상', '정보없음', 'N/A', 'n/a'):
        return None

    # ─ 전처리 1: 파이프 구분자 → 숫자 포함 부분 추출
    # 예: "기타|11~22시|" → "11~22시", "정시(09:00~20:00)|" → "정시(09:00~20:00)"
    if '|' in s:
        for _part in s.split('|'):
            _part = _part.strip()
            if _part and re.search(r'\d', _part):
                s = _part
                break

    # ─ 전처리 2: 괄호 안 숫자 포함 내용 추출
    # 예: "정시(09:00~20:00)" → "09:00~20:00", "상시(24시간)" → "24시간"
    _bracket = re.search(r'[(\[](.*?)[)\]]', s)
    if _bracket:
        _inner = _bracket.group(1).strip()
        if re.search(r'\d', _inner):
            s = _inner

    # ─ 상시 개방 키워드 (전처리 후 체크)
    for keyword in ('24시간', '상시개방', '연중무휴', '상시'):
        if keyword in s:
            return True

    # 00:00~24:00 또는 00:00-24:00 (종일 개방)
    if re.search(r'0{1,2}:0{1,2}\s*[~\-]\s*24:0{1,2}', s):
        return True

    # ─ HH:MM~HH:MM 또는 HH:MM-HH:MM
    match = re.search(r'(\d{1,2}):(\d{2})\s*[~\-]\s*(\d{1,2}):(\d{2})', s)
    if match:
        start_h = int(match.group(1))
        end_h = int(match.group(3))
        if end_h == 0 or end_h == 24:
            return start_h <= selected_hour
        if end_h < start_h:  # 자정 초과 (예: 22:00~05:00)
            return selected_hour >= start_h or selected_hour < end_h
        return start_h <= selected_hour < end_h

    # ─ HH시~HH시 또는 HH~HH시 (예: "11~22시", "11시~22시", "9시~18시")
    match = re.search(r'(\d{1,2})\s*시?\s*[~\-]\s*(\d{1,2})\s*시', s)
    if match:
        start_h = int(match.group(1))
        end_h = int(match.group(2))
        if end_h == 0 or end_h == 24:
            return start_h <= selected_hour
        if end_h < start_h:  # 자정 초과
            return selected_hour >= start_h or selected_hour < end_h
        return start_h <= selected_hour < end_h

    return None  # 파싱 불가 → 알 수 없음

#25
# 사용자가 입력한 검색어를 기반으로 공중화장실 위치를 추천하는 함수입니다.
# ancient_monarch.py 파일에서 호출됨
# hour: 시간대 (0-23), 기본값은 None (기존 동작 유지)
def search_region(query, hour=None):
    if not query or not isinstance(query, str):
        return {'error': '검색어를 입력해 주세요.', 'query': query}

    data = load_app_data() #24
    cleaned_query = query.strip()
    if not cleaned_query:
        return {'error': '검색어를 입력해 주세요.', 'query': query}

    # 시간대가 지정되면 시간대별 인구 데이터 사용, 아니면 기본 인구 데이터 사용
    dong_pop_to_use = data['dong_pop_by_hour'] if (hour is not None and data.get('dong_pop_by_hour')) else data['dong_pop']

    location = find_reference_location(
        cleaned_query,
        data['toilets'],
        data['score_map'],
        data['dong_info'],
        data['gu_info'],
        data['gu_pop'],
        dong_pop_to_use,
        data['dong_alias_map'],
        hour=hour,
    ) #27

    if not location or location.get('x') is None or location.get('y') is None:
        return {
            'error': (
                '검색 결과가 없습니다. 자치구명, 행정동명, 도로명주소 일부를 입력해보세요.\n'
                '예: "서대문구", "홍제동", "인왕시장길"'
            ),
            'query': cleaned_query,
        }

    # 직접 매칭된 화장실 추출 (TOP 5 후보 보장용)
    matched_toilet = location.pop('_matched_toilet', None)
    print(f"[DEBUG] query={cleaned_query} | match_type={location.get('type')} | x={location.get('x'):.5f}, y={location.get('y'):.5f} | matched_toilet={matched_toilet.get('name') if matched_toilet else None}")

    # 시간대가 지정된 경우 자치구 인구를 시간대별로 보정
    if hour is not None:
        gu_pop_by_hour = data.get('gu_pop_by_hour', {})
        gu_code = location.get('gu_code')
        if gu_code and gu_pop_by_hour.get(gu_code):
            hourly_pop = gu_pop_by_hour[gu_code].get(hour)
            if hourly_pop is not None:
                location['population'] = hourly_pop
                location['population_type'] = 'gu_hourly'

    # 시간대가 지정된 경우 영업중인 화장실만 추천 대상으로 사용
    if hour is not None:
        open_toilets = [t for t in data['toilets'] if is_open(t.get('open_time', ''), hour) is not False]
        used_fallback = len(open_toilets) == 0
        toilets_for_recommend = open_toilets if not used_fallback else data['toilets']
    else:
        toilets_for_recommend = data['toilets']
        used_fallback = False

    # 직접 검색된 화장실이 영업종료 필터에서 제외됐으면 복원
    if matched_toilet is not None:
        _mt_x = round(matched_toilet.get('x', 0), 5)
        _mt_y = round(matched_toilet.get('y', 0), 5)
        _already_in = any(
            round(t.get('x', 0), 5) == _mt_x and round(t.get('y', 0), 5) == _mt_y
            for t in toilets_for_recommend
        )
        if not _already_in:
            toilets_for_recommend = [matched_toilet] + list(toilets_for_recommend)
            print(f"[DEBUG] 직접 검색된 화장실 영업종료 필터에서 복원: {matched_toilet.get('name')}")

    recommendations = recommend_toilets(location, toilets_for_recommend) #30
    print(f"[DEBUG] TOP5 1위: {recommendations[0][1].get('name')} / {recommendations[0][1].get('addr_new')} / {int(recommendations[0][0])}m" if recommendations else "[DEBUG] 추천 없음")
    grade = classify_grade(location, recommendations, data['html_max'], data['html_min']) #28
    need = additional_need(grade) #29

    max_distance = max(distance for distance, _ in recommendations)

    top5 = []
    for idx, (distance, toilet) in enumerate(recommendations, start=1):

        # 거리 기반 접근성 점수 계산 (0~100). 접근성이 0이면 접근 불가능하다는 뜻이 아니라 접근하기 제일 어렵다는 뜻
        accessibility_score = round(
            (1 - (distance / max_distance)) * 100,
            2
        )

        open_time_str = toilet.get('open_time', '')
        if hour is None:
            status = '-'
        else:
            _open = is_open(open_time_str, hour)
            if _open is True:
                status = '영업중'
            elif _open is False:
                status = '영업종료'
            else:
                # 판정 불가 → 유형/개방시간 기반으로 표시 문구 결정
                _tstr = (' '.join([
                    toilet.get('full_type', '') or '',
                    toilet.get('location_type', '') or '',
                ])).lower()
                _is_subway = any(k in _tstr for k in ('지하철', '역사', '전철'))
                if not _is_subway and open_time_str:
                    _is_subway = '영업시작' in open_time_str.lower()
                status = '역사 운영시간' if _is_subway else '확인 필요'

        top5.append({
            'rank': idx,
            'name': toilet.get('name') or toilet.get('addr_new') or toilet.get('addr_old') or toilet.get('location_type') or '',
            'address': toilet.get('addr_new') or toilet.get('addr_old') or '',
            'distance_m': int(distance),
            'accessibility_score': accessibility_score,
            '구': toilet.get('gu', ''),
            '유형': toilet.get('location_type') or toilet.get('full_type') or '',
            'open_time': open_time_str,
            '영업상태': status,
            'x': toilet.get('x'),
            'y': toilet.get('y'),
        })


    # 자치구 내 화장실 수 (gu 기준 fallback용)
    gu_norm = normalize_text(location.get('gu', '')) #2
    toilet_count = sum(1 for t in data['toilets'] if normalize_text(t.get('gu', '')) == gu_norm) if gu_norm else len(data['toilets'])

    # ─── 검색 위치 → 동 Polygon 매칭 (gu/address/token 타입) ─────────────────────
    _lx, _ly = location.get('x'), location.get('y')
    print(f"[DEBUG] 검색어: {cleaned_query} | 좌표 x={_lx}, y={_ly}")
    if not location.get('dong_code') and _lx is not None and _ly is not None:
        _dong_match = find_dong_for_point(_lx, _ly)
        if _dong_match and _dong_match.get('dong_cd'):
            location['dong_code'] = _dong_match['dong_cd']
            if not location.get('dong'):
                location['dong'] = _dong_match['dong_nm']
            if not location.get('gu_code'):
                location['gu_code'] = _dong_match['gu_cd']
            print(f"[DEBUG] 공간조인 성공: dong_cd={_dong_match['dong_cd']}, dong_nm={_dong_match['dong_nm']}, gu_nm={_dong_match['gu_nm']}")
        else:
            print(f"[DEBUG] 공간조인 실패: 좌표 ({_lx}, {_ly}) 가 경계 밖 또는 매칭 없음 → 자치구 fallback")
    else:
        if location.get('dong_code'):
            print(f"[DEBUG] dong_code 이미 있음: {location.get('dong_code')}")

    # ─── 행정동 기준 분석 (공간조인 결과 활용) ──────────────────────────────
    dong_code = str(location.get('dong_code') or '')
    dong_shortage_table = data.get('dong_shortage_table', [])
    dong_raw_min = data.get('dong_raw_min')
    dong_raw_max = data.get('dong_raw_max')

    dong_toilet_count    = None
    dong_shortage_index  = None
    dong_display_grade   = None
    dong_display_priority = None
    dong_pop_per_toilet  = None
    dong_rank            = None
    dong_gu_rank         = None
    total_gu_dong_count  = None
    dong_hourly_pop_data = {}
    total_dong_count     = len(dong_shortage_table)

    if dong_code:
        # 법정동 내 화장실 수 (공간조인 기반)
        dong_toilet_count = sum(
            1 for t in data['toilets'] if t.get('sjoin_dong_code') == dong_code
        )

        # 면적 비율로 자치구 인구 분배 → 법정동 시간대 인구 추정
        _dong_area  = data.get('dong_area_map', {}).get(dong_code, 0.0)
        _gu_cd_dong = data.get('dong_to_gu_map', {}).get(dong_code, '') or location.get('gu_code', '')
        _gu_area    = data.get('gu_area_map', {}).get(_gu_cd_dong, 0.0)
        _gu_hourly  = data.get('gu_pop_by_hour', {}).get(_gu_cd_dong, {})

        if _dong_area > 0 and _gu_area > 0 and _gu_hourly:
            _ratio = _dong_area / _gu_area
            dong_hourly_pop_data = {h: p * _ratio for h, p in _gu_hourly.items()}
        else:
            dong_hourly_pop_data = {}

        dong_pop_hour = dong_hourly_pop_data.get(hour) if (hour is not None and dong_hourly_pop_data) else None

        if dong_toilet_count and dong_toilet_count > 0 and dong_pop_hour is not None:
            dong_raw = dong_pop_hour / dong_toilet_count
            # build_dong_shortage_table과 동일하게 log1p 변환 후 정규화
            dong_log = math.log1p(dong_raw)
            dong_shortage_index   = compute_shortage_index(dong_log, dong_raw_min, dong_raw_max) #25_idx
            dong_display_grade    = grade_from_index(dong_shortage_index) #25_grade
            dong_display_priority = priority_from_grade(dong_display_grade) #25_priority
            dong_pop_per_toilet   = round(dong_pop_hour / dong_toilet_count)
            location['population'] = dong_pop_hour
            location['population_type'] = 'dong_area_weighted'

        # 서울시 법정동 내 순위 (정적 평균 기준)
        _sorted_dong = sorted(
            dong_shortage_table, key=lambda r: r.get('shortage_index') or 0, reverse=True
        )
        dong_rank = next(
            (i + 1 for i, r in enumerate(_sorted_dong) if r.get('dong_code') == dong_code),
            None
        )
        _in_table = any(r.get('dong_code') == dong_code for r in dong_shortage_table)
        print(f"[DEBUG] dong_cd={dong_code}: 테이블조회={'성공' if _in_table else '실패'} | toilet수={dong_toilet_count}, 순위={dong_rank}, dong_idx={dong_shortage_index}")

        # 자치구 내 동 단위 순위
        _gu_nm_for_rank = location.get('gu', '')
        _gu_dongs = [r for r in dong_shortage_table if r.get('gu_nm') == _gu_nm_for_rank]
        total_gu_dong_count = len(_gu_dongs)
        _sorted_gu_dongs = sorted(_gu_dongs, key=lambda r: r.get('shortage_index') or 0, reverse=True)
        dong_gu_rank = next(
            (i + 1 for i, r in enumerate(_sorted_gu_dongs) if r.get('dong_code') == dong_code),
            None
        )

    # ─── 자치구 기준 지표 (fallback 또는 gu 타입 검색) ──────────────────────
    raw_score = location.get('score')
    shortage_index   = compute_shortage_index(raw_score, data.get('score_min'), data.get('score_max')) #25_idx
    display_grade    = grade_from_index(shortage_index) if shortage_index is not None else grade #25_grade
    display_priority = priority_from_grade(display_grade) #25_priority

    score_table = data.get('score_table', [])
    _sorted_gu = sorted([r for r in score_table if r['raw_score'] is not None], key=lambda r: r['raw_score'], reverse=True)
    gu_rank = next((i + 1 for i, r in enumerate(_sorted_gu) if r['gu_norm'] == gu_norm), None)
    total_gu_count = len(_sorted_gu)

    # 시간대별 그래프 데이터 (행정동 있으면 행정동, 없으면 자치구)
    if dong_hourly_pop_data:
        hourly_pop_data = dong_hourly_pop_data
    else:
        gu_code = location.get('gu_code')
        hourly_pop_data = dict(data.get('gu_pop_by_hour', {}).get(gu_code, {})) if gu_code else {}

    # 화장실 1개당 담당 인구 (행정동 있으면 행정동, 없으면 자치구 기준)
    pop_val = location.get('population')
    if dong_pop_per_toilet is not None:
        pop_per_toilet = dong_pop_per_toilet
    else:
        pop_per_toilet = round(pop_val / toilet_count) if (pop_val is not None and toilet_count > 0) else None

    return {
        'error': None,
        'query': cleaned_query,
        'location': location,
        'recommendations': top5,
        'grade': grade,
        'additional_need': need,
        'used_fallback': used_fallback,
        # 자치구 기준
        'toilet_count': toilet_count,
        'shortage_index': shortage_index,
        'display_grade': display_grade,
        'display_priority': display_priority,
        'gu_rank': gu_rank,
        'total_gu_count': total_gu_count,
        # 행정동 기준 (공간조인 성공 시)
        'dong_toilet_count': dong_toilet_count,
        'dong_shortage_index': dong_shortage_index,
        'dong_display_grade': dong_display_grade,
        'dong_display_priority': dong_display_priority,
        'dong_rank': dong_rank,
        'total_dong_count': total_dong_count,
        'dong_gu_rank': dong_gu_rank,
        'total_gu_dong_count': total_gu_dong_count,
        # 공통
        'hourly_pop_data': hourly_pop_data,
        'pop_per_toilet': pop_per_toilet,
        'seoul_avg_per_toilet': data.get('seoul_avg_per_toilet'),
    }

#26
# 입력된 위치에서 가장 가까운 공중화장실을 추천하는 함수입니다.
def average_distance(recommendations):
    if not recommendations:
        return None
    return sum(distance for distance, _ in recommendations) / len(recommendations)

#27
# 사용자가 입력한 검색어를 기반으로 가장 적합한 위치 정보를 찾는 함수입니다.
# hour: 시간대 (0-23), None이면 기존 동작 유지
def find_reference_location(query, toilets, score_map, dong_info, gu_info, gu_pop, dong_pop, dong_alias_map, hour=None):
    query_norm = normalize_text(query) #2
    if not query_norm:
        return None

    # 공중화장실 매칭: 검색어와 공중화장실 이름 또는 주소의 다양한 변형을 비교하여 완전 일치하는 공중화장실을 찾습니다.
    query_variants = generate_query_variants(query) #8

    # 1순위: 공중화장실 주소·건물명 직접 매칭 (동/구 매칭보다 먼저 수행)
    # Pass 1: 완전 일치 – toilet text ∈ query_variants
    _direct_match = None
    for _t in toilets:
        for _field in ['addr_new', 'addr_old', 'name']:
            _ttext = normalize_text(_t.get(_field, '')) #2
            if _ttext and _ttext in query_variants:
                _direct_match = _t
                break
        if _direct_match:
            break
    # Pass 2: 포함 일치 – 7자 이상 긴 검색어가 toilet 주소/이름에 포함됨
    # (화면에서 주소를 부분 복사한 경우에도 매칭 가능)
    if not _direct_match and len(query_norm) >= 7:
        for _t in toilets:
            for _field in ['addr_new', 'addr_old', 'name']:
                _ttext = normalize_text(_t.get(_field, '')) #2
                if _ttext and query_norm in _ttext:
                    _direct_match = _t
                    break
            if _direct_match:
                break
    if _direct_match:
        _et = _direct_match
        _gu = _et.get('gu', '')
        _gu_norm = normalize_text(_gu) #2
        _gu_code = gu_info.get(_gu_norm, {}).get('code')
        print(f"[DEBUG] match_type=exact_toilet | name={_et.get('name')} | addr={_et.get('addr_new')} | representative_x={_et['x']:.5f}, representative_y={_et['y']:.5f}")
        return {
            'name': _et.get('name') or _et.get('addr_new') or query,
            'type': 'exact_toilet',
            'x': _et['x'],
            'y': _et['y'],
            'gu': _gu,
            'dong': None,
            'dong_code': None,
            'gu_code': str(_gu_code) if _gu_code else None,
            'score': score_map.get(_gu_norm),
            'population': gu_pop.get(_gu_code),
            'population_type': 'gu' if _gu_code else None,
            'boundary_geojson': get_boundary_geojson_for_gu(_gu_norm, gu_info), #15
            '_matched_toilet': _et,
        }

    # 행정동 매칭: 검색어와 행정동 이름의 다양한 변형을 비교하여 가장 적합한 행정동을 찾습니다.
    dong_norm = find_best_dong_match(query, query_norm, dong_info, gu_info, dong_alias_map) #9
    if dong_norm:
        info = dong_info[dong_norm]
        code = info.get('code')
        gu = info.get('gu')
        centroid = info.get('centroid', (None, None))
        gu_code = gu_info.get(normalize_text(gu), {}).get('code') #2
        population, population_type = get_population_for_dong(code, dong_pop, gu_pop, gu_code, hour=hour) #19
        return {
            'name': info['name'],
            'type': 'dong',
            'x': centroid[0],
            'y': centroid[1],
            'gu': gu,
            'dong': info['name'],
            'dong_code': str(code) if code else None,
            'gu_code': str(gu_code) if gu_code else None,
            'score': score_map.get(normalize_text(gu)), #2
            'population': population,
            'population_type': population_type,
            'boundary_geojson': build_geojson_feature_collection([info.get('geometry')]), #14
        }

    # 자치구 매칭: 검색어와 자치구 이름의 다양한 변형을 비교하여 가장 적합한 자치구를 찾습니다.
    gu_candidates = [gu for gu in score_map.keys() if any(qv in gu or gu in qv for qv in query_variants)]
    if gu_candidates:
        gu_norm = max(gu_candidates, key=len)
        info = gu_info.get(gu_norm, {})
        centroid = info.get('centroid', (None, None))
        matched = [t for t in toilets if normalize_text(t['gu']) == gu_norm] #2
        if matched:
            avg_x = sum(t['x'] for t in matched) / len(matched)
            avg_y = sum(t['y'] for t in matched) / len(matched)
        else:
            avg_x, avg_y = centroid
        gu_code = info.get('code')
        return {
            'name': info.get('name') or query,
            'type': 'gu',
            'x': avg_x,
            'y': avg_y,
            'gu': info.get('name') or query,
            'dong': None,
            'dong_code': None,
            'gu_code': str(gu_code) if gu_code else None,
            'score': score_map.get(gu_norm),
            'population': gu_pop.get(gu_code),
            'population_type': 'gu',
            'boundary_geojson': get_boundary_geojson_for_gu(gu_norm, gu_info), #15
        }



    # 토큰 매칭: 검색어에서 한글과 숫자 토큰을 분리하여 공중화장실 데이터의 텍스트와 비교하여 가장 유사한 공중화장실을 찾습니다.
    tokens = [token for token in re.findall(r'[가-힣0-9]+', query) if len(token) >= 2]
    if tokens:
        best = None
        for t in toilets:
            score = 0
            # 비어있지 않은 필드만 join하여 target_text가 실질적 내용을 갖도록 함
            fields = [normalize_text(t.get(f, '')) for f in ['name', 'addr_new', 'addr_old', 'gu', 'location_type']] #2
            target_text = ' '.join(f for f in fields if f)
            if not target_text:
                continue
            for token in tokens:
                if token and token in target_text:
                    score += 1
            if score > 0:
                best = best or []
                best.append((score, t))
        if best:
            best.sort(key=lambda item: (-item[0], item[1]['name']))
            matches = [item[1] for item in best[:10]]
            avg_x = sum(t['x'] for t in matches) / len(matches)
            avg_y = sum(t['y'] for t in matches) / len(matches)
            gu = matches[0].get('gu', '')
            gu_norm = normalize_text(gu) #2
            gu_code = gu_info.get(gu_norm, {}).get('code')
            return {
                'name': query,
                'type': 'token',
                'x': avg_x,
                'y': avg_y,
                'gu': gu,
                'dong': None,
                'dong_code': None,
                'gu_code': str(gu_code) if gu_code else None,
                'score': score_map.get(gu_norm),
                'population': gu_pop.get(gu_code),
                'population_type': 'gu' if gu_code else None,
                'boundary_geojson': get_boundary_geojson_for_gu(gu_norm, gu_info), #15
            }

    return None

#28
# 추천된 공중화장실과의 평균 거리를 기반으로 등급을 분류하는 함수입니다.
def classify_grade(location, recommendations, max_score=None, min_score=None):

    # HTML 값이 전달되지 않은 경우 자동 로드
    if max_score is None or min_score is None:
        max_score, min_score = load_html_metrics() #23

    score = location.get('score')
    avg_distance = average_distance(recommendations)
    population = location.get('population')

    grade = '보통'

    # HTML 기준 상대 점수 계산
    if (
        score is not None and
        max_score is not None and
        min_score is not None and
        max_score > min_score
    ):
        relative_score = (
            score - min_score
        ) / (
            max_score - min_score
        )

        if relative_score >= 0.7:
            grade = '부족'
        elif relative_score >= 0.4:
            grade = '보통'
        else:
            grade = '충분'

    # 절대 부족도 점수 보정
    if score is not None:
        if score >= 0.35:
            grade = '부족'
        elif score >= 0.20:
            grade = '보통'
        else:
            grade = '충분'

    elif avg_distance is not None:
        if avg_distance > 1200:
            grade = '부족'
        elif avg_distance > 700:
            grade = '보통'
        else:
            grade = '충분'

    # 인구 보정
    if population is not None and avg_distance is not None:
        if population >= 40000 and avg_distance > 900:
            grade = '부족'
        elif population >= 25000 and avg_distance > 1200:
            grade = '부족'
        elif population < 15000 and avg_distance < 600 and grade == '보통':
            grade = '충분'

    # 거리 보정
    if avg_distance is not None:
        if avg_distance > 1500 and grade == '충분':
            grade = '보통'
        if avg_distance > 2000:
            grade = '부족'

    return grade

#29
# 등급에 따른 추가 설치 필요도를 반환하는 함수입니다.
def additional_need(grade):
    if grade == '부족':
        return '높음'
    if grade == '보통':
        return '보통'
    return '낮음'

#30
# 입력된 위치에서 가장 가까운 공중화장실을 추천하는 함수입니다.
def recommend_toilets(location, toilets, top_n=5):
    distances = []
    for t in toilets:
        distance = haversine(location['x'], location['y'], t['x'], t['y']) #11
        distances.append((distance, t))
    distances.sort(key=lambda item: item[0])
    return distances[:top_n]

#31
# 검색어, 추정된 위치 정보, 추천된 공중화장실 목록, 등급을 출력하는 함수입니다.
def print_results(query, location, recommendations, grade):
    print('\n입력 지역:', query)
    print('추정 지역:', location.get('name'))
    if location.get('type'):
        print('검색 타입:', location['type'])
    if location.get('dong'):
        print('행정동:', location['dong'])
    if location.get('population') is not None:
        print('대상 인구 수 (추정):', int(location['population']))

    print('\n가까운 공중화장실 TOP 5')
    for index, (distance, toilet) in enumerate(recommendations, start=1):
        label = toilet['name'] or toilet['addr_new'] or toilet['addr_old'] or toilet['location_type']
        print(f"{index}. {label} - {int(distance)}m")

    print(f"\n해당 지역 접근성 등급: {grade}")
    print(f"추가 설치 필요도: {additional_need(grade)}") #29

#31c
# 서울시 행정동별 부족도 순위 테이블 반환 (ancient_monarch.py TOP 10 표시용)
def get_dong_shortage_ranking():
    data = load_app_data() #24
    table = data.get('dong_shortage_table', [])
    if not table:
        return []
    result = []
    for i, r in enumerate(
        sorted(table, key=lambda x: x.get('shortage_index') or 0, reverse=True), start=1
    ):
        tc = r['toilet_count']
        avg_pop = r['avg_pop']
        result.append({
            '순위': i,
            '자치구': r['gu_nm'],
            '행정동': r['dong_nm'],
            '부족도 지수': f"{r['shortage_index']:.1f}점" if r['shortage_index'] is not None else '-',
            '접근성 등급': r['grade'],
            '설치 우선도': r['priority'],
            '공중화장실 수': f"{tc}개",
            '화장실1개당인구': f"약 {round(avg_pop / tc):,}명" if tc > 0 else '-',
        })
    return result

#31b
# 서울시 자치구별 부족도 순위 테이블 반환 (ancient_monarch.py TOP 10 표시용)
def get_shortage_ranking():
    data = load_app_data() #24
    score_table = data.get('score_table', [])
    score_min = data.get('score_min')
    score_max = data.get('score_max')
    if not score_table:
        return []
    result = []
    for i, row in enumerate(
        sorted(score_table, key=lambda r: r.get('raw_score') or 0, reverse=True), start=1
    ):
        idx = compute_shortage_index(row['raw_score'], score_min, score_max) #25_idx
        grade = grade_from_index(idx) #25_grade
        priority = priority_from_grade(grade) #25_priority
        result.append({
            '순위': i,
            '지역': row['gu'],
            '부족도 지수': f"{idx:.1f}점" if idx is not None else '-',
            '접근성 등급': grade,
            '설치 우선도': priority,
            '화장실 수': f"{row['toilet_count']}개",
            '인구1만명당 화장실': f"{row['per_10k']:.2f}개",
        })
    return result

#31e
# 특정 자치구의 동 단위 부족도 순위 테이블 반환 (검색 결과 자치구 내 우선지역 표시용)
def get_gu_dong_ranking(gu_nm):
    data = load_app_data() #24
    table = data.get('dong_shortage_table', [])
    if not table or not gu_nm:
        return []
    filtered = sorted(
        [r for r in table if r.get('gu_nm') == gu_nm],
        key=lambda x: x.get('shortage_index') or 0, reverse=True,
    )
    result = []
    for i, r in enumerate(filtered, start=1):
        tc = r['toilet_count']
        avg_pop = r['avg_pop']
        result.append({
            '순위': i,
            '_dong_code': r['dong_code'],
            '행정동': r['dong_nm'],
            '부족도 지수': f"{r['shortage_index']:.1f}점" if r['shortage_index'] is not None else '-',
            '접근성 등급': r['grade'],
            '설치 우선도': r['priority'],
            '공중화장실 수': f"{tc}개",
            '화장실1개당담당인구': f"약 {round(avg_pop / tc):,}명" if tc > 0 else '-',
        })
    return result

# 애플리케이션의 진입점.
# 필요한 데이터를 로드하고,
# 사용자로부터 검색어를 입력받아 공중화장실 위치를 검색하고, 
# 추천된 공중화장실과 등급을 출력합니다.
def main():
    toilets = load_toilet_data() #21
    if not toilets:
        print('공중화장실 데이터를 불러올 수 없습니다.')
        return

    score_map = load_shortage_scores() #22
    dong_info, gu_info, dong_alias_map = load_dong_boundary() #12
    gu_pop = load_population_csv(GU_POP_CSV_FILE, code_index=2, total_index=3) #16
    dong_pop = load_dong_population() #18
    jibgye_pop = load_jibgye_population() #20
    for code, total in jibgye_pop.items():
        if code not in dong_pop:
            dong_pop[code] = total
    html_max, html_min = load_html_metrics() #23

    query = input('검색할 지역명(자치구/행정동/지하철역/주변 명칭): ').strip()
    if not query:
        print('지역명을 입력해 주세요.')
        return

    location = find_reference_location(query, toilets, score_map, dong_info, gu_info, gu_pop, dong_pop, dong_alias_map) #27
    if not location or location.get('x') is None or location.get('y') is None:
        print('입력한 지역에서 공중화장실 위치를 찾을 수 없습니다. 다른 자치구 또는 주소명을 입력해 주세요.')
        return

    recommendations = recommend_toilets(location, toilets) #30
    
    grade = classify_grade(location, recommendations, html_max, html_min) #28
    print_results(query, location, recommendations, grade) #31


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)