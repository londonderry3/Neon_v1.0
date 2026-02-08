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

- `KisApiClient.get_investor_trading_by_date()`는 KIS의 `inquire-investor` 엔드포인트 특성상 종목별 “최근 영업일” 데이터만 제공합니다(기간 시계열 제공 불가).
