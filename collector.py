import io
import os
from datetime import datetime

import pandas as pd
import requests


class KRXApiClient:
    DATE_COLUMNS = ("TRD_DD", "TRD_DE", "TDD", "BASE_DT", "TRADE_DATE")
    OHLCV_COLUMN_MAP = {
        "OPNPRC": "시가",
        "OPEN_PRC": "시가",
        "HGPRC": "고가",
        "HIGH_PRC": "고가",
        "LWPRC": "저가",
        "LOW_PRC": "저가",
        "CLSPRC": "종가",
        "CLOSE_PRC": "종가",
        "TRDVOL": "거래량",
        "VOLUME": "거래량",
    }
    INVESTOR_COLUMN_MAP = {
        "INDV": "개인",
        "INDV_SUM": "개인",
        "FORN": "외국인합계",
        "FRGN": "외국인합계",
        "FOREIGN": "외국인합계",
        "INST": "기관합계",
        "INST_SUM": "기관합계",
        "ORG": "기관합계",
    }

    def __init__(self):
        self.api_key = os.getenv("KRX_API_KEY")
        self.ohlcv_url = os.getenv(
            "KRX_OHLCV_URL",
            "https://openapi.krx.co.kr/contents/OPP/ODM/02/03010000/ODM03010000_list.jsp",
        )
        self.investor_url = os.getenv(
            "KRX_INVESTOR_URL",
            "https://openapi.krx.co.kr/contents/OPP/OTD/01/01010100/OTD01010100_list.jsp",
        )

    def _request_json(self, url, params):
        if not self.api_key:
            return None
        payload = {"AUTH_KEY": self.api_key, **params}
        response = requests.get(url, params=payload, timeout=10)
        if response.status_code != 200:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _extract_records(payload):
        if not payload:
            return []
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for value in payload.values():
                if isinstance(value, list) and value and isinstance(value[0], dict):
                    return value
        return []

    def _normalize_dataframe(self, records, column_map, date_columns):
        if not records:
            return pd.DataFrame()
        df = pd.DataFrame(records)
        date_column = next((col for col in date_columns if col in df.columns), None)
        if not date_column:
            return pd.DataFrame()
        df[date_column] = pd.to_datetime(df[date_column])
        df.set_index(date_column, inplace=True)
        renamed = {col: column_map.get(col, col) for col in df.columns}
        df.rename(columns=renamed, inplace=True)
        numeric_cols = [col for col in df.columns if col != date_column]
        df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric, errors="coerce")
        return df

    def get_ohlcv_by_date(self, ticker, start_date, end_date):
        params = {
            "isuCd": ticker,
            "strtDd": start_date,
            "endDd": end_date,
        }
        payload = self._request_json(self.ohlcv_url, params)
        records = self._extract_records(payload)
        df = self._normalize_dataframe(records, self.OHLCV_COLUMN_MAP, self.DATE_COLUMNS)
        if df.empty:
            return df
        for required in ("시가", "고가", "저가", "종가", "거래량"):
            if required not in df.columns:
                df[required] = 0
        return df

    def get_investor_trading_by_date(self, ticker, start_date, end_date, share="2"):
        params = {
            "isuCd": ticker,
            "strtDd": start_date,
            "endDd": end_date,
            "share": share,
            "money": "1",
        }
        payload = self._request_json(self.investor_url, params)
        records = self._extract_records(payload)
        df = self._normalize_dataframe(records, self.INVESTOR_COLUMN_MAP, self.DATE_COLUMNS)
        if df.empty:
            return df
        return df

class DataCollector:
    @staticmethod
    def get_full_analysis(ticker, start_date, end_date):
        api_client = KRXApiClient()
        # 1. 데이터 수집 (시세 및 세부 투자자별 거래대금)
        df_p = api_client.get_ohlcv_by_date(ticker, start_date, end_date)
        df_i = api_client.get_investor_trading_by_date(
            ticker, start_date, end_date, share="2"
        )

        # 데이터가 아예 없는 경우 방어 로직
        if df_p.empty or df_i.empty:
            return None

        # 2. 🌟 핵심 수술: 두 데이터를 날짜 인덱스 기준으로 'inner join' 합치기
        # 이 과정을 거치면 df_p와 df_i 양쪽에 모두 데이터가 있는 날짜만 남습니다.
        # 즉, dates, prices, trend_data의 길이가 100% 일치하게 됩니다.
        df_combined = pd.concat([df_p, df_i], axis=1, join='inner')

        # 3. 빈 데이터(NaN) 메우기
        # 혹시 모를 빈칸은 직전 데이터로 채우고(ffill), 나머지는 0으로 채웁니다(fillna).
        # 차트(Plotly)가 'None'을 받아서 2012년으로 튀는 것을 막는 결정적 단계입니다.
        df_combined = df_combined.ffill().fillna(0)

        # 2. 누적 데이터 (억 원 단위)
        df_cum = df_combined[df_i.columns].cumsum()
        cum_data = {col: (df_cum[col] / 1e8).round(2).tolist() for col in df_i.columns}

        # 4. 리스트 변환 (JavaScript가 읽기 좋은 형태)
        dates = df_combined.index.strftime('%Y-%m-%d').tolist()
        prices = df_combined['종가'].astype(int).tolist()
        
        # 각 투자 주체별 데이터를 '억 원' 단위로 변환하여 리스트화
        # df_i.columns는 '기관합계', '외국인합계' 등의 주체 이름을 담고 있습니다.
        trend_data = {}
        for col in df_i.columns:
            trend_data[col] = (df_combined[col] / 1e8).round(2).tolist()

        # 5. 마지막 영업일 요약 정보 (UI 상단 그리드용)
        last_metrics = {col: round(float(df_combined[col].iloc[-1]) / 1e8, 2) for col in df_i.columns}

        return {
            "ticker_name": ticker,
            "ticker_code": ticker,
            "current_price": f"{int(df_combined['종가'].iloc[-1]):,} 원",
            "last_metrics": last_metrics,
            "daily_trend": trend_data,
            "cum_trend": cum_data,       # 누적 추가
            "prices": prices, # ✅ dates와 길이가 동일한 가격 리스트
            "dates": dates,   # ✅ 기준이 되는 날짜 리스트
            "timestamp": datetime.now().strftime('%H:%M:%S')
    }
    @staticmethod
    def generate_excel(ticker, start_date, end_date):
        # 시세와 11개 이상의 투자 주체 데이터 병합 및 엑셀 생성 (v4.8 로직)
        api_client = KRXApiClient()
        df_p = api_client.get_ohlcv_by_date(ticker, start_date, end_date)
        df_i = api_client.get_investor_trading_by_date(
            ticker, start_date, end_date, share="1"
        )
        
        df_final = pd.concat([df_p, df_i], axis=1, join='inner')
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_final.to_excel(writer, sheet_name='Investor_Universe')
            worksheet = writer.sheets['Investor_Universe']
            for i in range(len(df_final.columns) + 1):
                worksheet.set_column(i, i, 15)
        output.seek(0)
        return output
