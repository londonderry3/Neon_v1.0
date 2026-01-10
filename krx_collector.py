import io
import pandas as pd
import requests  # 추가
from datetime import datetime
from pykrx import stock

class DataCollector:
    @staticmethod
    def get_krx_official_data(ticker, start_date, end_date):
        """KRX 공식 API를 호출하여 투자자별 매매대금을 가져오는 함수"""
        API_KEY = "발급받으신_인증키_입력"
        # 실제 승인받은 서비스의 URL로 교체 필요
        url = "https://openapi.krx.co.kr/contents/OPP/OTD/01/01010100/OTD01010100_list.jsp"
        
        params = {
            "AUTH_KEY": API_KEY,
            "isuCd": ticker,
            "strtDd": start_date.replace("-", ""), # YYYYMMDD 형식
            "endDd": end_date.replace("-", ""),
            "share": "2", # 1:수량, 2:거래대금 (명세서 확인 필요)
            "money": "1"  # 단위 설정 등
        }
        
        response = requests.get(url, params=params)
        if response.status_code == 200:
            result = response.json()
            # KRX 응답의 'OutBlock_1' 데이터를 데이터프레임으로 변환
            # pykrx의 df_i와 컬럼명을 맞춰주는 작업이 여기서 필요합니다.
            raw_df = pd.DataFrame(result['OutBlock_1'])
            
            # 날짜를 인덱스로 설정 (명세서의 날짜 컬럼명 확인: 예 'TRD_DD')
            raw_df['TRD_DD'] = pd.to_datetime(raw_df['TRD_DD'])
            raw_df.set_index('TRD_DD', inplace=True)
            
            # 필요한 컬럼만 필터링 및 한글명 매핑 (pykrx와 동일하게)
            # 예: raw_df.rename(columns={'INST_SUM': '기관합계', ...})
            return raw_df
        return pd.DataFrame()

    @staticmethod
    def get_full_analysis(ticker, start_date, end_date):
        # 1. 시세는 여전히 pykrx가 잘 될 확률이 높지만, 
        # 수급 데이터(df_i)는 공식 API 함수로 대체합니다.
        df_p = stock.get_market_ohlcv_by_date(start_date, end_date, ticker)
        
        # 🔥 이 부분이 핵심: 공식 API 호출로 교체
        df_i = DataCollector.get_krx_official_data(ticker, start_date, end_date)

        if df_p.empty or df_i.empty:
            return None

        # 이후 합치고(join='inner') 누적(cumsum)하는 로직은 기존과 100% 동일!
        df_combined = pd.concat([df_p, df_i], axis=1, join='inner')
        # ... (이하 기존 코드와 동일)