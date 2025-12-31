import pandas as pd
import numpy as np

class SupplyScanner:
    """
    M-01: 수급 선행성 분석 모듈
    입력된 수급 데이터를 바탕으로 매수 에너지를 점수화함.
    """
    def __init__(self, weights={'foreign': 0.6, 'institution': 0.4}):
        # 가중치 설정 (설계 청사진 V2.4 반영)
        self.weights = weights
        self.threshold = 50  # 매수 우위 판단 임계값

    def calculate_supply_score(self, data):
        """
        data: {
            'foreign_net': [3일전, 2일전, 1일전 순매수량],
            'inst_net': [3일전, 2일전, 1일전 순매수량],
            'volume': 현재 거래량
        }
        """
        try:
            # 1. 외인 에너지 계산 (최근 일자에 가중치 부여)
            f_energy = np.average(data['foreign_net'], weights=[0.2, 0.3, 0.5])
            
            # 2. 기관 에너지 계산
            i_energy = np.average(data['inst_net'], weights=[0.2, 0.3, 0.5])
            
            # 3. 정규화 (예시: 특정 임계치 대비 비율로 0~100점 환산)
            # 실제 구현시에는 종목별 유통물량 대비 비율로 산정하는 것이 정확함
            f_score = self._normalize(f_energy)
            i_score = self._normalize(i_energy)
            
            # 4. 최종 가중치 합산 (Weighted Sum)
            final_score = (f_score * self.weights['foreign']) + (i_score * self.weights['institution'])
            
            return round(final_score, 2)
            
        except Exception as e:
            print(f"Error in Scanner Logic: {e}")
            return 0

    def _normalize(self, value):
        # 단순 선형 정규화 예시 (로직 설계 단계에서 튜닝 필요)
        if value <= 0: return 0
        score = (value / 1000000) * 100 # 100만주 기준 100점 (가정)
        return min(score, 100)

# --- 시뮬레이션 코드 ---
if __name__ == "__main__":
    scanner = SupplyScanner()
    
    # 가상의 샘플 데이터 (최근으로 갈수록 매수세 강화)
    sample_data = {
        'foreign_net': [10000, 50000, 150000],
        'inst_net': [-5000, 20000, 80000],
        'volume': 500000
    }
    
    result = scanner.calculate_supply_score(sample_data)
    print(f"✅ 검측된 수급 매력도: {result}점")