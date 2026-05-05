# Alterseinkünfte-Simulation

Eine interaktive Web-App zur Simulation und Optimierung des Renteneinkommens. Berechnet Nettoeinkommen, Steuerlast und Krankenversicherungsbeiträge für eine oder zwei Personen auf Basis von Rentenpunkten, Vorsorgeprodukten und Mieteinnahmen.

## Features

- **Gesetzliche Rente** – DRV-Rentenpunkt-System; EP-Jahresberechnung mit Gehaltsperioden (Elternzeit, Teilzeit, Sabbatjahr)
- **Beamtenpension §14 BeamtVG** – Versorgungssatz-Berechnung aus Dienstbezügen + Dienstjahren (`min(dienstjahre × 1,79375 %, 71,75 %) × Bezüge`); Versorgungsfreibetrag §19 Abs. 2 EStG; für Pensionäre: Direkteingabe
- **Vorsorgebausteine** – bAV, Riester, Rürup, Lebensversicherung, ETF-Depot (thesaurierend/ausschüttend), private Rentenversicherung; mit korrekter Steuer- und KV-Behandlung je Produkttyp
- **Einkommensteuer** – §32a EStG Grundtarif 2024 inkl. Solidaritätszuschlag und Kirchensteuer (8 %/9 %); optionales GFB-Wachstum verschiebt alle Steuerzonen dynamisch
- **Altersentlastungsbetrag** – §24a EStG; automatisch für Personen ab 65, qualifizierend: PrivRV-Ertragsanteil, Riester, BUV/DUV, Mieteinnahmen, Arbeitslohn (nicht GRV/Rürup/bAV)
- **Ehegatten-Splitting** – §32a Abs. 5 EStG; Haushalt-Tab zeigt Splitting-Vorteil
- **Kranken- und Pflegeversicherung** – GKV (KVdR-Pflicht vs. freiwillig §240 SGB V) und PKV; korrekte bAV-Freibetragslogik, BBG-Deckelung und PV-Kinderstaffelung (§55 Abs. 3a SGB XI)
- **PV-Kinderstaffelung** – §55 Abs. 3a SGB XI; 0–5 Kinder: Abschlag von −0,25 % je Kind ab dem 2. Kind (max. −1,0 %)
- **Szenarien** – Pessimistisch / Neutral / Optimistisch mit exakter Jahres-Simulation je Szenario
- **Entnahme-Optimierung** – Suche über alle Startjahr × Auszahlungsart-Kombinationen; 5-Säulen-Strategievergleich (frühest/spätestens × monatlich/einmal, optimal); Kapitalverzehr-Kalkulator
- **Multi-Pool-Kapitalanlage** – Jede Einmalauszahlung wahlweise als eigener reinvestierter Kapitalanlage-Pool; produktspezifische Rendite; Annuitätenverzehr mit Abgeltungsteuer auf Gewinne; separater Pool-Verlauf-Chart
- **Hypothek-Verwaltung** – Tilgungsplan mit Start-/Endmonat-Proration, Restschuld-Behandlung (als Kapitalanlage oder Ratenkredit); optionale Einbindung laufender Raten in die Simulation
- **Echtzeit-Selektionspropagation** – Änderungen an Auszahlungsart/-startjahr in der Entnahme-Optimierung werden sofort in Dashboard, Haushalt, Simulation und Vorsorge-Bausteine übernommen
- **Dynamische Einzahlungsfelder** – je Vorsorgebaustein: Einmaleinzahlungen, jährl. Beitrag, Dynamik %, Beitragsbefreiungsjahr; auto-berechnete Kostenbasis bis Startjahr
- **Mieteinnahmen** – §21 EStG; jährliche Steigerung konfigurierbar
- **DUV / BUV** – Dienstunfähigkeits- und Berufsunfähigkeitsversicherung mit Ertragsanteil-Besteuerung
- **Kaufkraft-Anpassung** – konfigurierbarer Inflationsslider im Dashboard
- **JSON-Persistenz** – Speichern und Laden von Profilen (inkl. Rückwärtskompatibilität)

## App-Aufbau

| Tab | Inhalt |
|---|---|
| ⚙️ **Profil** | Personendaten, KV-Wahl, Kirchensteuer, DUV/BUV, Mieteinnahmen, Erweiterte Einstellungen (GFB-Wachstum, Pool-Rendite) |
| 📊 **Dashboard** | Kennzahlen, Wasserfall, Kaufkraft, Progressionszone-Ampel, Steuer & KV-Details |
| 👥 **Haushalt** | Nur bei Partner: Paarvergleich, Splitting-Vorteil, Szenario-Tabelle |
| 🔮 **Simulation** | Drei Szenarien, Sensitivitätsanalyse Renteneintrittsalter |
| 🏦 **Vorsorge-Bausteine** | Vertragserfassung, Steuer-Steckbrief, Optimierung |
| 💡 **Entnahme-Optimierung** | Optimale Auszahlungsstrategie, Jahresverlauf, Pool-Verlauf, Hypothek-Verwaltung, Kapitalverzehr |
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

Alle Berechnungslogiken in `engine.py` sind durch Unit-Tests abgedeckt (348 Tests).

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
  hypothek.py       – Hypothek-Verwaltung, Tilgungsplan, Ausgabenplan
  entnahme_opt.py   – Auszahlungsoptimierung, Jahresverlauf, Pool-Verlauf
  utils.py          – Gemeinsame Hilfsfunktionen (_actual_startjahr, _actual_anteil)
  auszahlung.py     – Kapitalverzehr-Kalkulator
  steuern.py        – Steuer & KV-Detailansicht
  dokumentation.py  – Statische Dokumentationsseite
tests/
  test_engine.py    – Unit-Tests (348 Tests)
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
| §24a EStG | Altersentlastungsbetrag für Personen ab 64 Jahren |
| §51a EStG | Solidaritätszuschlag und Kirchensteuer |
| §20 InvStG | Teilfreistellung ETF (30 % thesaurierend; 0 % ausschüttend) |
| §226 Abs. 2 SGB V | bAV-Freibetrag KVdR (187,25 €/Mon.) |
| §229 SGB V | Versorgungsbezüge KVdR-pflichtig |
| §240 SGB V | Freiwillig GKV: alle Einkünfte beitragspflichtig |
| §55 Abs. 3a SGB XI | PV-Kinderstaffelung: −0,25 % je Kind ab dem 2. Kind |
| §77 SGB VI | Rentenabschlag 0,3 %/Monat Frühverrentung |
| §235 SGB VI | Regelaltersgrenze Jahrgänge 1947–1963 (Übergangsregelung) |
| §14 BeamtVG | Versorgungssatz Beamtenpension: 1,79375 % je Dienstjahr, max. 71,75 % |

## Haftungsausschluss

Diese Simulation dient ausschließlich **Informations- und Planungszwecken**. Sie stellt keine Steuer-, Rechts- oder Anlageberatung dar. Für verbindliche Auskünfte: Deutsche Rentenversicherung, Steuerberater, Krankenkasse.
