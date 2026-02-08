from collector import KisApiClient

import pandas as pd

class DataCollector:
    @staticmethod
    def get_krx_official_data(ticker, start_date, end_date):
        """(호환용) KIS OpenAPI를 호출하여 투자자 데이터를 가져오는 함수"""
        api_client = KisApiClient()
        return api_client.get_investor_trading_by_date(
            ticker,
            start_date.replace("-", ""),
            end_date.replace("-", ""),
            share="2",
        )

    @staticmethod
    def get_full_analysis(ticker, start_date, end_date):
        # 1. 시세 및 수급 데이터를 KIS OpenAPI에서 가져옵니다.
        api_client = KisApiClient()
        df_p = api_client.get_ohlcv_by_date(
            ticker,
            start_date.replace("-", ""),
            end_date.replace("-", ""),
        )
        
        # 🔥 이 부분이 핵심: 공식 API 호출로 교체
        df_i = DataCollector.get_krx_official_data(ticker, start_date, end_date)

        if df_p.empty:
            return None

        df_combined = df_p.copy()
        if df_i is not None and not df_i.empty:
            df_combined = df_combined.join(df_i, how="left")
        df_combined = df_combined.ffill().fillna(0)
        # ... (이하 기존 코드와 동일)
