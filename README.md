# Alterseinkünfte-Simulation

Eine interaktive Web-App zur Simulation und Optimierung des Renteneinkommens. Berechnet Nettoeinkommen, Steuerlast und Krankenversicherungsbeiträge für eine oder zwei Personen auf Basis von Rentenpunkten, Vorsorgeprodukten und Mieteinnahmen.

## Features

- **Gesetzliche Rente & Beamtenpension** – DRV-Rentenpunkt-System oder direkte Pensionseingabe mit Versorgungsfreibetrag (§ 19 Abs. 2 EStG)
- **Vorsorgebausteine** – bAV, Riester, Rürup, Lebensversicherung, ETF-Depot, private Rentenversicherung; mit korrekter Steuer- und KV-Behandlung je Produkttyp
- **Einkommensteuer** – §32a EStG Grundtarif 2024 inkl. Solidaritätszuschlag und Kirchensteuer (8 %/9 %)
- **Ehegatten-Splitting** – §32a Abs. 5 EStG; Haushalt-Tab zeigt Splitting-Vorteil
- **Kranken- und Pflegeversicherung** – GKV (KVdR-Pflicht vs. freiwillig §240 SGB V) und PKV; korrekte bAV-Freibetragslogik und BBG-Deckelung
- **Szenarien** – Pessimistisch / Neutral / Optimistisch mit exakter Jahres-Simulation je Szenario
- **Entnahme-Optimierung** – Brute-Force über alle Startjahr × Auszahlungsart-Kombinationen; Kapitalverzehr-Kalkulator
- **Mieteinnahmen** – §21 EStG; jährliche Steigerung konfigurierbar
- **DUV / BUV** – Dienstunfähigkeits- und Berufsunfähigkeitsversicherung mit Ertragsanteil-Besteuerung
- **Kaufkraft-Anpassung** – konfigurierbarer Inflationsslider im Dashboard
- **JSON-Persistenz** – Speichern und Laden von Profilen (inkl. Rückwärtskompatibilität)

## App-Aufbau

| Tab | Inhalt |
|---|---|
| ⚙️ **Profil** | Personendaten, KV-Wahl, Kirchensteuer, DUV/BUV, Mieteinnahmen, Speichern/Laden |
| 📊 **Dashboard** | Kennzahlen, Wasserfall, Kaufkraft, Progressionszone-Ampel, Steuer & KV-Details |
| 👥 **Haushalt** | Nur bei Partner: Paarvergleich, Splitting-Vorteil, Szenario-Tabelle |
| 🔮 **Simulation** | Drei Szenarien, Sensitivitätsanalyse Renteneintrittsalter |
| 🏦 **Vorsorge-Bausteine** | Vertragserfassung, Steuer-Steckbrief, Optimierung |
| 💡 **Entnahme-Optimierung** | Optimale Auszahlungsstrategie, Jahresverlauf, Kapitalverzehr |
| 📖 **Dokumentation** | Berechnungsgrundlagen, Formeln, Haftungsausschluss |

## Technologie

- **Python 3.11** / **Streamlit** – UI und reaktiver Datenfluss
- **Plotly** – interaktive Charts
- **Docker** – empfohlene Laufzeitumgebung

## Starten

### Docker (empfohlen)

```bash
docker compose up --build
```

App erreichbar unter **http://localhost:8502**

Code-Änderungen sind sofort live (Volume-Mount). Rebuild nur bei Änderungen an `requirements.txt` oder `Dockerfile`.

```bash
docker compose down   # stoppen
```

### Lokal

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## Logs

```bash
docker compose logs -f
```

## Tests

```bash
# Im laufenden Docker-Container
docker exec altereinkuenfte-app python -m pytest tests/ -v
```

Alle Berechnungslogiken in `engine.py` sind durch Unit-Tests abgedeckt (121 Tests).

## Projektstruktur

```
app.py              – Profil-Tab, Sidebar, Tab-Dispatch
engine.py           – Alle Berechnungen (kein Streamlit)
session_io.py       – JSON-Persistenz
tabs/
  dashboard.py      – Kennzahlen, Wasserfall, Kaufkraft, Ampel
  simulation.py     – Szenarien, Sensitivitätsanalyse
  haushalt.py       – Paarvergleich, Splitting
  vorsorge.py       – Vertragserfassung, Steueroptimierung
  entnahme_opt.py   – Auszahlungsoptimierung, Jahresverlauf
  auszahlung.py     – Kapitalverzehr-Kalkulator
  steuern.py        – Steuer & KV-Detailansicht
  dokumentation.py  – Statische Dokumentationsseite
tests/
  test_engine.py    – Unit-Tests
data/               – Gespeicherte Profile (JSON)
```

## Gesetzliche Grundlagen (Stand 2024)

| Norm | Inhalt |
|---|---|
| §32a EStG | Einkommensteuertarif Grundtarif 2024 |
| §32a Abs. 5 EStG | Ehegatten-Splitting |
| §22 EStG / JStG 2022 | Besteuerungsanteil Rente (ab 2023: +0,5 %/Jahr) |
| §19 Abs. 2 EStG | Versorgungsfreibetrag Beamtenpension |
| §22 Nr. 1 S. 3a bb EStG | Ertragsanteil private RV / DUV / BUV |
| §51a EStG | Solidaritätszuschlag und Kirchensteuer |
| §226 Abs. 2 SGB V | bAV-Freibetrag KVdR (187,25 €/Mon.) |
| §229 SGB V | Versorgungsbezüge KVdR-pflichtig |
| §240 SGB V | Freiwillig GKV: alle Einkünfte beitragspflichtig |
| §77 SGB VI | Rentenabschlag 0,3 %/Monat Frühverrentung |

## Haftungsausschluss

Diese Simulation dient ausschließlich **Informations- und Planungszwecken**. Sie stellt keine Steuer-, Rechts- oder Anlageberatung dar. Für verbindliche Auskünfte: Deutsche Rentenversicherung, Steuerberater, Krankenkasse.
