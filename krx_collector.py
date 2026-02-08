from collector import KRXApiClient

import pandas as pd

class DataCollector:
    @staticmethod
    def get_krx_official_data(ticker, start_date, end_date):
        """KRX 공식 API를 호출하여 투자자별 매매대금을 가져오는 함수"""
        api_client = KRXApiClient()
        return api_client.get_investor_trading_by_date(
            ticker,
            start_date.replace("-", ""),
            end_date.replace("-", ""),
            share="2",
        )

    @staticmethod
    def get_full_analysis(ticker, start_date, end_date):
        # 1. 시세 및 수급 데이터를 공식 API에서 가져옵니다.
        api_client = KRXApiClient()
        df_p = api_client.get_ohlcv_by_date(
            ticker,
            start_date.replace("-", ""),
            end_date.replace("-", ""),
        )
        
        # 🔥 이 부분이 핵심: 공식 API 호출로 교체
        df_i = DataCollector.get_krx_official_data(ticker, start_date, end_date)

        if df_p.empty or df_i.empty:
            return None

        # 이후 합치고(join='inner') 누적(cumsum)하는 로직은 기존과 100% 동일!
        df_combined = pd.concat([df_p, df_i], axis=1, join='inner')
        # ... (이하 기존 코드와 동일)
