import io
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests


def _load_dotenv_if_present():
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)


def _truncate_text(text: str, limit: int = 300) -> str:
    if not text:
        return ""
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


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


@dataclass(frozen=True)
class KisConfig:
    env: str
    base_url: str
    app_key: str
    app_secret: str
    debug: bool
    request_delay_sec: float
    investor_detail: bool


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
    INVESTOR_COLUMN_MAP_AMOUNT = {
        "prsn_ntby_tr_pbmn": "개인",
        "frgn_ntby_tr_pbmn": "외국인합계",
        "orgn_ntby_tr_pbmn": "기관합계",
    }
    INVESTOR_COLUMN_MAP_QTY = {
        "prsn_ntby_qty": "개인",
        "frgn_ntby_qty": "외국인합계",
        "orgn_ntby_qty": "기관합계",
    }
    INVESTOR_DETAIL_MAP_AMOUNT = {
        "prsn_shnu_tr_pbmn": "개인_매수대금",
        "prsn_seln_tr_pbmn": "개인_매도대금",
        "frgn_shnu_tr_pbmn": "외국인_매수대금",
        "frgn_seln_tr_pbmn": "외국인_매도대금",
        "orgn_shnu_tr_pbmn": "기관_매수대금",
        "orgn_seln_tr_pbmn": "기관_매도대금",
    }
    INVESTOR_DETAIL_MAP_VOL = {
        "prsn_shnu_vol": "개인_매수량",
        "prsn_seln_vol": "개인_매도량",
        "frgn_shnu_vol": "외국인_매수량",
        "frgn_seln_vol": "외국인_매도량",
        "orgn_shnu_vol": "기관_매수량",
        "orgn_seln_vol": "기관_매도량",
    }
    INVESTOR_PBMN_TO_KRW_MULTIPLIER = 1_000_000  # 백만원 단위로 내려오는 값을 '원'으로 환산

    def __init__(self):
        _load_dotenv_if_present()
        env = os.getenv("KIS_ENV", "demo").strip().lower()  # demo | real
        base_url = os.getenv("KIS_BASE_URL", "").strip()
        if not base_url:
            base_url = (
                "https://openapivts.koreainvestment.com:29443"
                if env == "demo"
                else "https://openapi.koreainvestment.com:9443"
            )

        app_key = (os.getenv("KIS_APP_KEY") or "").strip()
        app_secret = (os.getenv("KIS_APP_SECRET") or "").strip()
        debug = os.getenv("KIS_API_DEBUG", "").strip().lower() in ("1", "true", "yes", "y", "on")
        request_delay_sec = float(os.getenv("KIS_REQUEST_DELAY_SEC", "0") or "0")
        investor_detail = os.getenv("KIS_INVESTOR_DETAIL", "").strip().lower() in ("1", "true", "yes", "y", "on")

        self.config = KisConfig(
            env=env,
            base_url=base_url,
            app_key=app_key,
            app_secret=app_secret,
            debug=debug,
            request_delay_sec=max(0.0, request_delay_sec),
            investor_detail=investor_detail,
        )

        self.session = requests.Session()
        self._access_token = None
        self._access_token_expire_ts = 0.0
        self.last_error = None

    def _debug(self, message: str):
        if self.config.debug:
            print(f"[KIS_API_DEBUG] {message}")

    def _ensure_token(self):
        if self._access_token and time.time() < (self._access_token_expire_ts - 30):
            return

        if not self.config.app_key or not self.config.app_secret:
            self.last_error = "Missing KIS_APP_KEY/KIS_APP_SECRET (env)."
            raise RuntimeError(self.last_error)

        url = f"{self.config.base_url}/oauth2/tokenP"
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "Neon/1.0"}

        try:
            res = self.session.post(url, json=payload, headers=headers, timeout=15)
        except requests.RequestException as exc:
            self.last_error = f"Token request failed: {exc}"
            raise RuntimeError(self.last_error) from exc

        if res.status_code != 200:
            self.last_error = (
                f"Token request non-200: status={res.status_code} body={_truncate_text(res.text)}"
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
        url = f"{self.config.base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "authorization": f"Bearer {self._access_token}",
            "appkey": self.config.app_key,
            "appsecret": self.config.app_secret,
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
                f"non-200: status={res.status_code} url={url} body={_truncate_text(res.text)}"
            )
            self._debug(self.last_error)
            return None

        try:
            data = res.json()
        except ValueError:
            self.last_error = f"Non-JSON response: url={url} body={_truncate_text(res.text)}"
            self._debug(self.last_error)
            return None

        rt_cd = data.get("rt_cd")
        if rt_cd and rt_cd != "0":
            self.last_error = f"api error: rt_cd={rt_cd} msg_cd={data.get('msg_cd')} msg1={data.get('msg1')}"
            self._debug(self.last_error)
            return None

        if self.config.request_delay_sec > 0:
            time.sleep(self.config.request_delay_sec)

        return data

    @staticmethod
    def _normalize_yyyymmdd(date_str: str) -> str:
        if not date_str:
            return ""
        date_str = date_str.strip().replace("-", "")
        return date_str

    def get_ohlcv_by_date(self, ticker: str, start_date: str, end_date: str):
        start_date = self._normalize_yyyymmdd(start_date)
        end_date = self._normalize_yyyymmdd(end_date)
        if not start_date or not end_date:
            self.last_error = "Missing start_date/end_date (expected YYYYMMDD)."
            return pd.DataFrame()

        path = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
        tr_id = "FHKST03010100"

        parts = []
        cursor_end = end_date
        max_iters = int(os.getenv("KIS_OHLCV_MAX_ITERS", "50") or "50")

        for _ in range(max_iters):
            params = {
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": ticker,
                "FID_INPUT_DATE_1": start_date,
                "FID_INPUT_DATE_2": cursor_end,
                "FID_PERIOD_DIV_CODE": "D",
                "FID_ORG_ADJ_PRC": "1",
            }
            payload = self._request_json(path, tr_id, params)
            if not payload:
                break

            records = payload.get("output2") or []
            if not isinstance(records, list) or not records:
                break

            df = pd.DataFrame(records)
            if "stck_bsop_date" not in df.columns:
                break

            keep_cols = [c for c in ("stck_bsop_date", *self.OHLCV_COLUMN_MAP.keys()) if c in df.columns]
            df = df[keep_cols].copy()
            df["stck_bsop_date"] = pd.to_datetime(df["stck_bsop_date"], format="%Y%m%d", errors="coerce")
            df.dropna(subset=["stck_bsop_date"], inplace=True)
            if df.empty:
                break

            df.set_index("stck_bsop_date", inplace=True)
            df.rename(columns=self.OHLCV_COLUMN_MAP, inplace=True)
            for col in ("시가", "고가", "저가", "종가", "거래량"):
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            df.sort_index(inplace=True)
            parts.append(df)

            earliest = df.index.min()
            if earliest is pd.NaT:
                break

            start_dt = pd.to_datetime(start_date, format="%Y%m%d", errors="coerce")
            if pd.isna(start_dt) or earliest <= start_dt:
                break

            cursor_end_dt = earliest - pd.Timedelta(days=1)
            cursor_end = cursor_end_dt.strftime("%Y%m%d")

        if not parts:
            return pd.DataFrame()

        out = pd.concat(parts, axis=0)
        out = out[~out.index.duplicated(keep="last")]
        out.sort_index(inplace=True)
        start_dt = pd.to_datetime(start_date, format="%Y%m%d", errors="coerce")
        end_dt = pd.to_datetime(end_date, format="%Y%m%d", errors="coerce")
        if pd.notna(start_dt) and pd.notna(end_dt):
            out = out[(out.index >= start_dt) & (out.index <= end_dt)]
        return out

    def get_investor_trading_by_date(self, ticker: str, start_date: str, end_date: str, share: str = "2"):
        start_date = self._normalize_yyyymmdd(start_date)
        end_date = self._normalize_yyyymmdd(end_date)

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

        is_qty = str(share) == "1"
        column_map = self.INVESTOR_COLUMN_MAP_QTY if is_qty else self.INVESTOR_COLUMN_MAP_AMOUNT
        if not any(key in df.columns for key in column_map.keys()):
            # 서버 스펙/환경에 따라 필드가 달라질 수 있어 fallback
            column_map = self.INVESTOR_COLUMN_MAP_AMOUNT

        extra_map = {}
        if not is_qty and self.config.investor_detail:
            extra_map = {**self.INVESTOR_DETAIL_MAP_AMOUNT, **self.INVESTOR_DETAIL_MAP_VOL}

        keep_cols = [c for c in ("stck_bsop_date", *column_map.keys(), *extra_map.keys()) if c in df.columns]
        df = df[keep_cols].copy()
        df["stck_bsop_date"] = pd.to_datetime(df["stck_bsop_date"], format="%Y%m%d", errors="coerce")
        df.dropna(subset=["stck_bsop_date"], inplace=True)
        df.set_index("stck_bsop_date", inplace=True)
        df.rename(columns={**column_map, **extra_map}, inplace=True)
        df = df.apply(pd.to_numeric, errors="coerce")

        if not is_qty:
            # *_tr_pbmn 계열은 '백만원' 단위로 내려와서 원(KRW)으로 환산
            money_cols = [c for c in df.columns if c.endswith("대금") or c in ("개인", "외국인합계", "기관합계")]
            if money_cols:
                df[money_cols] = df[money_cols] * self.INVESTOR_PBMN_TO_KRW_MULTIPLIER

        df.sort_index(inplace=True)

        start_dt = pd.to_datetime(start_date, format="%Y%m%d", errors="coerce")
        end_dt = pd.to_datetime(end_date, format="%Y%m%d", errors="coerce")
        if pd.notna(start_dt) and pd.notna(end_dt):
            df = df[(df.index >= start_dt) & (df.index <= end_dt)]
        return df

class DataCollector:
    @staticmethod
    def get_full_analysis(ticker, start_date, end_date):
        api_client = KisApiClient()

        # 1) 시세 (필수)
        df_p = api_client.get_ohlcv_by_date(ticker, start_date, end_date)
        if df_p.empty:
            last_error = getattr(api_client, "last_error", None)
            raise RuntimeError(
                f"KIS OHLCV API returned no data. {_format_last_error(last_error)}"
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
        api_client = KisApiClient()
        df_p = api_client.get_ohlcv_by_date(ticker, start_date, end_date)
        if df_p.empty:
            last_error = getattr(api_client, "last_error", None)
            raise RuntimeError(
                f"KIS OHLCV API returned no data. {_format_last_error(last_error)}"
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
