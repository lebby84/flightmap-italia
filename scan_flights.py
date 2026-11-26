import argparse
import csv
import io
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

# ================= CONFIGURAZIONE =================
SCANNER_VERSION = "v6-ryanair-global+airlabs"
AIRLABS_KEY = os.getenv("AIRLABS_KEY", "INCOLLA_QUI_LA_TUA_API_KEY")
AIRLABS_BASE = "https://airlabs.co/api/v9"
ITALY_TZ = ZoneInfo("Europe/Rome")

# Database gratuito pubblico con coordinate/citta di tutti gli aeroporti mondiali (0 token AirLabs!)
OURAIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

# Header standard per l'API pubblica Ryanair (0 token AirLabs!)
RYANAIR_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}

# Limite mensile prudenziale di sicurezza AirLabs
MAX_MONTHLY_CALLS = 950
MIN_RESERVE_CALLS = 15
MAX_PAGES_PER_DIRECTION = 40

# Giorno del mese in cui si azzera il contatore mensile AirLabs (1-28)
BILLING_RESET_DAY = 1

# Frequenza automatica (modalita AUTO):
# - Flotta intera Ryanair (tutti gli aeroporti): ogni 7 giorni (0 token AirLabs!)
# - Bologna (altre compagnie AirLabs): ogni 7 giorni
# - Altri 7 aeroporti italiani (altre compagnie AirLabs): ogni 30 giorni
RYANAIR_GLOBAL_INTERVAL_DAYS = 7

AIRPORT_SCHEDULE = {
    "BLQ": 7,
    "VRN": 30,
    "BGY": 30,
    "FLR": 30,
    "TSF": 30,
    "LIN": 30,
    "MXP": 30,
    "VCE": 30,
}

RYANAIR_CODES = {"FR", "MW", "RK", "LW", "RR"}

AIRPORT_AIRLINES = {
    "BLQ": [
        "FR", "MW", "RK", "LW", "RR",
        "W4", "W6", "EC", "U2",
        "AZ", "EN", "LH", "AF", "KL", "WA", "BA", "IB", "YW", "I2",
        "VY", "V7", "OS", "LX", "SN", "TP", "NI", "SK", "DY", "AY", "EI",
        "TK", "VF", "PC", "A3", "LO", "RO", "JU", "OU", "BT", "NO",
        "EW", "HV", "TO", "EK", "QR", "FZ", "MS", "SM", "AT", "3O", "TU", "KM", "LG", "XZ", "XQ"
    ],
    "VRN": [
        "FR", "MW", "RK", "LW", "EN", "LH", "V7", "NO", "LS", "BY",
        "U2", "EC", "W4", "W6", "AZ", "BA", "EI", "AF", "KL", "WA",
        "HV", "EW", "DE", "X3", "OS", "TK", "SM", "MS", "RO", "XZ"
    ],
    "BGY": [
        "FR", "MW", "RK", "LW", "RR", "W4", "W6", "EC", "U2",
        "DY", "D8", "NO", "EW", "PC", "VF", "3O", "AT", "FZ", "EY", "QR",
        "MS", "SM", "RO", "H4", "BT", "AZ", "V7", "LS", "XQ", "XC"
    ],
    "FLR": [
        "AZ", "EN", "LH", "AF", "KL", "WA", "BA", "IB", "YW", "VY",
        "V7", "LX", "2L", "OS", "SN", "TP", "SK", "A3", "LO", "RO",
        "KM", "LG", "U2", "EC", "W4", "W6", "TK", "QR"
    ],
    "TSF": [
        "FR", "MW", "RK", "LW", "RR", "W4", "W6", "U2", "EC", "V7"
    ],
    "LIN": [
        "AZ", "EC", "U2", "LH", "EN", "AF", "KL", "WA", "BA", "IB",
        "I2", "YW", "LX", "OS", "SN", "SK", "SL", "TP", "AY", "EI",
        "A3", "KM", "LG", "DX", "HV", "V3", "ZQ", "XZ"
    ],
    "MXP": [
        "EC", "U2", "FR", "MW", "RK", "LW", "W4", "W6", "W9",
        "AZ", "NO", "LH", "EN", "AF", "KL", "WA", "BA", "IB", "I2", "VY",
        "OS", "LX", "SN", "TP", "SK", "DY", "AY", "EI", "A3", "GQ",
        "LO", "QS", "UX", "EW", "4Y", "DE", "HV", "TO", "LS",
        "TK", "VF", "PC", "XQ", "EK", "QR", "EY", "FZ", "SV", "G9", "WY", "RJ",
        "MS", "SM", "AT", "3O", "TU", "BJ", "ET", "RO", "JU", "OU", "BT", "FI", "LY",
        "CA", "MU", "HU", "CX", "SQ", "TG", "KE", "JL", "NH", "BR", "VN",
        "DL", "UA", "AA", "AC", "LA", "AI", "HY", "KC", "A9", "J2"
    ],
    "VCE": [
        "FR", "MW", "RK", "LW", "RR", "EC", "U2", "W4", "W6", "V7",
        "AZ", "LH", "EN", "AF", "KL", "WA", "BA", "IB", "I2", "YW", "VY",
        "OS", "LX", "SN", "TP", "SK", "DY", "AY", "EI", "A3", "LO",
        "RO", "JU", "OU", "BT", "EW", "HV", "TO", "LS", "BY",
        "TK", "VF", "PC", "XQ", "EK", "QR", "SV", "MS", "AT", "TU",
        "DL", "UA", "AA", "AC", "TS", "KE", "CA", "NO"
    ],
}

CANDIDATE_DESTINATIONS = sorted(set([
    "BRI", "BDS", "CAG", "CTA", "PMO", "SUF", "TPS", "AHO", "OLB", "LMP", "PNL", "REG", "PSR", "TRS", "NAP", "FCO", "CIA",
    "STN", "LTN", "LGW", "LHR", "MAN", "EDI", "BHX", "BRS", "LBA", "NCL", "EMA", "LPL", "GLA", "BFS", "DUB", "ORK", "SNN",
    "MAD", "BCN", "VLC", "SVQ", "AGP", "ALC", "PMI", "IBZ", "MAH", "TFS", "FUE", "ACE", "LPA", "SCQ", "SDR", "ZAZ", "GRX", "GRO", "REU", "LIS", "OPO", "FAO", "FNC",
    "BVA", "CDG", "ORY", "MRS", "TLS", "BOD", "NTE", "LYS", "NCE", "CRL", "BRU", "EIN", "AMS", "LUX",
    "CGN", "NRN", "BER", "FMM", "NUE", "HHN", "HAM", "DUS", "FRA", "MUC", "VIE", "ZRH", "GVA", "BSL", "CPH", "BLL", "ARN", "NYO", "GOT", "OSL", "HEL",
    "WAW", "WMI", "KRK", "KTW", "GDN", "WRO", "POZ", "KUN", "VNO", "RIX", "TLL",
    "PRG", "BTS", "BUD", "OTP", "BBU", "CLJ", "IAS", "TSR", "SCV", "CRA", "SBZ", "SOF", "VAR", "TIA", "ZAD", "SPU", "DBV", "PUY", "ZAG", "BEG", "SKP",
    "ATH", "SKG", "CFU", "RHO", "HER", "CHQ", "JTR", "JMK", "KGS", "ZTH", "EFL", "PVK", "KLX", "PFO", "LCA", "MLA",
    "IST", "SAW", "ADB", "AYT", "AMM", "TLV", "DXB", "AUH", "DOH", "RAK", "FEZ", "TNG", "AGA", "CMN", "TUN", "CAI", "SSH", "RMF", "HRG"
]))

BASE_AIRPORTS = {
    "BLQ": {"iata": "BLQ", "name": "Bologna Guglielmo Marconi", "city": "Bologna", "country": "IT", "lat": 44.5354, "lon": 11.2887, "is_base": True},
    "VRN": {"iata": "VRN", "name": "Verona Villafranca", "city": "Verona", "country": "IT", "lat": 45.3957, "lon": 10.8885, "is_base": True},
    "BGY": {"iata": "BGY", "name": "Milano Bergamo", "city": "Bergamo", "country": "IT", "lat": 45.6739, "lon": 9.7042, "is_base": True},
    "FLR": {"iata": "FLR", "name": "Firenze Peretola", "city": "Firenze", "country": "IT", "lat": 43.8100, "lon": 11.2051, "is_base": True},
    "TSF": {"iata": "TSF", "name": "Treviso Canova", "city": "Treviso", "country": "IT", "lat": 45.6484, "lon": 12.1944, "is_base": True},
    "LIN": {"iata": "LIN", "name": "Milano Linate", "city": "Milano", "country": "IT", "lat": 45.4451, "lon": 9.2767, "is_base": True},
    "MXP": {"iata": "MXP", "name": "Milano Malpensa", "city": "Milano", "country": "IT", "lat": 45.6306, "lon": 8.7281, "is_base": True},
    "VCE": {"iata": "VCE", "name": "Venezia Marco Polo", "city": "Venezia", "country": "IT", "lat": 45.5053, "lon": 12.3519, "is_base": True},
}

CITY_OVERRIDES = {
    "CDG": "Parigi (Charles de Gaulle)", "ORY": "Parigi (Orly)", "BVA": "Parigi (Beauvais)",
    "LHR": "Londra (Heathrow)", "STN": "Londra (Stansted)", "LTN": "Londra (Luton)", "LGW": "Londra (Gatwick)", "LCY": "Londra (City)", "SEN": "Londra (Southend)",
    "BRU": "Bruxelles (Zaventem)", "CRL": "Bruxelles (Charleroi)",
    "ARN": "Stoccolma (Arlanda)", "NYO": "Stoccolma (Skavsta)", "VST": "Stoccolma (Västerås)",
    "WAW": "Varsavia (Chopin)", "WMI": "Varsavia (Modlin)",
    "FRA": "Francoforte", "HHN": "Francoforte (Hahn)",
    "MUC": "Monaco di Baviera", "FMM": "Monaco (Memmingen)",
    "DUS": "Düsseldorf", "NRN": "Düsseldorf (Weeze)",
    "OSL": "Oslo (Gardermoen)", "TRF": "Oslo (Torp)",
    "DUB": "Dublino", "EDI": "Edimburgo", "GLA": "Glasgow", "PIK": "Glasgow (Prestwick)",
    "KRK": "Cracovia", "PRG": "Praga", "VIE": "Vienna", "LIS": "Lisbona", "OPO": "Porto",
    "ATH": "Atene", "BCN": "Barcellona", "GRO": "Barcellona (Girona)", "REU": "Barcellona (Reus)",
    "BER": "Berlino", "ZRH": "Zurigo", "CPH": "Copenaghen",
    "OTP": "Bucarest (Otopeni)", "BBU": "Bucarest (Băneasa)", "MLA": "Malta",
    "FCO": "Roma (Fiumicino)", "CIA": "Roma (Ciampino)", "NAP": "Napoli",
    "PMO": "Palermo", "CTA": "Catania", "CAG": "Cagliari", "BRI": "Bari", "BDS": "Brindisi",
    "AHO": "Alghero", "OLB": "Olbia", "SUF": "Lamezia Terme", "TPS": "Trapani",
    "IST": "Istanbul", "SAW": "Istanbul (Sabiha Gökçen)",
    "PMI": "Palma di Maiorca", "SVQ": "Siviglia", "VLC": "Valencia", "AGP": "Malaga", "ALC": "Alicante",
    "ACE": "Lanzarote", "TFS": "Tenerife Sud", "TFN": "Tenerife Nord", "FUE": "Fuerteventura", "LPA": "Gran Canaria",
    "CGN": "Colonia", "MRS": "Marsiglia", "TLS": "Tolosa", "LYS": "Lione", "NCE": "Nizza", "BOD": "Bordeaux",
    "BEG": "Belgrado", "TIA": "Tirana", "WRO": "Breslavia", "GDN": "Danzica", "POZ": "Poznań", "KTW": "Katowice",
    "ZAD": "Zara", "SPU": "Spalato", "DBV": "Dubrovnik", "ZAG": "Zagabria",
    "SKG": "Salonicco", "RHO": "Rodi", "CFU": "Corfù", "HER": "Heraklion (Creta)", "CHQ": "Chania (Creta)", "JTR": "Santorini",
    "RAK": "Marrakech", "FEZ": "Fès", "TNG": "Tangeri", "CMN": "Casablanca", "TUN": "Tunisi",
}

DEFAULT_AIRLINES = {
    "FR": "Ryanair", "MW": "Ryanair", "RK": "Ryanair", "LW": "Ryanair", "RR": "Ryanair",
    "U2": "easyJet", "EC": "easyJet", "DS": "easyJet",
    "W6": "Wizz Air", "W4": "Wizz Air Malta", "W9": "Wizz Air UK",
    "AZ": "ITA Airways", "LH": "Lufthansa", "EN": "Air Dolomiti", "CL": "Lufthansa CityLine",
    "AF": "Air France", "A5": "HOP!", "KL": "KLM", "WA": "KLM Cityhopper",
    "BA": "British Airways", "IB": "Iberia", "I2": "Iberia Express", "YW": "Air Nostrum",
    "VY": "Vueling", "V7": "Volotea", "OS": "Austrian Airlines", "LX": "SWISS",
    "2L": "Helvetic Airways", "SN": "Brussels Airlines", "TP": "TAP Air Portugal", "NI": "TAP Express",
    "SK": "SAS", "SL": "SAS Connect", "DY": "Norwegian", "D8": "Norwegian Air Sweden",
    "AY": "Finnair", "EI": "Aer Lingus", "TK": "Turkish Airlines", "VF": "AJet",
    "PC": "Pegasus Airlines", "A3": "Aegean Airlines", "GQ": "Sky Express",
    "LO": "LOT Polish Airlines", "OK": "Czech Airlines", "QS": "Smartwings",
    "UX": "Air Europa", "NO": "Neos", "EW": "Eurowings", "4Y": "Discover Airlines",
    "DE": "Condor", "X3": "TUI fly", "HV": "Transavia", "TO": "Transavia France",
    "LS": "Jet2.com", "BY": "TUI Airways", "EK": "Emirates", "QR": "Qatar Airways",
    "EY": "Etihad Airways", "FZ": "flydubai", "MS": "EgyptAir", "SM": "Air Cairo",
    "AT": "Royal Air Maroc", "3O": "Air Arabia Maroc", "TU": "Tunisair", "BJ": "Nouvelair",
    "RO": "TAROM", "H4": "HiSky", "JU": "Air Serbia", "OU": "Croatia Airlines",
    "BT": "airBaltic", "LG": "Luxair", "KM": "KM Malta Airlines", "CY": "Cyprus Airways",
    "FB": "Bulgaria Air", "FI": "Icelandair", "OG": "PLAY", "LY": "El Al",
    "RJ": "Royal Jordanian", "SV": "Saudia", "G9": "Air Arabia", "WY": "Oman Air",
    "CA": "Air China", "MU": "China Eastern", "HU": "Hainan Airlines", "CX": "Cathay Pacific",
    "SQ": "Singapore Airlines", "TG": "Thai Airways", "KE": "Korean Air",
    "JL": "Japan Airlines", "NH": "ANA", "BR": "EVA Air", "VN": "Vietnam Airlines",
    "DL": "Delta Air Lines", "UA": "United Airlines", "AA": "American Airlines",
    "AC": "Air Canada", "TS": "Air Transat", "LA": "LATAM Airlines", "ET": "Ethiopian Airlines",
    "5F": "FlyOne", "XQ": "SunExpress", "XC": "Corendon Airlines", "XZ": "AeroItalia",
    "DX": "DAT", "V3": "Carpatair", "ZQ": "German Airways", "A9": "Georgian Airways",
    "J2": "Azerbaijan Airlines", "HY": "Uzbekistan Airways", "KC": "Air Astana", "AI": "Air India",
}

DAY_MAP = {
    "mon": 1, "monday": 1, "1": 1,
    "tue": 2, "tuesday": 2, "2": 2,
    "wed": 3, "wednesday": 3, "3": 3,
    "thu": 4, "thursday": 4, "4": 4,
    "fri": 5, "friday": 5, "5": 5,
    "sat": 6, "saturday": 6, "6": 6,
    "sun": 7, "sunday": 7, "7": 7,
}

STATE_FILE = "quota_state.json"
ROUTES_FILE = "routes.json"
# ==================================================


def current_billing_cycle(now: datetime) -> str:
    if now.day >= BILLING_RESET_DAY:
        return now.strftime("%Y-%m")
    prev_month = now.replace(day=1) - timedelta(days=1)
    return prev_month.strftime("%Y-%m")


def load_json(path: str, default: dict) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def save_json(path: str, data: dict, compact: bool = False) -> None:
    with open(path, "w", encoding="utf-8") as f:
        if compact:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(data, f, ensure_ascii=False, indent=2)


def load_state(now: datetime) -> dict:
    cycle = current_billing_cycle(now)
    state = load_json(STATE_FILE, {
        "cycle": cycle,
        "units_used": 0,
        "units_limit": MAX_MONTHLY_CALLS,
        "remote_remaining": None,
        "blocked": False,
        "blocked_reason": None,
        "last_scan": {},
        "airlines_cache": dict(DEFAULT_AIRLINES),
    })
    if state.get("cycle") != cycle:
        print(f"[QUOTA] Nuovo ciclo mensile ({cycle}): azzero contatore chiamate.")
        state["cycle"] = cycle
        state["units_used"] = 0
        state["remote_remaining"] = None
        state["blocked"] = False
        state["blocked_reason"] = None
    state.setdefault("units_limit", MAX_MONTHLY_CALLS)
    state.setdefault("remote_remaining", None)
    cached = {k: v for k, v in state.get("airlines_cache", {}).items() if v and v != k}
    state["airlines_cache"] = {**cached, **DEFAULT_AIRLINES}
    return state


def days_since(iso_str: str, now: datetime) -> int:
    if not iso_str:
        return 9999
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ITALY_TZ)
        return (now - dt).days
    except ValueError:
        return 9999


def airlabs_get(endpoint: str, params: dict, state: dict):
    """Esegue una chiamata GET ad AirLabs con blocco preventivo e controllo quota reale."""
    rem = state.get("remote_remaining")
    if isinstance(rem, int) and rem <= MIN_RESERVE_CALLS:
        state["blocked"] = True
        state["blocked_reason"] = (
            f"Soglia di riserva AirLabs raggiunta ({rem} chiamate residue). "
            "Blocco attivo: riproverò automaticamente appena torna disponibile quota gratuita."
        )
        return None, "QUOTA_EXCEEDED"

    if rem is None and state["units_used"] + 1 > MAX_MONTHLY_CALLS:
        state["blocked"] = True
        state["blocked_reason"] = (
            f"Soglia locale raggiunta ({state['units_used']}/{MAX_MONTHLY_CALLS} chiamate). "
            "Blocco attivo: riproverò automaticamente alla prossima scansione."
        )
        return None, "QUOTA_EXCEEDED"

    query = {"api_key": AIRLABS_KEY, **params}
    url = f"{AIRLABS_BASE}/{endpoint}"

    try:
        resp = requests.get(url, params=query, timeout=30)
    except requests.RequestException as exc:
        print(f"[ERRORE RETE] {endpoint}: {exc}")
        return None, "NETWORK_ERROR"

    if resp.status_code == 429:
        state["blocked"] = True
        state["blocked_reason"] = "AirLabs ha restituito HTTP 429 (quota esaurita). Retry alla prossima esecuzione."
        return None, "QUOTA_EXCEEDED"

    if resp.status_code != 200:
        print(f"[ERRORE HTTP {resp.status_code}] {endpoint}: {resp.text[:200]}")
        return None, "HTTP_ERROR"

    payload = resp.json()

    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        err_code = str(err.get("code", "")).lower()
        err_msg = err.get("message", "Errore sconosciuto AirLabs")
        if any(k in err_code or k in err_msg.lower() for k in ("limit", "quota", "exceeded", "expired", "credit")):
            state["blocked"] = True
            state["blocked_reason"] = f"Quota AirLabs esaurita ({err_msg}). Retry alla prossima esecuzione."
            return None, "QUOTA_EXCEEDED"
        print(f"[ERRORE API AIRLABS] {err_code}: {err_msg}")
        return None, "API_ERROR"

    state["units_used"] += 1

    req_info = payload.get("request") or {}
    key_info = req_info.get("key") or {}
    monthly_limit = key_info.get("limits_by_month")
    remaining_calls = key_info.get("limits_total")

    if isinstance(monthly_limit, int) and monthly_limit > 0:
        state["units_limit"] = monthly_limit
    if isinstance(remaining_calls, int):
        state["remote_remaining"] = remaining_calls
        if isinstance(monthly_limit, int) and monthly_limit >= remaining_calls:
            state["units_used"] = monthly_limit - remaining_calls
        if remaining_calls <= MIN_RESERVE_CALLS:
            state["blocked"] = True
            state["blocked_reason"] = f"Chiamate residue AirLabs sotto la soglia di riserva ({remaining_calls} rimaste)."

    return payload.get("response", []), "OK"


# ==================== RYANAIR PUBLIC API (0 TOKEN AIRLABS) ====================
_thread_local = threading.local()


def get_thread_session() -> requests.Session:
    if not hasattr(_thread_local, "session"):
        s = requests.Session()
        s.headers.update(RYANAIR_HEADERS)
        _thread_local.session = s
    return _thread_local.session


def ryanair_get_json(urls: list, session: requests.Session = None):
    sess = session or get_thread_session()
    for url in urls:
        try:
            resp = sess.get(url, timeout=20)
            if resp.status_code == 200:
                return resp.json(), 200
            if resp.status_code in (429, 403):
                return None, resp.status_code
        except requests.RequestException:
            continue
    return None, 0


def target_months_for_schedule(now: datetime, full_two_months: bool = True) -> list:
    next_m = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    if full_two_months:
        return [(now.year, now.month), next_m]
    # Per scansione globale: 1 mese completo (il mese prossimo se siamo oltre il 10, altrimenti il mese corrente)
    return [next_m] if now.day > 10 else [(now.year, now.month)]


def fetch_ryanair_schedule(orig: str, dest: str, now: datetime, session: requests.Session = None, full_two_months: bool = True):
    """Recupera giorni della settimana (1..7) e TUTTI gli orari di partenza da Ryanair per una tratta."""
    days_set = set()
    times_set = set()
    rate_limited = False

    for y, m in target_months_for_schedule(now, full_two_months=full_two_months):
        data, code = ryanair_get_json([
            f"https://www.ryanair.com/api/timtbl/3/schedules/{orig}/{dest}/years/{y}/months/{m}",
            f"https://services-api.ryanair.com/timtbl/3/schedules/{orig}/{dest}/years/{y}/months/{m}",
        ], session)
        if code in (429, 403):
            rate_limited = True
            break
        if isinstance(data, dict) and isinstance(data.get("days"), list):
            for d_obj in data["days"]:
                day_num = d_obj.get("day")
                flights = d_obj.get("flights") or []
                if not day_num or not flights:
                    continue
                try:
                    dt = datetime(y, m, int(day_num))
                    days_set.add(dt.isoweekday())
                except ValueError:
                    continue
                for fl in flights:
                    t = (fl.get("departureTime") or "")[:5]
                    if t and len(times_set) < 24:
                        times_set.add(t)

    # Fallback availabilities solo se non siamo rate-limited e non abbiamo ancora trovato giorni
    if not days_set and not rate_limited and full_two_months:
        avail, code = ryanair_get_json([
            f"https://www.ryanair.com/api/farfnd/3/oneWayFares/{orig}/{dest}/availabilities",
            f"https://services-api.ryanair.com/farfnd/3/oneWayFares/{orig}/{dest}/availabilities",
        ], session)
        if code in (429, 403):
            rate_limited = True
        elif isinstance(avail, list):
            horizon = now.date() + timedelta(days=45)
            today = now.date()
            for ds in avail:
                try:
                    d = datetime.strptime(str(ds)[:10], "%Y-%m-%d").date()
                    if today <= d <= horizon:
                        days_set.add(d.isoweekday())
                except ValueError:
                    continue

    return days_set, times_set, rate_limited


def upsert_ryanair_airport(ap_obj: dict, airports_db: dict):
    code = (ap_obj.get("code") or "").strip().upper()
    if not code or code in BASE_AIRPORTS:
        return code
    coords = ap_obj.get("coordinates") or {}
    lat = coords.get("latitude")
    lon = coords.get("longitude")
    if lat is not None and lon is not None:
        city_obj = ap_obj.get("city") or {}
        country_obj = ap_obj.get("country") or {}
        ap_name = (ap_obj.get("name") or code).strip()
        ap_city = CITY_OVERRIDES.get(code) or (city_obj.get("name") or ap_name).strip()
        airports_db[code] = {
            "iata": code,
            "name": ap_name,
            "city": ap_city,
            "country": (country_obj.get("code") or "").strip().upper(),
            "lat": float(lat),
            "lon": float(lon),
            "is_base": False,
        }
    return code


def fetch_ryanair_routes_for_airport(iata: str, now: datetime, temp_routes: dict, airports_db: dict, discovered_airports: set) -> bool:
    """Scarica tutte le rotte dirette Ryanair per 1 singolo aeroporto base (0 token AirLabs)."""
    session = get_thread_session()
    data, _ = ryanair_get_json([
        f"https://www.ryanair.com/api/views/locate/searchWidget/routes/it/airport/{iata}",
        f"https://services-api.ryanair.com/views/locate/searchWidget/routes/it/airport/{iata}",
        f"https://www.ryanair.com/api/views/locate/searchWidget/routes/en/airport/{iata}",
    ], session)

    if not isinstance(data, list) or not data:
        print(f"  [RYANAIR] Nessuna rotta o API pubblica non raggiungibile per {iata}.")
        return False

    direct_dests = []
    for item in data:
        if not isinstance(item, dict) or item.get("connectingAirport"):
            continue
        arr = item.get("arrivalAirport") or {}
        dest = upsert_ryanair_airport(arr, airports_db)
        if not dest or dest == iata:
            continue
        direct_dests.append(dest)
        discovered_airports.add(dest)

    direct_dests = sorted(set(direct_dests))
    if not direct_dests:
        return False

    print(f"  [RYANAIR] Trovate {len(direct_dests)} destinazioni dirette per {iata} (0 token AirLabs). Scarico orari...")
    added_out = 0
    added_in = 0
    for dest in direct_dests:
        out_days, out_times, _ = fetch_ryanair_schedule(iata, dest, now, session, full_two_months=True)
        if out_days:
            entry = temp_routes.setdefault((iata, dest), {}).setdefault(
                "Ryanair",
                {"name": "Ryanair", "iata": "FR", "days": set(), "sample_times": set()},
            )
            entry["days"].update(out_days)
            entry["sample_times"].update(out_times)
            added_out += 1

        in_days, in_times, _ = fetch_ryanair_schedule(dest, iata, now, session, full_two_months=True)
        if in_days:
            entry = temp_routes.setdefault((dest, iata), {}).setdefault(
                "Ryanair",
                {"name": "Ryanair", "iata": "FR", "days": set(), "sample_times": set()},
            )
            entry["days"].update(in_days)
            entry["sample_times"].update(in_times)
            added_in += 1

        time.sleep(0.04)

    print(f"  [RYANAIR OK] {iata}: caricate {added_out} tratte in partenza e {added_in} in arrivo.")
    return added_out > 0


def sync_global_ryanair_fleet(now: datetime, routes_index: dict, airports_db: dict, discovered_airports: set) -> bool:
    """Sincronizza TUTTA la flotta Ryanair su tutti gli aeroporti europei/mediterranei (0 token AirLabs!)."""
    t0 = time.time()
    print("[RYANAIR GLOBAL] Avvio scansione completa flotta Ryanair (0 token AirLabs)...")

    # 1) Scarica lista completa di tutti gli aeroporti attivi Ryanair (~235 aeroporti in 1 chiamata)
    active_airports, code = ryanair_get_json([
        "https://www.ryanair.com/api/views/locate/5/airports/it/active",
        "https://services-api.ryanair.com/views/locate/5/airports/it/active",
        "https://www.ryanair.com/api/views/locate/5/airports/en/active",
        "https://www.ryanair.com/api/views/locate/3/airports/it/active",
    ])

    if not isinstance(active_airports, list) or not active_airports:
        print(f"[RYANAIR GLOBAL] Impossibile scaricare l'elenco aeroporti attivi (HTTP {code}).")
        return False

    ryanair_iata_list = []
    for ap in active_airports:
        if not isinstance(ap, dict):
            continue
        c = upsert_ryanair_airport(ap, airports_db)
        if c:
            ryanair_iata_list.append(c)
            discovered_airports.add(c)

    ryanair_iata_list = sorted(set(ryanair_iata_list))
    print(f"[RYANAIR GLOBAL] Trovati {len(ryanair_iata_list)} aeroporti attivi Ryanair. Scarico la rete delle rotte...")

    # 2) Scarica le rotte dirette per ciascuno dei ~235 aeroporti in parallelo
    directed_pairs = set()

    def fetch_ap_routes(orig_code):
        sess = get_thread_session()
        rows, _ = ryanair_get_json([
            f"https://www.ryanair.com/api/views/locate/searchWidget/routes/it/airport/{orig_code}",
            f"https://services-api.ryanair.com/views/locate/searchWidget/routes/it/airport/{orig_code}",
        ], sess)
        found = []
        if isinstance(rows, list):
            for item in rows:
                if not isinstance(item, dict) or item.get("connectingAirport"):
                    continue
                arr = item.get("arrivalAirport") or {}
                dest = (arr.get("code") or "").strip().upper()
                if dest and dest != orig_code:
                    found.append((orig_code, dest, arr))
        return found

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_ap_routes, c) for c in ryanair_iata_list]
        for fut in as_completed(futures):
            try:
                for orig, dest, arr_obj in fut.result():
                    directed_pairs.add((orig, dest))
                    discovered_airports.add(dest)
                    if dest not in airports_db:
                        upsert_ryanair_airport(arr_obj, airports_db)
            except Exception:
                continue

    # Prioritizza le tratte che toccano i tuoi 8 aeroporti base cosi vengono sempre completate per prime
    ordered_pairs = sorted(
        directed_pairs,
        key=lambda p: (0 if (p[0] in BASE_AIRPORTS or p[1] in BASE_AIRPORTS) else 1, p[0], p[1])
    )
    print(f"[RYANAIR GLOBAL] Scoperte {len(ordered_pairs)} tratte dirette totali in {time.time() - t0:.1f}s. Scarico giorni e orari...")

    # 3) Scarica giorni e orari con parallelismo moderato e protezione anti-timeout/rate-limit
    fresh_ryanair = {}  # (orig, dest) -> {"name": "Ryanair", "iata": "FR", "days": [...], "sample_times": [...]}
    stop_event = threading.Event()
    rate_limit_hits = 0
    rl_lock = threading.Lock()
    max_seconds = 1100  # Budget massimo ~18 minuti (ampiamente entro i limiti GitHub Actions)

    def fetch_pair_sched(pair):
        nonlocal rate_limit_hits
        if stop_event.is_set() or (time.time() - t0) > max_seconds:
            return pair, None, None, False
        orig, dest = pair
        is_base_pair = (orig in BASE_AIRPORTS or dest in BASE_AIRPORTS)
        days_s, times_s, rl = fetch_ryanair_schedule(orig, dest, now, full_two_months=is_base_pair)
        if rl:
            with rl_lock:
                rate_limit_hits += 1
                if rate_limit_hits >= 15:
                    stop_event.set()
            time.sleep(0.5)
        return pair, days_s, times_s, rl

    completed_count = 0
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(fetch_pair_sched, p) for p in ordered_pairs]
        for fut in as_completed(futures):
            try:
                pair, days_s, times_s, _ = fut.result()
                completed_count += 1
                if days_s:
                    fresh_ryanair[pair] = {
                        "name": "Ryanair",
                        "iata": "FR",
                        "days": sorted(days_s),
                        "sample_times": sorted(times_s),
                    }
                if completed_count % 500 == 0:
                    print(f"  [RYANAIR GLOBAL] Progresso: {completed_count}/{len(ordered_pairs)} tratte controllate ({len(fresh_ryanair)} attive con orari)...")
            except Exception:
                continue

    complete_run = (not stop_event.is_set()) and ((time.time() - t0) <= max_seconds) and (len(fresh_ryanair) > 100)
    print(f"[RYANAIR GLOBAL] Scaricate {len(fresh_ryanair)} tratte Ryanair attive in {time.time() - t0:.1f}s (completo={complete_run}).")

    # 4) Merge sicuro dentro routes_index: aggiorna SOLO "Ryanair", lasciando intatte tutte le altre compagnie!
    if complete_run:
        # Rimuove le vecchie voci Ryanair non piu attive, preservando tutte le altre compagnie
        for pair in list(routes_index.keys()):
            if pair not in fresh_ryanair:
                others = [a for a in routes_index[pair]["airlines"] if a.get("name") != "Ryanair"]
                if others:
                    routes_index[pair]["airlines"] = others
                else:
                    del routes_index[pair]

    for pair, ryan_entry in fresh_ryanair.items():
        orig, dest = pair
        if pair in routes_index:
            others = [a for a in routes_index[pair]["airlines"] if a.get("name") != "Ryanair"]
            others.append(ryan_entry)
            others.sort(key=lambda x: x["name"])
            routes_index[pair]["airlines"] = others
        else:
            routes_index[pair] = {
                "from": orig,
                "to": dest,
                "airlines": [ryan_entry],
            }

    return len(fresh_ryanair) > 0
# ==============================================================================


def parse_days(raw_days) -> list:
    if not raw_days:
        return [1, 2, 3, 4, 5, 6, 7]
    if isinstance(raw_days, str):
        tokens = [t.strip().lower() for t in raw_days.replace(";", ",").split(",") if t.strip()]
    elif isinstance(raw_days, list):
        tokens = [str(t).strip().lower() for t in raw_days if str(t).strip()]
    else:
        return [1, 2, 3, 4, 5, 6, 7]
    days = sorted({DAY_MAP[t] for t in tokens if t in DAY_MAP})
    return days if days else [1, 2, 3, 4, 5, 6, 7]


def resolve_airline_name(iata_code: str, state: dict) -> str:
    if not iata_code:
        return "Compagnia sconosciuta"
    code = iata_code.upper()
    if code in DEFAULT_AIRLINES:
        return DEFAULT_AIRLINES[code]
    if code in state["airlines_cache"]:
        return state["airlines_cache"][code]

    data, status = airlabs_get("airlines", {"iata_code": code}, state)
    if status == "OK" and isinstance(data, list) and data:
        name = data[0].get("name") or code
        state["airlines_cache"][code] = name
        return name

    state["airlines_cache"][code] = code
    return code


def apply_city_overrides(airports_db: dict):
    for code, nice_city in CITY_OVERRIDES.items():
        if code in airports_db and not airports_db[code].get("is_base"):
            airports_db[code]["city"] = nice_city


def enrich_missing_airports(needed_codes: set, airports_db: dict, state: dict, allow_airlabs_fallback: bool = True):
    """Risolve coordinate e nomi citta degli aeroporti esteri GRATIS da OurAirports CSV (0 token AirLabs)."""
    to_resolve = sorted(
        c for c in needed_codes
        if c and c not in BASE_AIRPORTS and (
            c not in airports_db
            or airports_db[c].get("lat") is None
            or airports_db[c].get("city") == airports_db[c].get("name")
        )
    )
    if to_resolve:
        print(f"[AIRPORTS] Aggiorno coordinate/città per {len(to_resolve)} aeroporti tramite OurAirports (0 token AirLabs)...")
        try:
            resp = requests.get(OURAIRPORTS_CSV_URL, timeout=45)
            if resp.status_code == 200:
                target_set = set(to_resolve)
                reader = csv.DictReader(io.StringIO(resp.text))
                resolved = 0
                for row in reader:
                    code = (row.get("iata_code") or "").strip().upper()
                    if code in target_set:
                        lat_s = (row.get("latitude_deg") or "").strip()
                        lon_s = (row.get("longitude_deg") or "").strip()
                        if lat_s and lon_s:
                            ap_name = (row.get("name") or code).strip()
                            ap_city = CITY_OVERRIDES.get(code) or (row.get("municipality") or ap_name).strip()
                            airports_db[code] = {
                                "iata": code,
                                "name": ap_name,
                                "city": ap_city,
                                "country": (row.get("iso_country") or "").strip().upper(),
                                "lat": float(lat_s),
                                "lon": float(lon_s),
                                "is_base": False,
                            }
                            resolved += 1
                print(f"[AIRPORTS] Risolti {resolved}/{len(to_resolve)} aeroporti gratuitamente via OurAirports.")
        except requests.RequestException as exc:
            print(f"[AIRPORTS] Errore rete OurAirports ({exc}).")

    if allow_airlabs_fallback:
        still_missing = sorted(c for c in needed_codes if c and (c not in airports_db or airports_db[c].get("lat") is None))
        for code in still_missing:
            data, status = airlabs_get("airports", {"iata_code": code}, state)
            if status == "QUOTA_EXCEEDED":
                break
            if status == "OK" and isinstance(data, list) and data:
                ap = data[0]
                lat = ap.get("lat")
                lon = ap.get("lng") if ap.get("lng") is not None else ap.get("lon")
                if lat is not None and lon is not None:
                    airports_db[code] = {
                        "iata": code,
                        "name": ap.get("name") or code,
                        "city": CITY_OVERRIDES.get(code) or ap.get("city") or ap.get("name") or code,
                        "country": ap.get("country_code") or "",
                        "lat": float(lat),
                        "lon": float(lon),
                        "is_base": False,
                    }
            time.sleep(0.2)

    apply_city_overrides(airports_db)


def row_signature(row: dict) -> tuple:
    return (
        (row.get("dep_iata") or "").upper(),
        (row.get("arr_iata") or "").upper(),
        (row.get("airline_iata") or "").upper(),
        (row.get("cs_airline_iata") or "").upper(),
        (row.get("dep_time") or "")[:5],
        str(row.get("days") or ""),
    )


def ingest_rows(rows: list, temp_routes: dict, fallback_cs_routes: dict, discovered_airports: set, state: dict, skip_ryanair: bool = False):
    for row in rows:
        orig = (row.get("dep_iata") or "").upper()
        dest = (row.get("arr_iata") or "").upper()
        if not orig or not dest or orig == dest:
            continue

        is_codeshare = bool(row.get("cs_airline_iata"))
        al_iata = (row.get("cs_airline_iata") if is_codeshare else row.get("airline_iata") or "").upper()
        if skip_ryanair and al_iata in RYANAIR_CODES:
            continue

        discovered_airports.add(orig)
        discovered_airports.add(dest)

        al_name = resolve_airline_name(al_iata, state)
        days = parse_days(row.get("days"))
        dep_time = (row.get("dep_time") or "")[:5]

        target_map = fallback_cs_routes if is_codeshare else temp_routes
        entry = target_map.setdefault((orig, dest), {}).setdefault(
            al_name,
            {"name": al_name, "iata": al_iata, "days": set(), "sample_times": set()},
        )
        entry["days"].update(days)
        if dep_time and len(entry["sample_times"]) < 24:
            entry["sample_times"].add(dep_time)


def try_paginated_direction(direction_param: dict, label: str, state: dict, temp_routes: dict, fallback_cs_routes: dict, discovered_airports: set, skip_ryanair: bool):
    seen_sigs = set()
    discovered_carriers = []
    calls = 0
    raw_rows = 0

    for page in range(MAX_PAGES_PER_DIRECTION):
        offset = page * 50
        params = {
            **direction_param,
            "limit": 50,
            "offset": offset,
            "_fields": "airline_iata,cs_airline_iata,dep_iata,arr_iata,dep_time,days",
        }
        rows, status = airlabs_get("routes", params, state)
        if status == "QUOTA_EXCEEDED":
            return False, calls, raw_rows, discovered_carriers, "QUOTA_EXCEEDED"
        if status != "OK" or not isinstance(rows, list):
            return False, calls, raw_rows, discovered_carriers, status

        calls += 1
        if not rows:
            if page == 1 and len(seen_sigs) >= 50:
                return False, calls, raw_rows, discovered_carriers, "NO_PAGINATION"
            return True, calls, raw_rows, discovered_carriers, "OK"

        new_sigs = [row_signature(r) for r in rows if row_signature(r) not in seen_sigs]
        if page > 0 and not new_sigs:
            return False, calls, raw_rows, discovered_carriers, "NO_PAGINATION"

        seen_sigs.update(new_sigs)
        raw_rows += len(rows)
        ingest_rows(rows, temp_routes, fallback_cs_routes, discovered_airports, state, skip_ryanair=skip_ryanair)
        for r in rows:
            for k in ("airline_iata", "cs_airline_iata"):
                c = (r.get(k) or "").upper()
                if c and c not in discovered_carriers:
                    discovered_carriers.append(c)

        if len(rows) < 50:
            return True, calls, raw_rows, discovered_carriers, "OK"
        time.sleep(0.16)

    return True, calls, raw_rows, discovered_carriers, "OK"


def scan_airport_routes(iata: str, now: datetime, state: dict, routes_index: dict, airports_db: dict, discovered_airports: set, ryanair_already_synced: bool = False):
    """Aggiorna le compagnie AirLabs + Ryanair (se non gia appena sincronizzato globalmente) per un aeroporto base."""
    temp_routes = {}
    fallback_cs_routes = {}
    calls_made = 0

    if ryanair_already_synced:
        # Preserva i voli Ryanair gia freschi appena scaricati dal sync globale
        for pair, r_obj in routes_index.items():
            if pair[0] == iata or pair[1] == iata:
                for al in r_obj.get("airlines", []):
                    if al.get("name") == "Ryanair":
                        temp_routes.setdefault(pair, {})["Ryanair"] = {
                            "name": "Ryanair",
                            "iata": al.get("iata", "FR"),
                            "days": set(al.get("days", [])),
                            "sample_times": set(al.get("sample_times", [])),
                        }
        ryanair_direct_ok = True
    else:
        ryanair_direct_ok = fetch_ryanair_routes_for_airport(iata, now, temp_routes, airports_db, discovered_airports)

    dep_ok, c1, _, carriers1, st1 = try_paginated_direction(
        {"dep_iata": iata}, f"{iata} partenze", state, temp_routes, fallback_cs_routes, discovered_airports, skip_ryanair=ryanair_direct_ok
    )
    calls_made += c1
    if st1 == "QUOTA_EXCEEDED":
        return "QUOTA_EXCEEDED"

    arr_ok, c2, _, carriers2, st2 = try_paginated_direction(
        {"arr_iata": iata}, f"{iata} arrivi", state, temp_routes, fallback_cs_routes, discovered_airports, skip_ryanair=ryanair_direct_ok
    )
    calls_made += c2
    if st2 == "QUOTA_EXCEEDED":
        return "QUOTA_EXCEEDED"

    if not (dep_ok and arr_ok):
        discovered_carriers = list(AIRPORT_AIRLINES.get(iata, []))
        seen_carriers = set(discovered_carriers)
        for c in carriers1 + carriers2:
            if c not in seen_carriers:
                seen_carriers.add(c)
                discovered_carriers.append(c)

        if ryanair_direct_ok:
            discovered_carriers = [c for c in discovered_carriers if c not in RYANAIR_CODES]

        active_carriers = []
        capped_cutoffs = []

        for carrier in discovered_carriers:
            rows, status = airlabs_get(
                "routes",
                {"dep_iata": iata, "airline_iata": carrier, "_fields": "airline_iata,cs_airline_iata,dep_iata,arr_iata,dep_time,days"},
                state,
            )
            if status == "QUOTA_EXCEEDED":
                return "QUOTA_EXCEEDED"
            if status == "OK" and isinstance(rows, list):
                calls_made += 1
                if rows:
                    active_carriers.append(carrier)
                    ingest_rows(rows, temp_routes, fallback_cs_routes, discovered_airports, state, skip_ryanair=ryanair_direct_ok)
                    if len(rows) >= 50:
                        dests = sorted({(r.get("arr_iata") or "").upper() for r in rows if r.get("arr_iata")})
                        if dests:
                            capped_cutoffs.append(dests[-1])
            time.sleep(0.14)

        for carrier in active_carriers:
            rows, status = airlabs_get(
                "routes",
                {"arr_iata": iata, "airline_iata": carrier, "_fields": "airline_iata,cs_airline_iata,dep_iata,arr_iata,dep_time,days"},
                state,
            )
            if status == "QUOTA_EXCEEDED":
                return "QUOTA_EXCEEDED"
            if status == "OK" and isinstance(rows, list) and rows:
                calls_made += 1
                ingest_rows(rows, temp_routes, fallback_cs_routes, discovered_airports, state, skip_ryanair=ryanair_direct_ok)
            time.sleep(0.14)

        if capped_cutoffs:
            min_cutoff = min(capped_cutoffs)
            to_check = [d for d in CANDIDATE_DESTINATIONS if d != iata and d >= min_cutoff]
            for dest in to_check:
                rows, status = airlabs_get(
                    "routes",
                    {"dep_iata": iata, "arr_iata": dest, "_fields": "airline_iata,cs_airline_iata,dep_iata,arr_iata,dep_time,days"},
                    state,
                )
                if status == "QUOTA_EXCEEDED":
                    break
                if status == "OK" and isinstance(rows, list):
                    calls_made += 1
                    if rows:
                        ingest_rows(rows, temp_routes, fallback_cs_routes, discovered_airports, state, skip_ryanair=ryanair_direct_ok)
                        ret_rows, ret_status = airlabs_get(
                            "routes",
                            {"dep_iata": dest, "arr_iata": iata, "_fields": "airline_iata,cs_airline_iata,dep_iata,arr_iata,dep_time,days"},
                            state,
                        )
                        if ret_status == "QUOTA_EXCEEDED":
                            break
                        if ret_status == "OK" and isinstance(ret_rows, list) and ret_rows:
                            calls_made += 1
                            ingest_rows(ret_rows, temp_routes, fallback_cs_routes, discovered_airports, state, skip_ryanair=ryanair_direct_ok)
                time.sleep(0.14)

    for pair, airlines_dict in fallback_cs_routes.items():
        dest_airlines = temp_routes.setdefault(pair, {})
        for al_key, al_val in airlines_dict.items():
            if al_key not in dest_airlines:
                dest_airlines[al_key] = al_val

    for k in [k for k in routes_index if k[0] == iata or k[1] == iata]:
        del routes_index[k]

    for (orig, dest), airlines_dict in temp_routes.items():
        routes_index[(orig, dest)] = {
            "from": orig,
            "to": dest,
            "airlines": [
                {
                    "name": a["name"],
                    "iata": a["iata"],
                    "days": sorted(a["days"]),
                    "sample_times": sorted(a["sample_times"]),
                }
                for a in sorted(airlines_dict.values(), key=lambda x: x["name"])
            ],
        }

    out_dests = sorted({d for (o, d) in temp_routes if o == iata})
    in_origs = sorted({o for (o, d) in temp_routes if d == iata})
    print(f"[INFO] {iata}: {calls_made} chiamate AirLabs, {len(out_dests)} destinazioni in partenza, {len(in_origs)} in arrivo.")
    return "OK"


def parse_args():
    parser = argparse.ArgumentParser(description="Scansione rotte per FlightMap Italia")
    parser.add_argument(
        "--airport",
        default=os.getenv("TARGET_AIRPORT", "AUTO"),
        help="AUTO, RYANAIR (tutta la flotta Ryanair), ALL (tutti gli 8), oppure singolo IATA (es. BLQ)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=os.getenv("FORCE_RESCAN", "false").strip().lower() in ("1", "true", "yes"),
        help="Forza l'aggiornamento ignorando l'intervallo di giorni",
    )
    return parser.parse_args()


def main():
    print(f"=== FlightMap Scanner {SCANNER_VERSION} ===")
    args = parse_args()
    target = (args.airport or "AUTO").strip().upper()
    force = bool(args.force)

    if target != "RYANAIR" and (not AIRLABS_KEY or AIRLABS_KEY == "INCOLLA_QUI_LA_TUA_API_KEY"):
        raise SystemExit("Configura prima il secret AIRLABS_KEY su GitHub (o la variabile d'ambiente locale).")

    now = datetime.now(ITALY_TZ)
    state = load_state(now)

    existing = load_json(ROUTES_FILE, {"airports": {}, "routes": []})
    airports_db = {**existing.get("airports", {}), **BASE_AIRPORTS}
    routes_index = {(r["from"], r["to"]): r for r in existing.get("routes", [])}
    discovered_airports = set(airports_db.keys())

    ryanair_synced_now = False

    # 1) Modalita dedicata RYANAIR (manuale, 0 token AirLabs, tutta la flotta europea)
    if target == "RYANAIR":
        ok = sync_global_ryanair_fleet(now, routes_index, airports_db, discovered_airports)
        if ok:
            state["last_scan"]["RYANAIR"] = now.isoformat(timespec="seconds")
            ryanair_synced_now = True
        to_scan = []
    else:
        # In AUTO, aggiorna settimanalmente l'intera flotta Ryanair (0 token AirLabs!)
        if target == "AUTO" and (force or days_since(state["last_scan"].get("RYANAIR"), now) >= RYANAIR_GLOBAL_INTERVAL_DAYS):
            ok = sync_global_ryanair_fleet(now, routes_index, airports_db, discovered_airports)
            if ok:
                state["last_scan"]["RYANAIR"] = now.isoformat(timespec="seconds")
                ryanair_synced_now = True

        if target == "ALL":
            to_scan = list(AIRPORT_SCHEDULE.keys())
            print(f"[MODO ALL] Forzo scansione completa su: {', '.join(to_scan)}")
        elif target in AIRPORT_SCHEDULE:
            to_scan = [target]
            print(f"[MODO SINGOLO] Sincronizzo solo {target} (preservo gli altri aeroporti in cache).")
        elif target == "AUTO":
            to_scan = [
                code for code, interval_days in AIRPORT_SCHEDULE.items()
                if force or days_since(state["last_scan"].get(code), now) >= interval_days
            ]
        else:
            raise SystemExit(f"Valore non valido: '{target}'. Ammessi: RYANAIR, AUTO, ALL, {', '.join(AIRPORT_SCHEDULE.keys())}")

    if not to_scan and not ryanair_synced_now:
        print("[OK] Tutto già aggiornato secondo le frequenze impostate. 0 chiamate usate.")
    else:
        if to_scan:
            print(f"[SCAN] Aeroporti AirLabs in coda: {', '.join(to_scan)}")
            for code in to_scan:
                print(f"[SCAN] Avvio scaricamento rotte per {code}...")
                status = scan_airport_routes(
                    code, now, state, routes_index, airports_db, discovered_airports,
                    ryanair_already_synced=ryanair_synced_now,
                )
                if status == "QUOTA_EXCEEDED":
                    print(f"[BLOCCO QUOTA] Fermato su {code}: {state['blocked_reason']}")
                    break

                state["last_scan"][code] = now.isoformat(timespec="seconds")
                if not (isinstance(state.get("remote_remaining"), int) and state["remote_remaining"] <= MIN_RESERVE_CALLS):
                    state["blocked"] = False
                    state["blocked_reason"] = None
                rem_str = f" (rimaste su AirLabs: {state['remote_remaining']})" if state.get("remote_remaining") is not None else ""
                print(f"[OK] {code} completato. Chiamate AirLabs: {state['units_used']}/{state.get('units_limit', MAX_MONTHLY_CALLS)}{rem_str}")
                time.sleep(0.3)

    enrich_missing_airports(discovered_airports, airports_db, state, allow_airlabs_fallback=(target != "RYANAIR"))

    valid_routes = [
        r for r in routes_index.values()
        if r["from"] in airports_db and r["to"] in airports_db
    ]
    dropped = len(routes_index) - len(valid_routes)
    if dropped > 0:
        print(f"[WARN] {dropped} rotte escluse per coordinate mancanti.")

    save_json(STATE_FILE, state, compact=False)
    output = {
        "generated_at": now.isoformat(timespec="seconds"),
        "quota_status": {
            "cycle": state["cycle"],
            "units_used": state["units_used"],
            "units_limit": state.get("units_limit", MAX_MONTHLY_CALLS),
            "remote_remaining": state.get("remote_remaining"),
            "blocked": state["blocked"],
            "reason": state["blocked_reason"],
            "last_scan_by_airport": state["last_scan"],
        },
        "airports": airports_db,
        "routes": valid_routes,
    }
    # Usa formato compatto quando il file supera le 500 rotte per mantenere il caricamento ultra-veloce su mobile
    save_json(ROUTES_FILE, output, compact=(len(valid_routes) > 500))
    print(f"[FINE] Salvato {ROUTES_FILE}: {len(airports_db)} aeroporti, {len(valid_routes)} rotte.")


if __name__ == "__main__":
    main()
