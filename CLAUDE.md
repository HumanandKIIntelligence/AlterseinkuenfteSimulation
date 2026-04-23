# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the App

**Docker (empfohlen, Port 8502):**
```bash
docker compose up --build   # http://localhost:8502
docker compose down
```
Code-Änderungen sind sofort live (Volume-Mount), kein Rebuild nötig – außer bei Änderungen an `requirements.txt` oder `Dockerfile`.

**Lokal:**
```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

---

## Architektur

### Datenfluß
```
Sidebar-Eingaben (app.py)
    → Profil-Dataclass (engine.py)
    → berechne_rente() → RentenErgebnis
    → Tab-Module (tabs/*.py)
```

### Modulstruktur

| Modul | Verantwortung |
|---|---|
| `app.py` | Sidebar-Rendering, Tab-Dispatch |
| `engine.py` | Alle Berechnungen (kein Streamlit); `Profil`, `RentenErgebnis`, `berechne_rente`, `simuliere_szenarien`, `kapital_vs_rente` |
| `tabs/dashboard.py` | Kennzahlen, Wasserfall-Chart, Kaufkraft |
| `tabs/simulation.py` | Szenarien (pessimistisch/neutral/optimistisch), Kapitalverlauf, Renteneintrittsalter-Sensitivität |
| `tabs/auszahlung.py` | Kapital-Annuität vs. externe Rente, Break-Even, Laufzeitszenarien |
| `tabs/steuern.py` | Einkommensteuer-Schritte, Besteuerungsanteil-Chart, GKV/PKV-Vergleich |

### Wichtige Konstanten (engine.py)

| Konstante | Wert | Quelle |
|---|---|---|
| `RENTENWERT_2024` | 39,32 € | DRV West, 01.07.2024 |
| `GRUNDFREIBETRAG_2024` | 11.604 € | § 32a EStG 2024 |
| `AKTUELLES_JAHR` | 2025 | manuell aktualisieren |

### Steuerberechnung

- `einkommensteuer(zvE)` → Grundtarif 2024 nach § 32a EStG
- `besteuerungsanteil(eintritt_jahr)` → nach JStG 2022: ab 2023 nur +0,5 % p.a. (statt 1 %)
- GKV-Rentner: 7,3 % + ½ Zusatzbeitrag + volle PV (3,4 % / 4,0 %)

---

## Bekannte Vereinfachungen

- Kein direkter Rentenabschlag bei Frühverrentung (0,3 %/Monat) – wirkt indirekt über weniger Beitragsjahre
- Keine anderen Einkunftsarten (Mieteinnahmen, Wertpapiererträge)
- GKV-Simulation ohne Beitragsbemessungsgrenze-Kappung
- Keine steuerliche Behandlung der Kapitalentnahme im Auszahlung-Tab
