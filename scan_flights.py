import json
import os
import time
from datetime import datetime, timedelta
import requests

# ================= CONFIGURAZIONE =================
AIRLABS_KEY = os.getenv("AIRLABS_KEY", "INCOLLA_QUI_LA_TUA_API_KEY")
AIRLABS_BASE = "https://airlabs.co/api/v9"

# Limite mensile prudenziale (piano Free AirLabs = 1.000 richieste/mese)
MAX_MONTHLY_CALLS = 900

# Giorno del mese in cui si azzera il contatore mensile AirLabs (1-28)
BILLING_RESET_DAY = 1

# Intervallo di aggiornamento (in giorni) per ciascun aeroporto
AIRPORT_SCHEDULE = {
    "BLQ": 7,
    "VRN": 7,
    "BGY": 7,
    "FLR": 7,
    "TSF": 7,
    "LIN": 7,
    "MXP": 7,
    "VCE": 7,
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
    "FR": "Ryanair", "RK": "Ryanair UK", "LW": "Lauda Europe", "U2": "easyJet",
    "EC": "easyJet Europe", "W6": "Wizz Air", "W4": "Wizz Air Malta",
    "AZ": "ITA Airways", "LH": "Lufthansa", "EN": "Air Dolomiti",
    "AF": "Air France", "KL": "KLM", "BA": "British Airways", "IB": "Iberia",
    "VY": "Vueling", "V7": "Volotea", "OS": "Austrian Airlines", "LX": "SWISS",
    "SN": "Brussels Airlines", "TP": "TAP Air Portugal", "SK": "SAS",
    "DY": "Norwegian", "AY": "Finnair", "EI": "Aer Lingus", "TK": "Turkish Airlines",
    "A3": "Aegean Airlines", "LO": "LOT Polish Airlines", "OK": "Czech Airlines",
    "UX": "Air Europa", "NO": "Neos", "EW": "Eurowings", "HV": "Transavia",
    "TO": "Transavia France", "PC": "Pegasus Airlines", "EK": "Emirates",
    "QR": "Qatar Airways", "EY": "Etihad Airways", "RO": "TAROM",
    "JU": "Air Serbia", "OU": "Croatia Airlines", "BT": "airBaltic",
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
        "blocked": False,
        "blocked_reason": None,
        "last_scan": {},
        "airlines_cache": dict(DEFAULT_AIRLINES),
    })
    if state.get("cycle") != cycle:
        print(f"[QUOTA] Nuovo ciclo mensile ({cycle}): azzero contatore chiamate.")
        state["cycle"] = cycle
        state["units_used"] = 0
        state["blocked"] = False
        state["blocked_reason"] = None
    state["airlines_cache"] = {**DEFAULT_AIRLINES, **state.get("airlines_cache", {})}
    return state


def airlabs_get(endpoint: str, params: dict, state: dict):
    """Esegue una chiamata GET ad AirLabs con blocco preventivo e controllo limiti."""
    if state["units_used"] + 1 > MAX_MONTHLY_CALLS:
        state["blocked"] = True
        state["blocked_reason"] = (
            f"Soglia gratuita raggiunta ({state['units_used']}/{MAX_MONTHLY_CALLS} chiamate). "
            "Blocco attivo: riproverò automaticamente alla prossima scansione notturna."
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

    key_info = (payload.get("request") or {}).get("key") or {}
    limits_left = key_info.get("limits_by_month")
    if isinstance(limits_left, int) and limits_left <= 10:
        state["blocked"] = True
        state["blocked_reason"] = f"Chiamate residue AirLabs quasi esaurite ({limits_left} rimaste)."

    return payload.get("response", []), "OK"


def parse_days(raw_days) -> list:
    """Converte il campo days di AirLabs (lista o stringa) in numeri ISO 1..7."""
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
    """Scarica coordinate e nomi degli aeroporti esteri non ancora presenti in cache."""
    missing = sorted(c for c in needed_codes if c and c not in airports_db)
    if not missing:
        return

    if len(missing) > 5:
        print(f"[CACHE] Scarico catalogo aeroporti in 1 chiamata per risolvere {len(missing)} scali...")
        bulk, status = airlabs_get("airports", {}, state)
        if status == "QUOTA_EXCEEDED":
            return
        if status == "OK" and isinstance(bulk, list):
            needed_set = set(missing)
            for ap in bulk:
                code = (ap.get("iata_code") or "").upper()
                if code in needed_set:
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
                            "is_base": code in BASE_AIRPORTS,
                        }

    still_missing = sorted(c for c in needed_codes if c and c not in airports_db)
    for code in still_missing:
        data, status = airlabs_get("airports", {"iata_code": code}, state)
        if status == "QUOTA_EXCEEDED":
            print(f"[BLOCCO QUOTA] Interrotto arricchimento aeroporti su {code}.")
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
                    "is_base": code in BASE_AIRPORTS,
                }
        time.sleep(0.25)


def scan_airport_routes(iata: str, state: dict, routes_index: dict, discovered_airports: set):
    """Scarica tutte le rotte in partenza e in arrivo per uno degli 8 aeroporti base."""
    temp_routes = {}

    for direction_param in ({"dep_iata": iata}, {"arr_iata": iata}):
        offset = 0
        while True:
            params = {**direction_param, "limit": 500, "offset": offset}
            rows, status = airlabs_get("routes", params, state)
            if status == "QUOTA_EXCEEDED":
                return "QUOTA_EXCEEDED"
            if status != "OK" or not isinstance(rows, list) or not rows:
                break

            for row in rows:
                orig = (row.get("dep_iata") or "").upper()
                dest = (row.get("arr_iata") or "").upper()
                if not orig or not dest or orig == dest:
                    continue

                if row.get("cs_airline_iata"):
                    continue

                discovered_airports.add(orig)
                discovered_airports.add(dest)

                al_iata = (row.get("airline_iata") or "").upper()
                al_name = row.get("airline_name") or resolve_airline_name(al_iata, state)
                days = parse_days(row.get("days"))
                dep_time = (row.get("dep_time") or "")[:5]

                entry = temp_routes.setdefault((orig, dest), {}).setdefault(
                    al_iata or al_name,
                    {"name": al_name, "iata": al_iata, "days": set(), "sample_times": set()},
                )
                entry["days"].update(days)
                if dep_time and len(entry["sample_times"]) < 4:
                    entry["sample_times"].add(dep_time)

            if len(rows) < 500:
                break
            offset += 500
            time.sleep(0.25)

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

    return "OK"


def main():
    if not AIRLABS_KEY or AIRLABS_KEY == "INCOLLA_QUI_LA_TUA_API_KEY":
        raise SystemExit("Configura prima il secret AIRLABS_KEY su GitHub (o la variabile d'ambiente locale).")

    now = datetime.now()
    state = load_state(now)

    existing = load_json(ROUTES_FILE, {"airports": {}, "routes": []})
    airports_db = {**existing.get("airports", {}), **BASE_AIRPORTS}
    routes_index = {(r["from"], r["to"]): r for r in existing.get("routes", [])}
    discovered_airports = set(airports_db.keys())

    to_scan = []
    for code, interval_days in AIRPORT_SCHEDULE.items():
        last_str = state["last_scan"].get(code)
        if not last_str:
            to_scan.append(code)
        else:
            last_dt = datetime.fromisoformat(last_str)
            if (now - last_dt).days >= interval_days:
                to_scan.append(code)

    if not to_scan:
        print("[OK] Tutti gli aeroporti sono già aggiornati. Nessuna chiamata consumata.")
    else:
        print(f"[SCAN] Aeroporti da aggiornare: {', '.join(to_scan)}")
        for code in to_scan:
            if state["units_used"] + 2 > MAX_MONTHLY_CALLS:
                state["blocked"] = True
                state["blocked_reason"] = (
                    f"Chiamate insufficienti per scansionare {code} "
                    f"({state['units_used']}/{MAX_MONTHLY_CALLS} usate). Retry alla prossima notte."
                )
                print(f"[BLOCCO QUOTA] {state['blocked_reason']}")
                break

            print(f"[SCAN] Scarico rotte AirLabs per {code}...")
            status = scan_airport_routes(code, state, routes_index, discovered_airports)
            if status == "QUOTA_EXCEEDED":
                print(f"[BLOCCO QUOTA] Fermato su {code}: {state['blocked_reason']}")
                break

            state["last_scan"][code] = now.isoformat(timespec="seconds")
            state["blocked"] = False
            state["blocked_reason"] = None
            print(f"[OK] {code} aggiornato. Chiamate usate: {state['units_used']}/{MAX_MONTHLY_CALLS}")
            time.sleep(0.3)

    if not state["blocked"]:
        enrich_missing_airports(discovered_airports, airports_db, state)

    valid_routes = [
        r for r in routes_index.values()
        if r["from"] in airports_db and r["to"] in airports_db
    ]

    save_json(STATE_FILE, state)
    output = {
        "generated_at": now.isoformat(timespec="seconds"),
        "quota_status": {
            "cycle": state["cycle"],
            "units_used": state["units_used"],
            "units_limit": MAX_MONTHLY_CALLS,
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
