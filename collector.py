import io
import os
import time
from datetime import datetime
from pathlib import Path

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
        self._load_dotenv_if_present()
        self.api_key = os.getenv("KRX_API_KEY")
        self.ohlcv_url = os.getenv(
            "KRX_OHLCV_URL",
            "https://openapi.krx.co.kr/contents/OPP/ODM/02/03010000/ODM03010000_list.jsp",
        )
        self.investor_url = os.getenv(
            "KRX_INVESTOR_URL",
            "https://openapi.krx.co.kr/contents/OPP/OTD/01/01010100/OTD01010100_list.jsp",
        )
        self.debug = os.getenv("KRX_API_DEBUG", "").strip().lower() in ("1", "true", "yes", "y", "on")
        self.session = requests.Session()
        self.last_error = None

    @staticmethod
    def _load_dotenv_if_present():
        try:
            from dotenv import load_dotenv  # type: ignore
        except Exception:
            return
        env_path = Path(__file__).resolve().parent / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path)

    def _debug(self, message: str):
        if self.debug:
            print(f"[KRX_API_DEBUG] {message}")

    @staticmethod
    def _truncate_text(text: str, limit: int = 300) -> str:
        if not text:
            return ""
        text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        if len(text) <= limit:
            return text
        return text[:limit] + "…"

    @staticmethod
    def _format_last_error(err) -> str:
        if not err:
            return ""
        if isinstance(err, str):
            return err
        if isinstance(err, dict):
            parts = []
            for key in ("status", "respCode", "respMsg", "url"):
                if err.get(key) not in (None, ""):
                    parts.append(f"{key}={err.get(key)}")
            if err.get("body"):
                parts.append(f"body={err.get('body')}")
            return " | ".join(parts)
        return str(err)

    def _request_json(self, url, params, *, method: str = "GET"):
        if not self.api_key:
            self.last_error = "Missing KRX_API_KEY (env)."
            return None

        self.last_error = None
        payload = {"AUTH_KEY": self.api_key, **params}
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/121.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            # KRX OPEN API 안내: Request 헤더 AUTH_KEY
            "AUTH_KEY": self.api_key,
            "Referer": "https://openapi.krx.co.kr/",
            "Origin": "https://openapi.krx.co.kr",
        }

        try:
            if method.upper() == "POST":
                response = self.session.post(url, data=payload, headers=headers, timeout=15)
            else:
                response = self.session.get(url, params=payload, headers=headers, timeout=15)
        except requests.RequestException as exc:
            self.last_error = {"url": url, "status": None, "respCode": None, "respMsg": str(exc), "body": None}
            self._debug(f"request failed: {self._format_last_error(self.last_error)}")
            return None

        if response.status_code != 200:
            self.last_error = {
                "url": url,
                "status": response.status_code,
                "respCode": None,
                "respMsg": None,
                "body": self._truncate_text(response.text),
            }
            self._debug(f"non-200: {self._format_last_error(self.last_error)}")
            return None
        try:
            data = response.json()
            if isinstance(data, dict) and ("respCode" in data or "respMsg" in data):
                # Data Marketplace Open API 스타일 에러
                code = data.get("respCode")
                msg = data.get("respMsg")
                if code and code != "000":
                    self.last_error = {"url": url, "status": 200, "respCode": code, "respMsg": msg, "body": None}
                    self._debug(f"api error: {self._format_last_error(self.last_error)}")
                    return None
            return data
        except ValueError:
            self.last_error = {
                "url": url,
                "status": 200,
                "respCode": None,
                "respMsg": "Non-JSON response",
                "body": self._truncate_text(response.text),
            }
            self._debug(f"json parse failed: {self._format_last_error(self.last_error)}")
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
        if payload is None and self.last_error:
            # 일부 엔드포인트는 POST만 허용하는 경우가 있어 fallback
            payload = self._request_json(self.ohlcv_url, params, method="POST")
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
        if payload is None and self.last_error:
            payload = self._request_json(self.investor_url, params, method="POST")
        records = self._extract_records(payload)
        df = self._normalize_dataframe(records, self.INVESTOR_COLUMN_MAP, self.DATE_COLUMNS)
        if df.empty:
            return df
        return df


class KisApiClient:
    """
    한국투자증권(KIS) OpenAPI 기반 시세 클라이언트.

    - OHLCV: 국내주식기간별시세(일/주/월/년) `inquire-daily-itemchartprice` (TR: FHKST03010100)
    - 투자자: 주식현재가 투자자 `inquire-investor` (TR: FHKST01010900)
      ※ 당일 데이터는 장 종료 후 제공되며, 기간별 시계열을 KRX처럼 제공하지 않습니다.
    """

    OHLCV_COLUMN_MAP = {
        "stck_oprc": "시가",
        "stck_hgpr": "고가",
        "stck_lwpr": "저가",
        "stck_clpr": "종가",
        "acml_vol": "거래량",
    }
    INVESTOR_COLUMN_MAP = {
        "prsn_ntby_tr_pbmn": "개인",
        "frgn_ntby_tr_pbmn": "외국인합계",
        "orgn_ntby_tr_pbmn": "기관합계",
    }

    def __init__(self):
        KRXApiClient._load_dotenv_if_present()
        self.env = os.getenv("KIS_ENV", "demo").strip().lower()  # demo | real
        self.base_url = os.getenv("KIS_BASE_URL", "").strip()
        if not self.base_url:
            self.base_url = (
                "https://openapivts.koreainvestment.com:29443"
                if self.env == "demo"
                else "https://openapi.koreainvestment.com:9443"
            )

        self.app_key = os.getenv("KIS_APP_KEY")
        self.app_secret = os.getenv("KIS_APP_SECRET")
        self.debug = os.getenv("KIS_API_DEBUG", "").strip().lower() in ("1", "true", "yes", "y", "on")

        self.session = requests.Session()
        self._access_token = None
        self._access_token_expire_ts = 0.0
        self.last_error = None

    def _debug(self, message: str):
        if self.debug:
            print(f"[KIS_API_DEBUG] {message}")

    def _ensure_token(self):
        if self._access_token and time.time() < (self._access_token_expire_ts - 30):
            return

        if not self.app_key or not self.app_secret:
            self.last_error = "Missing KIS_APP_KEY/KIS_APP_SECRET (env)."
            raise RuntimeError(self.last_error)

        url = f"{self.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Neon/1.0"}

        try:
            res = self.session.post(url, json=payload, headers=headers, timeout=15)
        except requests.RequestException as exc:
            self.last_error = f"Token request failed: {exc}"
            raise RuntimeError(self.last_error) from exc

        if res.status_code != 200:
            self.last_error = (
                f"Token request non-200: status={res.status_code} body={KRXApiClient._truncate_text(res.text)}"
            )
            raise RuntimeError(self.last_error)

        data = res.json()
        token = data.get("access_token")
        if not token:
            self.last_error = f"Token response missing access_token: {data}"
            raise RuntimeError(self.last_error)

        expire_ts = time.time() + 60 * 30
        expired_str = data.get("access_token_token_expired")
        if isinstance(expired_str, str):
            try:
                expire_dt = datetime.strptime(expired_str, "%Y-%m-%d %H:%M:%S")
                expire_ts = expire_dt.timestamp()
            except ValueError:
                pass
        elif isinstance(data.get("expires_in"), (int, float)):
            expire_ts = time.time() + float(data["expires_in"])

        self._access_token = token
        self._access_token_expire_ts = expire_ts
        self._debug("token refreshed")

    def _request_json(self, path: str, tr_id: str, params: dict):
        self._ensure_token()
        url = f"{self.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "authorization": f"Bearer {self._access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
            "User-Agent": "Neon/1.0",
        }

        try:
            res = self.session.get(url, params=params, headers=headers, timeout=15)
        except requests.RequestException as exc:
            self.last_error = f"request failed: {exc}"
            self._debug(self.last_error)
            return None

        if res.status_code != 200:
            self.last_error = (
                f"non-200: status={res.status_code} url={url} body={KRXApiClient._truncate_text(res.text)}"
            )
            self._debug(self.last_error)
            return None

        try:
            data = res.json()
        except ValueError:
            self.last_error = f"Non-JSON response: url={url} body={KRXApiClient._truncate_text(res.text)}"
            self._debug(self.last_error)
            return None

        rt_cd = data.get("rt_cd")
        if rt_cd and rt_cd != "0":
            self.last_error = f"api error: rt_cd={rt_cd} msg_cd={data.get('msg_cd')} msg1={data.get('msg1')}"
            self._debug(self.last_error)
            return None

        return data

    def get_ohlcv_by_date(self, ticker: str, start_date: str, end_date: str):
        path = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        tr_id = "FHKST03010100"
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start_date,
            "FID_INPUT_DATE_2": end_date,
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "1",
        }
        payload = self._request_json(path, tr_id, params)
        if not payload:
            return pd.DataFrame()

        records = payload.get("output2") or []
        if not isinstance(records, list) or not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        if "stck_bsop_date" not in df.columns:
            return pd.DataFrame()

        keep_cols = [c for c in ("stck_bsop_date", *self.OHLCV_COLUMN_MAP.keys()) if c in df.columns]
        df = df[keep_cols].copy()
        df["stck_bsop_date"] = pd.to_datetime(df["stck_bsop_date"], format="%Y%m%d", errors="coerce")
        df.dropna(subset=["stck_bsop_date"], inplace=True)
        df.set_index("stck_bsop_date", inplace=True)
        df.rename(columns=self.OHLCV_COLUMN_MAP, inplace=True)
        for col in ("시가", "고가", "저가", "종가", "거래량"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df.sort_index(inplace=True)
        return df

    def get_investor_trading_by_date(self, ticker: str, start_date: str, end_date: str, share: str = "2"):
        _ = share
        path = "/uapi/domestic-stock/v1/quotations/inquire-investor"
        tr_id = "FHKST01010900"
        params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker}
        payload = self._request_json(path, tr_id, params)
        if not payload:
            return pd.DataFrame()

        records = payload.get("output") or []
        if not isinstance(records, list) or not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        if "stck_bsop_date" not in df.columns:
            return pd.DataFrame()

        keep_cols = [c for c in ("stck_bsop_date", *self.INVESTOR_COLUMN_MAP.keys()) if c in df.columns]
        df = df[keep_cols].copy()
        df["stck_bsop_date"] = pd.to_datetime(df["stck_bsop_date"], format="%Y%m%d", errors="coerce")
        df.dropna(subset=["stck_bsop_date"], inplace=True)
        df.set_index("stck_bsop_date", inplace=True)
        df.rename(columns=self.INVESTOR_COLUMN_MAP, inplace=True)
        for col in ("개인", "외국인합계", "기관합계"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df.sort_index(inplace=True)

        start_dt = pd.to_datetime(start_date, format="%Y%m%d", errors="coerce")
        end_dt = pd.to_datetime(end_date, format="%Y%m%d", errors="coerce")
        if pd.notna(start_dt) and pd.notna(end_dt):
            df = df[(df.index >= start_dt) & (df.index <= end_dt)]
        return df

class DataCollector:
    @staticmethod
    def get_full_analysis(ticker, start_date, end_date):
        provider = os.getenv("MARKET_DATA_PROVIDER", "kis").strip().lower()
        api_client = KisApiClient() if provider == "kis" else KRXApiClient()

        # 1) 시세 (필수)
        df_p = api_client.get_ohlcv_by_date(ticker, start_date, end_date)
        if df_p.empty:
            last_error = getattr(api_client, "last_error", None)
            raise RuntimeError(
                f"{provider.upper()} OHLCV API returned no data. {KRXApiClient._format_last_error(last_error)}"
            )

        # 2) 수급 (선택 / 제공 범위 차이)
        df_i = api_client.get_investor_trading_by_date(ticker, start_date, end_date, share="2")

        # 3) 시세를 기준으로 left join하여 날짜 범위를 유지 (수급이 없으면 0)
        df_combined = df_p.copy()
        if df_i is not None and not df_i.empty:
            df_combined = df_combined.join(df_i, how="left")

        # 3. 빈 데이터(NaN) 메우기
        # 혹시 모를 빈칸은 직전 데이터로 채우고(ffill), 나머지는 0으로 채웁니다(fillna).
        # 차트(Plotly)가 'None'을 받아서 2012년으로 튀는 것을 막는 결정적 단계입니다.
        df_combined = df_combined.ffill().fillna(0)

        investor_cols = list(df_i.columns) if df_i is not None and not df_i.empty else []

        # 2. 누적 데이터 (억 원 단위)
        if investor_cols:
            df_cum = df_combined[investor_cols].cumsum()
            cum_data = {col: (df_cum[col] / 1e8).round(2).tolist() for col in investor_cols}
        else:
            cum_data = {}

        # 4. 리스트 변환 (JavaScript가 읽기 좋은 형태)
        dates = df_combined.index.strftime('%Y-%m-%d').tolist()
        prices = df_combined['종가'].astype(int).tolist()
        
        # 각 투자 주체별 데이터를 '억 원' 단위로 변환하여 리스트화
        trend_data = {col: (df_combined[col] / 1e8).round(2).tolist() for col in investor_cols}

        # 5. 마지막 영업일 요약 정보 (UI 상단 그리드용)
        last_metrics = {col: round(float(df_combined[col].iloc[-1]) / 1e8, 2) for col in investor_cols}

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
        provider = os.getenv("MARKET_DATA_PROVIDER", "kis").strip().lower()
        api_client = KisApiClient() if provider == "kis" else KRXApiClient()
        df_p = api_client.get_ohlcv_by_date(ticker, start_date, end_date)
        if df_p.empty:
            last_error = getattr(api_client, "last_error", None)
            raise RuntimeError(
                f"{provider.upper()} OHLCV API returned no data. {KRXApiClient._format_last_error(last_error)}"
            )
        df_i = api_client.get_investor_trading_by_date(
            ticker, start_date, end_date, share="1"
        )
        
        df_final = df_p.copy()
        if df_i is not None and not df_i.empty:
            df_final = df_final.join(df_i, how="left")
        df_final = df_final.ffill().fillna(0)
        
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df_final.to_excel(writer, sheet_name='Investor_Universe')
            worksheet = writer.sheets['Investor_Universe']
            for i in range(len(df_final.columns) + 1):
                worksheet.set_column(i, i, 15)
        output.seek(0)
        return output
