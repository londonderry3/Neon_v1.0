# Neon_v1.0

## Market data (KIS OpenAPI)

이 프로젝트는 KIS OpenAPI를 통해 국내주식 OHLCV/투자자 데이터를 조회합니다.

1) 환경변수 설정
- `.env.example`를 참고해 `.env`를 생성하고 `KIS_APP_KEY`, `KIS_APP_SECRET`를 입력합니다.
- 모의투자: `KIS_ENV=demo` / 실전: `KIS_ENV=real`

2) 실행
- `python3 app.py`
- 브라우저에서 `http://127.0.0.1:5002` 접속

## Notes

- `KisApiClient.get_investor_trading_by_date()`는 KIS `inquire-investor` 응답의 `*_tr_pbmn` 값을 '원(KRW)'로 환산해서 반환합니다(원본은 '백만원' 단위).
- 더 상세한 수급(개인/외국인/기관의 매수·매도대금/매수·매도량)을 보고 싶으면 `KIS_INVESTOR_DETAIL=true`를 설정하세요.
