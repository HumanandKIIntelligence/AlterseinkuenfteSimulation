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

## Tests

Tests laufen im Docker-Container (alle Abhängigkeiten bereits installiert):

```bash
# Alle Tests
docker exec altereinkuenfte-app python -m pytest tests/ -v

# Einmalig pytest installieren (falls nötig)
docker exec altereinkuenfte-app pip install pytest -q
```

**Teststruktur (`tests/test_engine.py`):**

| Klasse | Inhalt |
|---|---|
| `TestEinkommensteuer` | §32a EStG Grundtarif: alle Zonen, Monotonie, Zonenübergänge |
| `TestSplitting` | §32a Abs. 5 EStG: Definition, Vorteil bei ungleichen Einkommen |
| `TestBesteuerungsanteil` | §22 EStG / JStG 2022: Stufen, 0,5%-Reform ab 2023, Cap bei 100 % |
| `TestKapitalwachstum` | Zinseszins-Formel: Nullrendite, Nullsparrate, kombiniert |
| `TestBerechneRente` | GKV/PKV, Kinder, Zusatzrente, Kapital, Netto-Konsistenz |
| `TestBerechneHaushalt` | Einzelperson, Paar, Splitting-Vorteil, Mieteinnahmen ohne KV |
| `TestAnnuitaet` | Annuitätsformel: Sonderfälle, Monotonie |
| `TestWertBeiStart` | Aufschubverzinsung: Kein Aufschub, 2 Jahre, Negative Deferral |
| `TestKapitalVsRente` | Kapitalverzehr: Nullrendite, Gesamtauszahlung, Verlauf |
| `TestNettoUeberHorizont` | KV-Korrektheit: bAV vs. PrivateRV, Freibetrag, BBG, Mieteinnahmen, PKV fix |
| `TestSimuliereSzenarien` | Szenarien-Reihenfolge und Vollständigkeit |
| `TestKonstanten` | Plausibilitätsprüfung der Gesetzeskonstanten |

---

## Architektur

### Datenfluß
```
Sidebar-Eingaben (app.py)
    → Profil-Dataclass + mieteinnahmen/mietsteigerung (engine.py)
    → berechne_rente() → RentenErgebnis
    → berechne_haushalt() → hh-Dict
    → Tab-Module (tabs/*.py)
```

### Modulstruktur

| Modul | Verantwortung |
|---|---|
| `app.py` | Sidebar-Rendering (Person 1+2, Mieteinnahmen, Speichern/Laden), Tab-Dispatch |
| `engine.py` | Alle Berechnungen (kein Streamlit); zentrale Formeln und Dataclasses |
| `session_io.py` | JSON-Persistenz: Profile, Produkte, Mieteinnahmen |
| `tabs/dashboard.py` | Kennzahlen, Wasserfall-Chart, Kaufkraft, Mieteinnahmen-Metric |
| `tabs/simulation.py` | Szenarien (pessimistisch/neutral/optimistisch), Kapitalverlauf |
| `tabs/auszahlung.py` | Kapital-Annuität vs. externe Rente, Break-Even, Laufzeitszenarien |
| `tabs/steuern.py` | Steuerberechnung inkl. Mieteinnahmen, Besteuerungsanteil-Chart, GKV/PKV |
| `tabs/haushalt.py` | Paarvergleich, Splitting-Vorteil, Szenario-Tabelle (nur bei Partner) |
| `tabs/vorsorge.py` | Vertragserfassung (bAV/RV/Riester/LV), Steueroptimierung über alle Kombinationen |

### engine.py – wichtige Funktionen

| Funktion | Beschreibung |
|---|---|
| `einkommensteuer(zvE)` | §32a EStG Grundtarif 2024 |
| `einkommensteuer_splitting(zvE_gesamt)` | §32a Abs. 5: 2× ESt(zvE/2) |
| `besteuerungsanteil(eintritt_jahr)` | §22 EStG / JStG 2022: ab 2023 +0,5 %/Jahr |
| `kapitalwachstum(kapital, sparrate, rendite_pa, jahre)` | Zinseszins mit monatlicher Sparrate |
| `berechne_rente(profil)` | Vollberechnung → `RentenErgebnis` |
| `berechne_haushalt(erg1, erg2, veranlagung, mieteinnahmen_monatlich)` | Haushaltseinkommen mit Splitting und Mieteinnahmen |
| `_netto_ueber_horizont(...)` | Jahressimulation für Steueroptimierung; KV-korrekt nach SGB V |
| `optimiere_auszahlungen(profil, ergebnis, produkte, horizont, mieteinnahmen, mietsteigerung)` | Brute-Force über alle Startjahr × Auszahlungsart-Kombinationen |

### Wichtige Konstanten (engine.py)

| Konstante | Wert | Quelle |
|---|---|---|
| `RENTENWERT_2024` | 39,32 € | DRV West, 01.07.2024 |
| `GRUNDFREIBETRAG_2024` | 11.604 € | §32a EStG 2024 |
| `BAV_FREIBETRAG_MONATLICH` | 187,25 € | §226 Abs. 2 SGB V 2024 |
| `BBG_KV_MONATLICH` | 5.175 € | BBG KV/PV 2024 |
| `AKTUELLES_JAHR` | 2025 | **Manuell aktualisieren bei Jahreswechsel** |

---

## KV/PV-Behandlung in der Vorsorge-Optimierung

Die `_netto_ueber_horizont`-Funktion implementiert die KVdR-Regeln korrekt:

- **bAV-Monatsrente**: KVdR-pflichtig. Freibetrag 187,25 €/Mon. (§226 Abs. 2 SGB V). Basis = `max(0, bAV_mono - Freibetrag)`.
- **bAV-Einmalauszahlung**: KV-Basis wird auf 10 Jahre verteilt (§229 Abs. 1 S. 3 SGB V: 1/120 pro Monat).
- **Private RV, Riester, LV**: Nicht KVdR-pflichtig. KV bleibt unverändert.
- **Mieteinnahmen**: Nicht KVdR-pflichtig. Nur steuerlich wirksam (§21 EStG, voll steuerpflichtig).
- **BBG**: KV-Basis gedeckelt bei `BBG_KV_MONATLICH` (5.175 €/Mon.).

## Steuerbehandlung Mieteinnahmen

- Eingabe: Nettomieteinnahmen nach abzugsfähigen Werbungskosten (der Nutzer trägt Kosten selbst ab)
- Steuer: voll zum zvE addiert (kein Besteuerungsanteil)
- KV: keine Pflicht
- Ehepaar Getrennt: 50/50 aufgeteilt; Ehepaar Zusammen: voller Betrag im Splitting-zvE

## Bekannte Vereinfachungen

- Kein Rentenabschlag bei Frühverrentung (0,3 %/Monat) – wirkt indirekt über weniger Beitragsjahre
- Private RV / LV werden steuerlich wie bAV behandelt (konservativ; korrekt wäre Ertragsanteil nach §22 Nr. 1 S. 3 EStG)
- `berechne_rente` wendet Besteuerungsanteil vereinfacht auch auf Zusatzrente an (korrekt wäre bAV voll steuerpflichtig)
- Keine Rentenerhöhung durch Aufschub-Bonus (Zugangsfaktor) berücksichtigt
