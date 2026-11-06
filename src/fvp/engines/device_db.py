"""Profili di riferimento dei dispositivi per i controlli di coerenza.

ATTENZIONE: sono dati di riferimento da VALIDARE con file campione acquisiti dall'analista sullo stesso
modello e sulla stessa versione di sistema prima di usarli in una relazione. Ogni profilo ha il campo
"verificato": finché è False i risultati che ne derivano sono marcati con confidenza bassa.

Il laboratorio può aggiungere o correggere profili senza toccare il codice con un file JSON
<cartella dati>/device_profiles.json con la stessa struttura di MODELS (le chiavi sovrascrivono quelle incluse):
  {"Apple|iPhone 15": {"released": "2023-09-22", "launch_os": "17.0", "rear": [[5712, 4284]], ...,
                       "verificato": true, "fonte": "campioni di laboratorio 2026-03"}}
"""
from __future__ import annotations

# Risoluzioni di base (4:3, orientamento orizzontale). I ritagli 16:9 e 1:1 dell'app Fotocamera
# sono derivati automaticamente in device.py.
R5 = (2576, 1932)
R7 = (3088, 2320)
R12 = (4032, 3024)
R24 = (5712, 4284)
R48 = (8064, 6048)

# Date di rilascio pubblico delle versioni principali di iOS (x.0). Le beta per sviluppatori circolano da giugno.
IOS_RELEASES = {
    9: "2015-09-16", 10: "2016-09-13", 11: "2017-09-19", 12: "2018-09-17", 13: "2019-09-19", 14: "2020-09-16",
    15: "2021-09-20", 16: "2022-09-12", 17: "2023-09-18", 18: "2024-09-16", 26: "2025-09-15",
}


def _apple(released, launch_os, rear, front, max_os=None, heic=True):
    return {"released": released, "launch_os": launch_os, "max_os": max_os, "rear": [list(r) for r in rear],
            "front": [list(r) for r in front] if front is not None else None, "heic": heic,
            "verificato": False, "fonte": "specifiche pubbliche Apple; da validare con campioni"}


_STD = (R12,)                   # 12 MP su tutte le fotocamere posteriori
_48 = (R12, R24, R48)           # sensore 48 MP: 12 MP, 24 MP (predefinito dal 15) e 48 MP "HEIF Max"

# Chiave: "Make|Model" esattamente come scritto in EXIF IFD0.
MODELS: dict[str, dict] = {
    "Apple|iPhone 6s": _apple("2015-09-25", "9.0", _STD, (R5,), max_os="15", heic=False),
    "Apple|iPhone 6s Plus": _apple("2015-09-25", "9.0", _STD, (R5,), max_os="15", heic=False),
    "Apple|iPhone 7": _apple("2016-09-16", "10.0", _STD, (R7,), max_os="15"),
    "Apple|iPhone 7 Plus": _apple("2016-09-16", "10.0", _STD, (R7,), max_os="15"),
    "Apple|iPhone 8": _apple("2017-09-22", "11.0", _STD, (R7,), max_os="16"),
    "Apple|iPhone 8 Plus": _apple("2017-09-22", "11.0", _STD, (R7,), max_os="16"),
    "Apple|iPhone X": _apple("2017-11-03", "11.0", _STD, (R7,), max_os="16"),
    "Apple|iPhone XS": _apple("2018-09-21", "12.0", _STD, (R7,), max_os="18"),
    "Apple|iPhone XS Max": _apple("2018-09-21", "12.0", _STD, (R7,), max_os="18"),
    "Apple|iPhone XR": _apple("2018-10-26", "12.0", _STD, (R7,), max_os="18"),
    # Dall'11 la frontale è 12 MP; in modalità ravvicinata (predefinita in verticale) produce un ritaglio 7 MP
    "Apple|iPhone 11": _apple("2019-09-20", "13.0", _STD, (R12, R7)),
    "Apple|iPhone 11 Pro": _apple("2019-09-20", "13.0", _STD, (R12, R7)),
    "Apple|iPhone 11 Pro Max": _apple("2019-09-20", "13.0", _STD, (R12, R7)),
    "Apple|iPhone SE (2nd generation)": _apple("2020-04-24", "13.4", _STD, (R7,)),
    "Apple|iPhone 12": _apple("2020-10-23", "14.1", _STD, (R12, R7)),
    "Apple|iPhone 12 Pro": _apple("2020-10-23", "14.1", _STD, (R12, R7)),
    "Apple|iPhone 12 mini": _apple("2020-11-13", "14.2", _STD, (R12, R7)),
    "Apple|iPhone 12 Pro Max": _apple("2020-11-13", "14.2", _STD, (R12, R7)),
    "Apple|iPhone 13": _apple("2021-09-24", "15.0", _STD, (R12, R7)),
    "Apple|iPhone 13 mini": _apple("2021-09-24", "15.0", _STD, (R12, R7)),
    "Apple|iPhone 13 Pro": _apple("2021-09-24", "15.0", _STD, (R12, R7)),
    "Apple|iPhone 13 Pro Max": _apple("2021-09-24", "15.0", _STD, (R12, R7)),
    "Apple|iPhone SE (3rd generation)": _apple("2022-03-18", "15.4", _STD, (R7,)),
    "Apple|iPhone 14": _apple("2022-09-16", "16.0", _STD, (R12, R7)),
    "Apple|iPhone 14 Plus": _apple("2022-10-07", "16.0", _STD, (R12, R7)),
    # 14 Pro: 48 MP in ProRAW con iOS 16, in HEIF Max da iOS 17
    "Apple|iPhone 14 Pro": _apple("2022-09-16", "16.0", (R12, R48), (R12, R7)),
    "Apple|iPhone 14 Pro Max": _apple("2022-09-16", "16.0", (R12, R48), (R12, R7)),
    "Apple|iPhone 15": _apple("2023-09-22", "17.0", _48, (R12, R7)),
    "Apple|iPhone 15 Plus": _apple("2023-09-22", "17.0", _48, (R12, R7)),
    "Apple|iPhone 15 Pro": _apple("2023-09-22", "17.0", _48, (R12, R7)),
    "Apple|iPhone 15 Pro Max": _apple("2023-09-22", "17.0", _48, (R12, R7)),
    "Apple|iPhone 16": _apple("2024-09-20", "18.0", _48, (R12, R7)),
    "Apple|iPhone 16 Plus": _apple("2024-09-20", "18.0", _48, (R12, R7)),
    "Apple|iPhone 16 Pro": _apple("2024-09-20", "18.0", _48, (R12, R7)),
    "Apple|iPhone 16 Pro Max": _apple("2024-09-20", "18.0", _48, (R12, R7)),
    "Apple|iPhone 16e": _apple("2025-02-28", "18.3", _48, (R12, R7)),
    # Frontale "Center Stage" 18 MP: risoluzioni di uscita non profilate (front=None => controllo saltato)
    "Apple|iPhone 17": _apple("2025-09-19", "26.0", _48, None),
    "Apple|iPhone Air": _apple("2025-09-19", "26.0", _48, None),
    "Apple|iPhone 17 Pro": _apple("2025-09-19", "26.0", _48, None),
    "Apple|iPhone 17 Pro Max": _apple("2025-09-19", "26.0", _48, None),
}

# Convenzioni di nome dei file. "time": None = il nome non contiene l'ora; "local"/"utc" = ora nel nome.
# I gruppi nominati 'd' (YYYYMMDD) e 't' (HHMMSS) servono al confronto con DateTimeOriginal.
VENDORS: dict[str, dict] = {
    "apple": {
        "makes": ["apple"],
        "native": [r"^IMG_(?P<n>\d{4})\.(HEIC|JPG|JPEG|PNG|DNG|MOV)$"],
        "edited": [r"^IMG_E(?P<n>\d{4})\.(HEIC|JPG|JPEG|PNG|MOV)$"],
        "time": None,
        "folder": r"[\\/]DCIM[\\/](\d{3}APPLE|\d{6}__)[\\/]",
        "uppercase_ext": True,
    },
    "samsung": {
        "makes": ["samsung"],
        "native": [r"^(?P<d>\d{8})_(?P<t>\d{6})(\(\d+\))?\.(jpg|jpeg|heic|dng|mp4)$"],
        "edited": [],
        "time": "local",
        "folder": r"[\\/]DCIM[\\/]Camera[\\/]",
    },
    "google": {
        "makes": ["google"],
        "native": [r"^PXL_(?P<d>\d{8})_(?P<t>\d{6})\d{3}(\.[A-Z_.~0-9]+)?\.(jpg|jpeg|dng|mp4|heic)$"],
        "edited": [],
        "time": "utc",
        "folder": r"[\\/]DCIM[\\/]Camera[\\/]",
    },
    "android_generic": {
        "makes": ["xiaomi", "redmi", "poco", "huawei", "honor", "oneplus", "oppo", "realme", "vivo", "motorola"],
        "native": [r"^IMG_(?P<d>\d{8})_(?P<t>\d{6})(_\d+)?(_HDR)?\.(jpg|jpeg|heic|heif|dng)$"],
        "edited": [],
        "time": "local",
        "folder": r"[\\/]DCIM[\\/]Camera[\\/]",
    },
}

# Nomi prodotti da app di messaggistica o da altri passaggi: indicano la provenienza del FILE, non della foto.
TRANSFER_PATTERNS = [
    (r"^IMG-(?P<d>\d{8})-WA\d{4}\.", "WhatsApp (salvataggio/ricezione)",
     "WhatsApp ricomprime le foto inviate come media e ne rimuove l'EXIF: la data nel nome è quella di "
     "ricezione o salvataggio, non di scatto."),
    (r"^photo_(?P<d>\d{4}-\d{2}-\d{2})_(?P<t>\d{2}-\d{2}-\d{2})", "Telegram (esportazione)",
     "Il nome è assegnato da Telegram all'esportazione; la data è quella del messaggio."),
    (r"^signal-(?P<d>\d{4}-\d{2}-\d{2})-(?P<t>\d{6})", "Signal (salvataggio)",
     "Il nome è assegnato da Signal al salvataggio."),
    (r"^Screenshot[_ ]", "Screenshot", "Nome tipico di una cattura dello schermo."),
]
