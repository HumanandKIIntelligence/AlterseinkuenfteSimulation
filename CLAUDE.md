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
| `TestErtragsanteil` | §22 Nr. 1 S. 3a bb EStG: Tabellenwerte, Monotonie |
| `TestKapitalwachstum` | Zinseszins-Formel: Nullrendite, Nullsparrate, kombiniert |
| `TestBerechneRente` | GKV/PKV, Kinder, Zusatzrente, Kapital, Netto-Konsistenz |
| `TestBerechneHaushalt` | Einzelperson, Paar, Splitting-Vorteil, Mieteinnahmen ohne KV |
| `TestAnnuitaet` | Annuitätsformel: Sonderfälle, Monotonie |
| `TestWertBeiStart` | Aufschubverzinsung: Kein Aufschub, 2 Jahre, Negative Deferral |
| `TestKapitalVsRente` | Kapitalverzehr: Nullrendite, Gesamtauszahlung, Verlauf |
| `TestNettoUeberHorizont` | KV-Korrektheit: bAV vs. PrivateRV, Freibetrag, BBG, Mieteinnahmen, PKV fix |
| `TestSimuliereSzenarien` | Szenarien-Reihenfolge und Vollständigkeit |
| `TestKonstanten` | Plausibilitätsprüfung der Gesetzeskonstanten |
| `TestVersorgungsfreibetrag` | §19 Abs. 2 EStG: 2005/2024-Tabellenwerte, Monotonie, Null ab 2040 |
| `TestPensionaerBerechne` | Beamtenpension: VFB-Wirkung, KV ohne bAV-Freibetrag, PKV/Beihilfe |
| `TestDuvBuv` | DUV/BUV: Ertragsanteil im zvE, kein KVdR-Beitrag, Laufzeitende |
| `TestKVdRVsFreiwillig` | KVdR §229 vs. freiwillig §240: Miete/PrivateRV/bAV-Freibetrag/Mindest-BMG |
| `TestLaufendeKapitalertraege` | Laufende Kapitalerträge: Sparerpauschbetrag, Abgeltungsteuer, freiwillig-KV |
| `TestBerufsjahre` | Pre-retirement Simulation: Gehalt, Jahresanzahl, Src_Gehalt-Verlauf |

---

## Architektur

### Datenfluß
```
Profil-Tab (app.py) + Mieteinnahmen
    → Profil-Dataclass + mieteinnahmen/mietsteigerung (engine.py)
    → berechne_rente() → RentenErgebnis
    → berechne_haushalt() → hh-Dict
    → Tab-Module (tabs/*.py)
```

### App-Struktur (6 Tabs)

```
⚙️ Profil          – Personendaten (Person 1+2), Mieteinnahmen, KV, DUV/BUV
📊 Dashboard       – Kennzahlen, Wasserfall, Kaufkraft, Progressionszone-Ampel
                     └─ Expander: 🧾 Steuer- & KV-Details (steuern.render_section)
👥 Haushalt        – nur bei Partner: Paarvergleich, Splitting-Vorteil
🔮 Simulation      – Szenarien pessimistisch/neutral/optimistisch
🏦 Vorsorge-Bausteine – Vertragserfassung, Steuer-Steckbrief
💡 Entnahme-Optimierung – Auszahlungsstrategie, Jahresverlauf
                     └─ Expander: 💰 Kapitalverzehr-Kalkulator (auszahlung.render_section)
📖 Dokumentation   – Berechnungsgrundlagen, Haftungsausschluss
```

**Sidebar:** Reset (Neu anfangen), Laden aus gespeicherten Profilen, Speichern, Schnell-Metrics Nettorente P1/P2.

### Modulstruktur

| Modul | Verantwortung |
|---|---|
| `app.py` | Profil-Tab (Widgets), Sidebar (Reset/Laden/Speichern/Metrics), Tab-Dispatch; `_get(pfx, key, default)` als zentraler session_state-Accessor |
| `engine.py` | Alle Berechnungen (kein Streamlit); zentrale Formeln und Dataclasses |
| `session_io.py` | JSON-Persistenz: Profile, Produkte, Mieteinnahmen; `_PROFIL_LADE_DEFAULTS` für Backward-Compat |
| `tabs/dashboard.py` | Kennzahlen, Wasserfall, Kaufkraft, Progressionszone-Ampel, Steuer-Expander |
| `tabs/simulation.py` | Szenarien (pessimistisch/neutral/optimistisch), Kapitalverlauf |
| `tabs/auszahlung.py` | `render_section()`: Kapital-Annuität vs. externe Rente, Break-Even, Laufzeitszenarien |
| `tabs/steuern.py` | `render_section()`: Steuerberechnung inkl. Mieteinnahmen, Besteuerungsanteil-Chart, GKV/PKV |
| `tabs/haushalt.py` | Paarvergleich, Splitting-Vorteil, Szenario-Tabelle (nur bei Partner) |
| `tabs/vorsorge.py` | Vertragserfassung (bAV/Riester/Rürup/LV/ETF), Steueroptimierung |
| `tabs/entnahme_opt.py` | Steuer-Steckbrief, Auszahlungsoptimierung, Jahresverlauf, Kapitalverzehr-Expander |
| `tabs/dokumentation.py` | Statische Erläuterungsseite |

### engine.py – wichtige Funktionen

| Funktion | Beschreibung |
|---|---|
| `einkommensteuer(zvE)` | §32a EStG Grundtarif 2024 |
| `solidaritaetszuschlag(est)` | §51a EStG: Freigrenze 17.543 €, Gleitzone bis 33.912 €, dann 5,5 % |
| `einkommensteuer_splitting(zvE_gesamt)` | §32a Abs. 5: 2× ESt(zvE/2) |
| `besteuerungsanteil(eintritt_jahr)` | §22 EStG / JStG 2022: ab 2023 +0,5 %/Jahr |
| `versorgungsfreibetrag(ruhestand_jahr, pension_jahres)` | §19 Abs. 2 EStG: Freibetrag für Beamtenpensionen; 0 ab 2040 |
| `ertragsanteil(alter)` | §22 Nr. 1 S. 3a bb EStG: Tabellenwert als Dezimalzahl |
| `kapitalwachstum(kapital, sparrate, rendite_pa, jahre)` | Zinseszins mit monatlicher Sparrate |
| `berechne_rente(profil)` | Vollberechnung → `RentenErgebnis` |
| `berechne_haushalt(erg1, erg2, veranlagung, mieteinnahmen_monatlich)` | Haushaltseinkommen mit Splitting und Mieteinnahmen |
| `_netto_ueber_horizont(..., gehalt_monatlich)` | Jahressimulation; startet ab AKTUELLES_JAHR wenn gehalt_monatlich>0; Rentenanpassung p.a. eingebaut; KVdR vs. freiwillig GKV |
| `optimiere_auszahlungen(..., gehalt_monatlich)` | Brute-Force über alle Startjahr × Auszahlungsart-Kombinationen |

### Wichtige Konstanten (engine.py)

| Konstante | Wert | Quelle |
|---|---|---|
| `RENTENWERT_2024` | 39,32 € | DRV West, 01.07.2024 |
| `GRUNDFREIBETRAG_2024` | 11.604 € | §32a EStG 2024 |
| `BAV_FREIBETRAG_MONATLICH` | 187,25 € | §226 Abs. 2 SGB V 2024 |
| `BBG_KV_MONATLICH` | 5.175 € | BBG KV/PV 2024 |
| `MINDEST_BMG_FREIWILLIG_MONO` | 1.096,67 € | §240 Abs. 4 SGB V 2024 (1/90 Bezugsgröße) |
| `AKTUELLES_JAHR` | 2025 | **Manuell aktualisieren bei Jahreswechsel** |

---

## Beamtenpensionär-Support

`ist_pensionaer=True` aktiviert folgende abweichende Logik:

- **Einkommensteuer:** `versorgungsfreibetrag()` nach §19 Abs. 2 EStG (statt Besteuerungsanteil §22)
- **KV-Basis:** Voller Pensionsbetrag (§229 Abs. 1 Nr. 1 SGB V), kein bAV-Freibetrag
- **Beihilfe + PKV:** Eigener Versicherungsarten-Radio im Profil-Tab
- **DUV:** Dienstunfähigkeitsversicherung mit Ertragsanteil §22 Nr. 1 S. 3a bb; nicht KVdR-pflichtig
- **Rentenpunkte:** Werden auf 0 gesetzt; `rentenanpassung_pa = 0` (kein DRV-Mechanismus)
- **Profil-Eingabe:** Erwartete Bruttopension direkt als €/Mon. (kein Rentenpunkt-System)

## DUV / BUV

Beide Versicherungen sind **nicht KVdR-pflichtig** (private Versicherungsleistungen, §229 SGB V nicht anwendbar):

- **DUV** (nur `ist_pensionaer=True`): Ertragsanteil auf Basis des aktuellen Alters; läuft bis `duv_endjahr`
- **BUV** (nur `ist_pensionaer=False`): Gleiche Besteuerungslogik; `buv_zvE_j = buv_monatl × 12 × ertragsanteil(alter)`; KV-Basis wird um BUV-Betrag *reduziert*

---

## KV/PV-Behandlung in der Vorsorge-Optimierung

`_netto_ueber_horizont` implementiert drei KV-Pfade je nach Versicherungsstatus:

### PKV
Fixer Monatsbeitrag `profil.pkv_beitrag × 12`, unabhängig vom Einkommen.

### KVdR-Pflichtmitglied (`kvdr_pflicht=True`, §5 Abs. 1 Nr. 11 SGB V)
Nur §229-Einkünfte beitragspflichtig:
- **bAV-Monatsrente**: Freibetrag 187,25 €/Mon. (§226 Abs. 2 SGB V). Basis = `max(0, bAV_mono - Freibetrag)`.
- **bAV-Einmalauszahlung**: KV-Basis wird auf 10 Jahre verteilt (§229 Abs. 1 S. 3 SGB V: 1/120 pro Monat).
- **Gesetzliche Rente**: Vollständig beitragspflichtig.
- **Private RV, Riester, LV, Mieteinnahmen, Kapitalerträge**: NICHT beitragspflichtig.
- **BBG**: KV-Basis gedeckelt bei `BBG_KV_MONATLICH` (5.175 €/Mon.).

### Freiwillig GKV (`kvdr_pflicht=False`, §240 SGB V)
ALLE Einnahmen beitragspflichtig (ohne bAV-Freibetrag):
- Gesetzliche Rente + bAV (ohne Freibetrag) + Private RV + LV/ETF + Mieteinnahmen + laufende Kapitalerträge
- Mindestbemessungsgrundlage: `MINDEST_BMG_FREIWILLIG_MONO` = 1.096,67 €/Mon. (§240 Abs. 4 SGB V)
- BBG-Deckel: 5.175 €/Mon.
- UI: Checkbox „KVdR-Pflichtmitglied" im Profil-Tab bei GKV-Wahl.

### Arbeitsjahre (Simulation ab AKTUELLES_JAHR)
Wenn `gehalt_monatlich > 0` und `bereits_rentner=False`: Simulation startet ab `AKTUELLES_JAHR`.
KV in Arbeitsjahren = AN-Anteil auf Gehalt (begrenzt auf BBG).

## Steuerbehandlung Mieteinnahmen

- Eingabe: Nettomieteinnahmen nach abzugsfähigen Werbungskosten (der Nutzer trägt Kosten selbst ab)
- Steuer: voll zum zvE addiert (kein Besteuerungsanteil)
- KV: keine Pflicht
- Ehepaar Getrennt: 50/50 aufgeteilt; Ehepaar Zusammen: voller Betrag im Splitting-zvE

## Rentenanpassung im Jahresverlauf (`_netto_ueber_horizont`)

Die gesetzliche Rente wächst im Simulationshorizont mit `rentenanpassung_pa`:
```python
gesetzl_j = gesetzl_mono * 12 * (1 + profil.rentenanpassung_pa) ** _r_y
# _r_y = max(0, jahr - profil.eintritt_jahr)  ← immer relativ zum Renteneintritt
```
Für Pensionäre gilt `rentenanpassung_pa = 0.0` → konstante Pension. Für `bereits_rentner` startet die Simulation bei `rentenbeginn_jahr` (nicht `eintritt_jahr`).

## Berufsjahre-Simulation (`_netto_ueber_horizont`)

Wenn `gehalt_monatlich > 0` und nicht `bereits_rentner`:
- Simulation startet bei `AKTUELLES_JAHR` statt `eintritt_jahr`
- Arbeitsjahre (`jahr < eintritt_jahr`): Gehalt als zvE-Basis (100 % progressiv §19 EStG), AN-KV auf Gehalt
- Ab `eintritt_jahr`: gesetzliche Rente als zvE-Basis (mit `besteuerungsanteil`)
- `Src_Gehalt` in jahresdaten = Bruttogehalt in Arbeitsjahren, 0 in Rentenjahren
- Gesamtlänge jahresdaten = `max(0, eintritt_jahr - AKTUELLES_JAHR) + horizont_jahre`

## VorsorgeProdukt – neue Felder

- **`laufende_kapitalertraege_mono`** (float, default 0.0): Monatliche laufende Kapitalerträge (Zinsen, Dividenden, ETF-Ausschüttungen). Fließen in Abgeltungsteuer-Pool ein; bei freiwillig GKV zusätzlich KV-pflichtig. Eingabe im Vorsorge-Baustein Bearbeitungsdialog.

## Profil – neue Felder

- **`kvdr_pflicht`** (bool, default True): Ob Person KVdR-Pflichtmitglied ist. Steuert KV-Berechnungslogik in Rente. UI: Checkbox im Profil-Tab bei GKV.
- **`kirchensteuer`** (bool, default False): Ob Person kirchensteuerpflichtig ist. UI: Checkbox im Profil-Tab mit Rate-Radio (8 %/9 %).
- **`kirchensteuer_satz`** (float, default 0.09): Kirchensteuersatz (0.09 für alle Länder außer Bayern/Baden-Württemberg, 0.08 dort).

## RentenErgebnis – neue Felder

- **`kirchensteuer_monatlich`** (float, default 0.0): Monatliche Kirchensteuer; in `steuer_monatlich` bereits enthalten.

## Progressionszone-Ampel (dashboard.py)

`_steuerampel(zvE)` bestimmt Zone (steuerfrei/Zone1/Zone2/42%/45%), den analytischen Grenzsteuersatz, den Freiraum bis zur nächsten Zone und einen Handlungshinweis. Aufgerufen mit `ergebnis.zvE_jahres + mieteinnahmen * 12`. Zeigt 4 Spalten: Zone/Farbe, Grenzsteuersatz, Jahressteuer (ESt + Soli), Handlungshinweis.

## Szenario-Simulation (simulation.py, haushalt.py)

Szenarien verwenden seit dem Refactor **exakte `_netto_ueber_horizont`-Simulation** statt Näherungsformel `netto × (1+anp)^n`. Pro Szenario wird `dataclasses.replace(profil, rentenanpassung_pa=rpa, rendite_pa=kpa)` erstellt und `berechne_rente()` + `_netto_ueber_horizont()` aufgerufen. Ergebnis: Dict `{jahr: row}` je Szenario; Tabelle schlägt Betrachtungsjahr nach.

## Inflationsrate (dashboard.py)

Im Kaufkraft-Abschnitt des Dashboards gibt es ein konfigurierbares `number_input` für die Inflation p.a. (0–5 %, Default 2 %). Keys: `f"rc{_rc}_dash_inflation"` (Einzelperson) und `f"rc{_rc}_dash_inflation_hh"` (Haushalt/Zusammen).

## Widget-Key-Namensraum

Alle Slider/Radio-Keys in Tabs sind mit `f"rc{_rc}_"` präfixiert (`_rc = st.session_state.get("_rc", 0)`). app.py verwendet `_RC` (Modul-Level, einmalig aus session_state gelesen). Verhindert stale-state-Bugs nach Reset (Reset inkrementiert `_rc`).

## Bekannte Vereinfachungen

- Rentenabschlag bei Frühverrentung: 0,3 %/Monat vor Regelaltersgrenze 67 (§ 77 SGB VI) implementiert; feste RAG 67 für alle Jahrgänge (Übergangsregelung 1947–1963 nicht berücksichtigt)
- LV-Altvertrag (vor 2005): steuerfrei pauschal angenommen (5-J.-Beitragspflicht und 60%-Todesfallschutz werden nicht geprüft)
- Abgeltungsteuer auf LV/PrivateRV: vereinfacht 25 % (ohne Soli/KiSt auf Abgeltungsteuer)
- Kirchensteuer auf Abgeltungsteuer (Kapitalerträge): nicht berücksichtigt
- Private RV Einmalauszahlung: gleiche Regeln wie LV (§ 20 Abs. 1 Nr. 6 EStG); korrekt implementiert
- Private RV Monatsrente: Ertragsanteil § 22 Nr. 1 S. 3a bb EStG; korrekt implementiert
- Keine Rentenerhöhung durch Aufschub-Bonus (Zugangsfaktor) berücksichtigt
- Versorgungsfreibetrag Beamte: feste RAG-Tabelle; Übergangsregelungen für Jahrgänge vor 1964 nicht berücksichtigt
