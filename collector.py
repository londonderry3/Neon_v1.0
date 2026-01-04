import io
import pandas as pd
from datetime import datetime, timedelta
import FinanceDataReader as fdr

class DataCollector:
    @staticmethod
    def get_full_analysis(ticker, start_date, end_date):
        # 1. 데이터 수집 (FinanceDataReader 기반)
        start = datetime.strptime(start_date, "%Y%m%d").strftime("%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y%m%d").strftime("%Y-%m-%d")
        df_price = fdr.DataReader(ticker, start, end)

        # 데이터가 아예 없는 경우 방어 로직
        if df_price.empty:
            return None

        df_p = df_price.rename(columns={'Close': '종가'}).copy()
        trading_value = (df_price['Close'] * df_price['Volume']) / 1e8
        df_i = pd.DataFrame({'거래대금': trading_value})

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
        start = datetime.strptime(start_date, "%Y%m%d").strftime("%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y%m%d").strftime("%Y-%m-%d")
        df_price = fdr.DataReader(ticker, start, end)
        df_p = df_price.rename(columns={'Close': '종가'})
        df_i = pd.DataFrame({'거래대금': (df_price['Close'] * df_price['Volume'])})
        df_final = pd.concat([df_p, df_i], axis=1, join='inner')
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_final.to_excel(writer, sheet_name='Investor_Universe')
            worksheet = writer.sheets['Investor_Universe']
            for i in range(len(df_final.columns) + 1):
                worksheet.set_column(i, i, 15)
        output.seek(0)
        return output
