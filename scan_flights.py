import argparse
import csv
import io
import json
import os
import time
from datetime import datetime, timedelta
import requests

# ================= CONFIGURAZIONE =================
AIRLABS_KEY = os.getenv("AIRLABS_KEY", "INCOLLA_QUI_LA_TUA_API_KEY")
AIRLABS_BASE = "https://airlabs.co/api/v9"

# Database gratuito pubblico con coordinate/citta di tutti gli aeroporti mondiali (0 chiamate AirLabs!)
OURAIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

# Limite mensile prudenziale di sicurezza (viene aggiornato anche leggendo il residuo reale di AirLabs)
MAX_MONTHLY_CALLS = 900
MIN_RESERVE_CALLS = 15  # Ferma le chiamate se AirLabs segnala meno di 15 richieste residue nel mese

# Giorno del mese in cui si azzera il contatore mensile AirLabs (1-28)
BILLING_RESET_DAY = 1

# Frequenza automatica (modalita AUTO): Bologna ogni settimana, gli altri 7 ogni 30 giorni
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

# Limite di sicurezza pagine per direzione (50 voli/pagina sul piano free -> 25 pagine = 1.250 voli)
MAX_PAGES_PER_DIRECTION = int(os.getenv("MAX_PAGES_PER_DIRECTION", "25"))

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

# Cache compagnie piu comuni per evitare chiamate /airlines inutili
DEFAULT_AIRLINES = {
    "FR": "Ryanair", "RK": "Ryanair UK", "LW": "Lauda Europe", "RR": "Buzz",
    "U2": "easyJet", "EC": "easyJet Europe", "DS": "easyJet Switzerland",
    "W6": "Wizz Air", "W4": "Wizz Air Malta", "W9": "Wizz Air UK",
    "AZ": "ITA Airways", "LH": "Lufthansa", "EN": "Air Dolomiti", "CL": "Lufthansa CityLine",
    "AF": "Air France", "KL": "KLM", "BA": "British Airways", "IB": "Iberia",
    "I2": "Iberia Express", "YW": "Air Nostrum", "VY": "Vueling", "V7": "Volotea",
    "OS": "Austrian Airlines", "LX": "SWISS", "2L": "Helvetic Airways",
    "SN": "Brussels Airlines", "TP": "TAP Air Portugal", "SK": "SAS",
    "DY": "Norwegian", "D8": "Norwegian Air Sweden", "AY": "Finnair",
    "EI": "Aer Lingus", "TK": "Turkish Airlines", "VF": "AJet", "PC": "Pegasus Airlines",
    "A3": "Aegean Airlines", "GQ": "Sky Express", "LO": "LOT Polish Airlines",
    "OK": "Czech Airlines", "QS": "Smartwings", "UX": "Air Europa", "NO": "Neos",
    "EW": "Eurowings", "4Y": "Discover Airlines", "DE": "Condor", "X3": "TUI fly",
    "HV": "Transavia", "TO": "Transavia France", "LS": "Jet2.com", "BY": "TUI Airways",
    "EK": "Emirates", "QR": "Qatar Airways", "EY": "Etihad Airways", "FZ": "flydubai",
    "MS": "EgyptAir", "SM": "Air Cairo", "AT": "Royal Air Maroc", "3O": "Air Arabia Maroc",
    "TU": "Tunisair", "BJ": "Nouvelair", "RO": "TAROM", "H4": "HiSky", "0B": "Blue Air",
    "JU": "Air Serbia", "OU": "Croatia Airlines", "BT": "airBaltic", "LG": "Luxair",
    "KM": "KM Malta Airlines", "CY": "Cyprus Airways", "FB": "Bulgaria Air",
    "FI": "Icelandair", "OG": "PLAY", "LY": "El Al", "RJ": "Royal Jordanian",
    "SV": "Saudia", "G9": "Air Arabia", "WY": "Oman Air", "CA": "Air China",
    "MU": "China Eastern", "HU": "Hainan Airlines", "CX": "Cathay Pacific",
    "SQ": "Singapore Airlines", "TG": "Thai Airways", "KE": "Korean Air",
    "JL": "Japan Airlines", "NH": "ANA", "BR": "EVA Air", "VN": "Vietnam Airlines",
    "DL": "Delta Air Lines", "UA": "United Airlines", "AA": "American Airlines",
    "AC": "Air Canada", "TS": "Air Transat", "LA": "LATAM Airlines", "ET": "Ethiopian Airlines",
    "U6": "Ural Airlines", "PS": "Ukraine Intl", "5F": "FlyOne", "4O": "Interjet",
    "XQ": "SunExpress", "XC": "Corendon Airlines", "MT": "Malta MedAir", "XZ": "AeroItalia",
    "2A": "Deutsche Bahn", "B2": "Belavia", "A9": "Georgian Airways", "J2": "Azerbaijan Airlines",
    "HY": "Uzbekistan Airways", "KC": "Air Astana", "AI": "Air India",
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
    """Esegue una chiamata GET ad AirLabs con blocco preventivo e lettura has_more / quota."""
    # Se conosciamo il residuo reale lato AirLabs usiamo quello, altrimenti il limite locale
    rem = state.get("remote_remaining")
    if isinstance(rem, int) and rem <= MIN_RESERVE_CALLS:
        state["blocked"] = True
        state["blocked_reason"] = (
            f"Soglia di riserva AirLabs raggiunta ({rem} chiamate residue). "
            "Blocco attivo: riproverò automaticamente appena torna disponibile quota gratuita."
        )
        return None, False, "QUOTA_EXCEEDED"

    if rem is None and state["units_used"] + 1 > MAX_MONTHLY_CALLS:
        state["blocked"] = True
        state["blocked_reason"] = (
            f"Soglia locale raggiunta ({state['units_used']}/{MAX_MONTHLY_CALLS} chiamate). "
            "Blocco attivo: riproverò automaticamente alla prossima scansione."
        )
        return None, False, "QUOTA_EXCEEDED"

    query = {"api_key": AIRLABS_KEY, **params}
    url = f"{AIRLABS_BASE}/{endpoint}"

    try:
        resp = requests.get(url, params=query, timeout=30)
    except requests.RequestException as exc:
        print(f"[ERRORE RETE] {endpoint}: {exc}")
        return None, False, "NETWORK_ERROR"

    if resp.status_code == 429:
        state["blocked"] = True
        state["blocked_reason"] = "AirLabs ha restituito HTTP 429 (quota esaurita). Retry alla prossima esecuzione."
        return None, False, "QUOTA_EXCEEDED"

    if resp.status_code != 200:
        print(f"[ERRORE HTTP {resp.status_code}] {endpoint}: {resp.text[:200]}")
        return None, False, "HTTP_ERROR"

    payload = resp.json()

    if isinstance(payload, dict) and payload.get("error"):
        err = payload["error"]
        err_code = str(err.get("code", "")).lower()
        err_msg = err.get("message", "Errore sconosciuto AirLabs")
        if any(k in err_code or k in err_msg.lower() for k in ("limit", "quota", "exceeded", "expired", "credit")):
            state["blocked"] = True
            state["blocked_reason"] = f"Quota AirLabs esaurita ({err_msg}). Retry alla prossima esecuzione."
            return None, False, "QUOTA_EXCEEDED"
        print(f"[ERRORE API AIRLABS] {err_code}: {err_msg}")
        return None, False, "API_ERROR"

    state["units_used"] += 1

    req_info = payload.get("request") or {}
    has_more = bool(req_info.get("has_more", False))

    key_info = req_info.get("key") or {}
    limits_left = key_info.get("limits_by_month")
    limits_total = key_info.get("limits_total")
    if isinstance(limits_left, int):
        state["remote_remaining"] = limits_left
        if isinstance(limits_total, int) and limits_total > 0:
            state["units_limit"] = limits_total
            state["units_used"] = max(0, limits_total - limits_left)
        if limits_left <= MIN_RESERVE_CALLS:
            state["blocked"] = True
            state["blocked_reason"] = f"Chiamate residue AirLabs sotto la soglia di riserva ({limits_left} rimaste)."

    return payload.get("response", []), has_more, "OK"


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

    # Se la compagnia non e nella lista locale, proviamo 1 sola chiamata ad AirLabs (poi resta in cache)
    data, _, status = airlabs_get("airlines", {"iata_code": code}, state)
    if status == "OK" and isinstance(data, list) and data:
        name = data[0].get("name") or code
        state["airlines_cache"][code] = name
        return name

    state["airlines_cache"][code] = code
    return code


def enrich_missing_airports(needed_codes: set, airports_db: dict, state: dict):
    """Risolve coordinate e citta degli aeroporti esteri GRATIS da OurAirports CSV (0 chiamate AirLabs)."""
    missing = sorted(c for c in needed_codes if c and c not in airports_db)
    if not missing:
        return

    print(f"[AIRPORTS] Cerco coordinate per {len(missing)} nuovi aeroporti tramite OurAirports (0 token AirLabs)...")
    try:
        resp = requests.get(OURAIRPORTS_CSV_URL, timeout=45)
        if resp.status_code == 200:
            needed_set = set(missing)
            reader = csv.DictReader(io.StringIO(resp.text))
            resolved = 0
            for row in reader:
                code = (row.get("iata_code") or "").strip().upper()
                if code in needed_set and code not in airports_db:
                    lat_s = (row.get("latitude_deg") or "").strip()
                    lon_s = (row.get("longitude_deg") or "").strip()
                    if lat_s and lon_s:
                        airports_db[code] = {
                            "iata": code,
                            "name": (row.get("name") or code).strip(),
                            "city": (row.get("municipality") or row.get("name") or code).strip(),
                            "country": (row.get("iso_country") or "").strip().upper(),
                            "lat": float(lat_s),
                            "lon": float(lon_s),
                            "is_base": code in BASE_AIRPORTS,
                        }
                        resolved += 1
            print(f"[AIRPORTS] Risolti {resolved}/{len(missing)} aeroporti gratuitamente via OurAirports.")
        else:
            print(f"[AIRPORTS] Download OurAirports fallito (HTTP {resp.status_code}), passo al fallback AirLabs.")
    except requests.RequestException as exc:
        print(f"[AIRPORTS] Errore rete OurAirports ({exc}), passo al fallback AirLabs.")

    # Fallback AirLabs SOLO per eventuali rarissimi codici non trovati su OurAirports
    still_missing = sorted(c for c in needed_codes if c and c not in airports_db)
    for code in still_missing:
        data, _, status = airlabs_get("airports", {"iata_code": code}, state)
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
                    "is_base": code in BASE_AIRPORTS,
                }
        time.sleep(0.25)


def scan_airport_routes(iata: str, state: dict, routes_index: dict, discovered_airports: set):
    """Scarica TUTTE le pagine di rotte in partenza e in arrivo per un singolo aeroporto base."""
    temp_routes = {}
    fallback_cs_routes = {}  # Tenuto come riserva se una tratta ha solo righe codeshare
    total_raw_rows = 0
    total_pages = 0

    for label, direction_param in (("partenze", {"dep_iata": iata}), ("arrivi", {"arr_iata": iata})):
        offset = 0
        page = 0
        while page < MAX_PAGES_PER_DIRECTION:
            params = {
                **direction_param,
                "limit": 50,  # Massimo garantito su AirLabs Free (50 righe per pagina)
                "offset": offset,
                "_fields": "airline_iata,cs_airline_iata,dep_iata,arr_iata,dep_time,days",
            }
            rows, has_more, status = airlabs_get("routes", params, state)
            if status == "QUOTA_EXCEEDED":
                return "QUOTA_EXCEEDED"
            if status != "OK" or not isinstance(rows, list) or not rows:
                break

            page += 1
            total_pages += 1
            total_raw_rows += len(rows)

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

            # Avanza dell'esatto numero di righe ricevute e continua finche has_more e True
            offset += len(rows)
            if not has_more:
                break
            time.sleep(0.25)

        print(f"  -> {iata} ({label}): {page} pagine scaricate (offset finale {offset}).")

    # Integra eventuali rotte/compagnie viste solo come codeshare se non gia presenti
    for pair, airlines_dict in fallback_cs_routes.items():
        dest_airlines = temp_routes.setdefault(pair, {})
        for al_key, al_val in airlines_dict.items():
            if al_key not in dest_airlines:
                dest_airlines[al_key] = al_val

    # Aggiorna solo le rotte che coinvolgono questo aeroporto (preservando gli altri 7!)
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

    print(f"[INFO] {iata}: {total_pages} chiamate, {total_raw_rows} voli grezzi -> {len(temp_routes)} tratte dirette uniche.")
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

    now = datetime.now()
    state = load_state(now)

    existing = load_json(ROUTES_FILE, {"airports": {}, "routes": []})
    airports_db = {**existing.get("airports", {}), **BASE_AIRPORTS}
    routes_index = {(r["from"], r["to"]): r for r in existing.get("routes", [])}
    discovered_airports = set(airports_db.keys())

    # Selezione aeroporti da scansionare
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
            print(f"[OK] {code} completato. Chiamate usate nel ciclo: {state['units_used']}/{state.get('units_limit', MAX_MONTHLY_CALLS)}{rem_str}")
            time.sleep(0.3)

    # Arricchisce coordinate gratuitamente da OurAirports (anche se la quota AirLabs si fosse fermata!)
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
