# src/analysis/m01_subject.py

class TradingSubjectModel:
    def calculate_score(self, ticker):
        # 1. API 데이터 로드 (최근 10일)
        from src.ingestion.market_data import get_trading_volume_data
        df = get_trading_volume_data(ticker)
        
        if df.empty:
            return 0
        
        # 2. 핵심 지표 추출 (외국인, 기관합계)
        # pykrx 데이터 컬럼: '외국인', '기관합계', '개인' 등
        recent_5 = df.tail(5)
        
        foreign_buy = recent_5['외국인'].sum()
        inst_buy = recent_5['기관합계'].sum()
        total_vol = recent_5['거래량'].sum()
        
        # 3. 수급 강도(Buy Power) 계산
        # 전체 거래량 대비 메이저(외인+기관)의 순매수 비중
        major_net_buy = foreign_buy + inst_buy
        buy_power_score = (major_net_buy / total_vol) * 100 if total_vol > 0 else 0
        
        # 4. 가중치 적용 (개인이 팔고 메이저가 살 때 가점)
        individual_sell = recent_5['개인'].sum()
        multiplier = 1.0
        if individual_sell < 0 and major_net_buy > 0:
            multiplier = 1.2 # 개인이 털린 물량을 메이저가 받을 때
            
        # 5. 최종 점수 정규화 (0~100)
        final_score = min(max(buy_power_score * multiplier * 10, 0), 100)
        
        return {
            "model": "M01",
            "score": round(final_score, 2),
            "details": {
                "foreign": foreign_buy,
                "institutional": inst_buy,
                "major_net": major_net_buy
            }
        }