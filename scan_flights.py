import argparse
import csv
import io
import json
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import requests

# ================= CONFIGURAZIONE =================
AIRLABS_KEY = os.getenv("AIRLABS_KEY", "INCOLLA_QUI_LA_TUA_API_KEY")
AIRLABS_BASE = "https://airlabs.co/api/v9"
ITALY_TZ = ZoneInfo("Europe/Rome")

# Database gratuito pubblico con coordinate/citta di tutti gli aeroporti mondiali (0 chiamate AirLabs!)
OURAIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

# Limite mensile prudenziale di sicurezza (viene aggiornato automaticamente con i dati reali di AirLabs)
MAX_MONTHLY_CALLS = 950
MIN_RESERVE_CALLS = 15  # Blocca le chiamate se AirLabs segnala <= 15 richieste residue nel mese

# Giorno del mese in cui si azzera il contatore mensile AirLabs (1-28)
BILLING_RESET_DAY = 1

# Frequenza automatica (modalita AUTO): Bologna ogni 7 giorni, gli altri 7 ogni 30 giorni
AIRPORT_SCHEDULE = {
    "BLQ": 7,   # Bologna: ogni 7 giorni
    "VRN": 30,  # Verona: ogni 30 giorni
    "BGY": 30,  # Bergamo: ogni 30 giorni
    "FLR": 30,  # Firenze: ogni 30 giorni
    "TSF": 30,  # Treviso: ogni 30 giorni
    "LIN": 30,  # Milano Linate: ogni 30 giorni
    "MXP": 30,  # Milano Malpensa: ogni 30 giorni
    "VCE": 30,  # Venezia: ogni 30 giorni
}

# Compagnie principali per ciascun aeroporto base (aggira il tetto di 50 righe/chiamata del piano free AirLabs)
AIRPORT_AIRLINES = {
    "BLQ": [
        "FR", "MW", "RK", "LW", "RR",  # Gruppo Ryanair (DAC, Malta Air, UK, Lauda, Buzz)
        "W4", "W6", "EC", "U2",        # Wizz Air & easyJet
        "AZ", "EN", "LH", "AF", "KL", "WA", "BA", "IB", "YW", "I2",  # Major europee
        "VY", "V7", "OS", "LX", "SN", "TP", "SK", "DY", "AY", "EI",  # Altre europee
        "TK", "VF", "PC", "A3", "LO", "RO", "JU", "OU", "BT", "NO",  # Est Europa / Medio Oriente / Charter
        "EW", "HV", "TO", "EK", "QR", "FZ", "MS", "AT", "3O", "TU", "KM", "XZ", "XQ", "CA"
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

DEFAULT_AIRLINES = {
    "FR": "Ryanair", "MW": "Ryanair (Malta Air)", "RK": "Ryanair UK",
    "LW": "Ryanair (Lauda)", "RR": "Ryanair (Buzz)",
    "U2": "easyJet", "EC": "easyJet Europe", "DS": "easyJet Switzerland",
    "W6": "Wizz Air", "W4": "Wizz Air Malta", "W9": "Wizz Air UK",
    "AZ": "ITA Airways", "LH": "Lufthansa", "EN": "Air Dolomiti", "CL": "Lufthansa CityLine",
    "AF": "Air France", "KL": "KLM", "WA": "KLM Cityhopper",
    "BA": "British Airways", "IB": "Iberia", "I2": "Iberia Express", "YW": "Air Nostrum",
    "VY": "Vueling", "V7": "Volotea", "OS": "Austrian Airlines", "LX": "SWISS",
    "2L": "Helvetic Airways", "SN": "Brussels Airlines", "TP": "TAP Air Portugal",
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


def save_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
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
    state["airlines_cache"] = {**DEFAULT_AIRLINES, **state.get("airlines_cache", {})}
    return state


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

    # In AirLabs v9: limits_by_month = tetto mensile (es. 1000/2000), limits_total = chiamate residue
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
    if code in state["airlines_cache"]:
        return state["airlines_cache"][code]

    data, status = airlabs_get("airlines", {"iata_code": code}, state)
    if status == "OK" and isinstance(data, list) and data:
        name = data[0].get("name") or code
        state["airlines_cache"][code] = name
        return name

    state["airlines_cache"][code] = code
    return code


def enrich_missing_airports(needed_codes: set, airports_db: dict, state: dict):
    """Risolve coordinate e nomi citta degli aeroporti esteri GRATIS da OurAirports CSV (0 token AirLabs)."""
    to_resolve = sorted(
        c for c in needed_codes
        if c and c not in BASE_AIRPORTS and (
            c not in airports_db
            or airports_db[c].get("lat") is None
            or airports_db[c].get("city") == airports_db[c].get("name")
        )
    )
    if not to_resolve:
        return

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
                        ap_city = (row.get("municipality") or ap_name).strip()
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
        else:
            print(f"[AIRPORTS] Download OurAirports fallito (HTTP {resp.status_code}).")
    except requests.RequestException as exc:
        print(f"[AIRPORTS] Errore rete OurAirports ({exc}).")

    # Fallback AirLabs SOLO per codici ancora privi di coordinate
    still_missing = sorted(c for c in needed_codes if c and (c not in airports_db or airports_db[c].get("lat") is None))
    for code in still_missing:
        data, status = airlabs_get("airports", {"iata_code": code}, state)
        if status == "QUOTA_EXCEEDED":
            print(f"[BLOCCO QUOTA] Interrotto fallback aeroporti su {code}.")
            break
        if status == "OK" and isinstance(data, list) and data:
            ap = data[0]
            lat = ap.get("lat")
            lon = ap.get("lng") if ap.get("lng") is not None else ap.get("lon")
            if lat is not None and lon is not None:
                airports_db[code] = {
                    "iata": code,
                    "name": ap.get("name") or code,
                    "city": ap.get("city") or ap.get("name") or code,
                    "country": ap.get("country_code") or "",
                    "lat": float(lat),
                    "lon": float(lon),
                    "is_base": False,
                }
        time.sleep(0.2)


def ingest_rows(rows: list, temp_routes: dict, fallback_cs_routes: dict, discovered_airports: set, state: dict):
    for row in rows:
        orig = (row.get("dep_iata") or "").upper()
        dest = (row.get("arr_iata") or "").upper()
        if not orig or not dest or orig == dest:
            continue

        discovered_airports.add(orig)
        discovered_airports.add(dest)

        is_codeshare = bool(row.get("cs_airline_iata"))
        al_iata = (row.get("cs_airline_iata") if is_codeshare else row.get("airline_iata") or "").upper()
        al_name = resolve_airline_name(al_iata, state)
        days = parse_days(row.get("days"))
        dep_time = (row.get("dep_time") or "")[:5]

        target_map = fallback_cs_routes if is_codeshare else temp_routes
        entry = target_map.setdefault((orig, dest), {}).setdefault(
            al_iata or al_name,
            {"name": al_name, "iata": al_iata, "days": set(), "sample_times": set()},
        )
        entry["days"].update(days)
        if dep_time and len(entry["sample_times"]) < 4:
            entry["sample_times"].add(dep_time)


def scan_airport_routes(iata: str, state: dict, routes_index: dict, discovered_airports: set):
    """Scarica le rotte per compagnia per aggirare il limite di 50 righe/chiamata del piano free AirLabs."""
    temp_routes = {}
    fallback_cs_routes = {}
    calls_made = 0
    raw_rows_total = 0

    # 1) Passata generale veloce (2 chiamate) per scoprire eventuali compagnie extra non in lista
    discovered_carriers = list(AIRPORT_AIRLINES.get(iata, []))
    seen_carriers = set(discovered_carriers)

    for direction_param in ({"dep_iata": iata}, {"arr_iata": iata}):
        rows, status = airlabs_get(
            "routes",
            {**direction_param, "_fields": "airline_iata,cs_airline_iata,dep_iata,arr_iata,dep_time,days"},
            state,
        )
        if status == "QUOTA_EXCEEDED":
            return "QUOTA_EXCEEDED"
        if status == "OK" and isinstance(rows, list):
            calls_made += 1
            raw_rows_total += len(rows)
            ingest_rows(rows, temp_routes, fallback_cs_routes, discovered_airports, state)
            for r in rows:
                for k in ("airline_iata", "cs_airline_iata"):
                    c = (r.get(k) or "").upper()
                    if c and c not in seen_carriers:
                        seen_carriers.add(c)
                        discovered_carriers.append(c)
        time.sleep(0.2)

    # 2) Interrogazione mirata per compagnia (partenze + arrivi) per ottenere tutte le destinazioni
    for carrier in discovered_carriers:
        for direction_param in ({"dep_iata": iata, "airline_iata": carrier}, {"arr_iata": iata, "airline_iata": carrier}):
            rows, status = airlabs_get(
                "routes",
                {**direction_param, "_fields": "airline_iata,cs_airline_iata,dep_iata,arr_iata,dep_time,days"},
                state,
            )
            if status == "QUOTA_EXCEEDED":
                return "QUOTA_EXCEEDED"
            if status == "OK" and isinstance(rows, list) and rows:
                calls_made += 1
                raw_rows_total += len(rows)
                ingest_rows(rows, temp_routes, fallback_cs_routes, discovered_airports, state)
            time.sleep(0.18)

    # Integra eventuali rotte viste solo come codeshare se non gia presenti
    for pair, airlines_dict in fallback_cs_routes.items():
        dest_airlines = temp_routes.setdefault(pair, {})
        for al_key, al_val in airlines_dict.items():
            if al_key not in dest_airlines:
                dest_airlines[al_key] = al_val

    # Aggiorna solo le rotte di questo aeroporto, preservando intatti gli altri 7
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

    out_count = sum(1 for (o, _) in temp_routes if o == iata)
    in_count = sum(1 for (_, d) in temp_routes if d == iata)
    print(f"[INFO] {iata}: {calls_made} chiamate, {raw_rows_total} voli -> {out_count} destinazioni in partenza, {in_count} in arrivo.")
    return "OK"


def parse_args():
    parser = argparse.ArgumentParser(description="Scansione rotte AirLabs per FlightMap Italia")
    parser.add_argument(
        "--airport",
        default=os.getenv("TARGET_AIRPORT", "AUTO"),
        help="AUTO (schedulatore), ALL (tutti gli 8), oppure singolo codice IATA (es. BLQ)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=os.getenv("FORCE_RESCAN", "false").strip().lower() in ("1", "true", "yes"),
        help="Forza l'aggiornamento ignorando l'intervallo di giorni",
    )
    return parser.parse_args()


def main():
    if not AIRLABS_KEY or AIRLABS_KEY == "INCOLLA_QUI_LA_TUA_API_KEY":
        raise SystemExit("Configura prima il secret AIRLABS_KEY su GitHub (o la variabile d'ambiente locale).")

    args = parse_args()
    target = (args.airport or "AUTO").strip().upper()
    force = bool(args.force)

    now = datetime.now(ITALY_TZ)
    state = load_state(now)

    existing = load_json(ROUTES_FILE, {"airports": {}, "routes": []})
    airports_db = {**existing.get("airports", {}), **BASE_AIRPORTS}
    routes_index = {(r["from"], r["to"]): r for r in existing.get("routes", [])}
    discovered_airports = set(airports_db.keys())

    if target == "ALL":
        to_scan = list(AIRPORT_SCHEDULE.keys())
        print(f"[MODO ALL] Forzo scansione completa su: {', '.join(to_scan)}")
    elif target in AIRPORT_SCHEDULE:
        to_scan = [target]
        print(f"[MODO SINGOLO] Sincronizzo solo {target} (preservo gli altri aeroporti in cache).")
    elif target == "AUTO":
        to_scan = []
        for code, interval_days in AIRPORT_SCHEDULE.items():
            last_str = state["last_scan"].get(code)
            if force or not last_str:
                to_scan.append(code)
            else:
                last_dt = datetime.fromisoformat(last_str)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=ITALY_TZ)
                if (now - last_dt).days >= interval_days:
                    to_scan.append(code)
    else:
        raise SystemExit(f"Codice aeroporto non valido: '{target}'. Valori ammessi: AUTO, ALL, {', '.join(AIRPORT_SCHEDULE.keys())}")

    if not to_scan:
        print("[OK] Tutti gli aeroporti sono già aggiornati secondo la frequenza impostata. 0 chiamate usate.")
    else:
        print(f"[SCAN] Aeroporti in coda: {', '.join(to_scan)}")
        for code in to_scan:
            print(f"[SCAN] Avvio scaricamento rotte AirLabs per {code}...")
            status = scan_airport_routes(code, state, routes_index, discovered_airports)
            if status == "QUOTA_EXCEEDED":
                print(f"[BLOCCO QUOTA] Fermato su {code}: {state['blocked_reason']}")
                break

            state["last_scan"][code] = now.isoformat(timespec="seconds")
            if not (isinstance(state.get("remote_remaining"), int) and state["remote_remaining"] <= MIN_RESERVE_CALLS):
                state["blocked"] = False
                state["blocked_reason"] = None
            rem_str = f" (rimaste su AirLabs: {state['remote_remaining']})" if state.get("remote_remaining") is not None else ""
            print(f"[OK] {code} completato. Chiamate usate: {state['units_used']}/{state.get('units_limit', MAX_MONTHLY_CALLS)}{rem_str}")
            time.sleep(0.3)

    # Arricchisce coordinate e nomi citta gratuitamente da OurAirports
    enrich_missing_airports(discovered_airports, airports_db, state)

    valid_routes = [
        r for r in routes_index.values()
        if r["from"] in airports_db and r["to"] in airports_db
    ]
    dropped = len(routes_index) - len(valid_routes)
    if dropped > 0:
        print(f"[WARN] {dropped} rotte escluse per coordinate mancanti.")

    save_json(STATE_FILE, state)
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
    save_json(ROUTES_FILE, output)
    print(f"[FINE] Salvato {ROUTES_FILE}: {len(airports_db)} aeroporti, {len(valid_routes)} rotte.")


if __name__ == "__main__":
    main()
