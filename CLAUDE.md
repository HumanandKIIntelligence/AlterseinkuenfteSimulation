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
| `TestEinkommensteuerGFB` | `einkommensteuer(zvE, grundfreibetrag=...)`: GFB-Shift, Zonengrenzen, Monotonie |
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
| `TestAltersentlastungsbetrag` | §24a EStG: Tabellenwerte 2005/2010/2020/2025, Phase-A/B, Cap, bereits_genutzt, Integration berechne_rente |
| `TestPVKinderstaffelung` | §55 Abs. 3a SGB XI: 0–5 Kinder Beitragssätze, Monotonie, Integration berechne_rente |
| `TestEinzahlungenEffektiv` | VorsorgeProdukt.einzahlungen_effektiv(): Fallback, Akkumulation, Dynamik, Beitragsbefreiung, Monotonie, Riester-Grundzulage, Kinderzulage neu/alt/gemischt, Zulagen-Ende mit Renteneintritt |
| `TestKapitalanlagePool` | als_kapitalanlage: Pool-Initialisierung, Timing (Injektion vs. Verzehr), Src_Kapitalverzehr, Kap_Pool, Src_Einmal-Korrektur |
| `TestMultiPool` | Multi-Pool: Zwei Produkte mit eigenen Pools, per-Produkt-Rendite, Kap_Pool_{pid} / Src_Kap_{pid} Felder |
| `TestEtfAusschuettend` | etf_ausschuettend=True: keine Teilfreistellung, Abgeltungsteuer auf vollen Betrag |
| `TestProfilNeueFelder` | grundfreibetrag_wachstum_pa, kap_pool_rendite_pa: Defaults, GFB-Wachstum senkt Steuer, Pool-Rendite überschreibt Profil-Rendite |
| `TestOptimiererReferenzStrategien` | netto_alle_monatlich_spaet / einmal_spaet: Schlüssel, Gleichheit bei fix, Unterschied bei Range, optimal ≥ alle Referenzen |
| `TestP2RentenEintritt` | P2-Einkommen = 0 vor P2 eintritt_jahr; Brutto-Sprung bei P2-Eintritt; gleichzeitig ab Jahr 0 |
| `TestGetrenntSteuer` | Getrennt-Netto = P1_solo + P2_solo; nicht inflationiert durch fehlende P2-Steuer; Zusammen > Getrennt bei ungleichem Einkommen |
| `TestKapFehlbetrag` | Kein Fehlbetrag ohne Pool (0 statt Sonderausgabe); direkter Netto-Abzug bleibt; Fehlbetrag gesetzt wenn Pool unzureichend |
| `TestVorsorgeBeitraege` | jaehrl_einzahlung → Vorsorge_Beitraege pro Jahr; Netto-Differenz exakt; Beitragsbefreiung stoppt Abzug; einzel_einzahlung kein laufender Abzug |
| `TestGehaltFuerJahr` | `_gehalt_fuer_jahr()`: kein Treffer → Basis, Treffer → Periodengehalt, inklusive Grenzen, Nullgehalt (Elternzeit), mehrere Perioden |
| `TestBeamtenpensionBerechnung` | `_berechne_pension_beamte()`: Nullbezüge → 0, Versorgungssatz-Formel, Cap 71,75 %, Monotonie Dienstjahre/Bezüge |
| `TestPensionaerBerechneErweitert` | Beamtenpension in `berechne_rente()`: Fallback auf `aktuelles_brutto_monatlich`, § 14 BeamtVG wenn Bezüge angegeben, bereits-Pensionär nutzt Direkteingabe |
| `TestGehaltPeriodenGRV` | `gehalt_perioden` → EP in `berechne_rente()`: ohne Perioden = punkte_pro_jahr, Perioden senken EP, Elternzeit, BBG-Kappung, Pensionäre unberührt |
| `TestGehaltPeriodenSimulation` | `gehalt_perioden` → Src_Gehalt in `_netto_ueber_horizont()`: Periodengehalt in Arbeitsjahren, keine Wirkung nach Renteneintritt |

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
                     └─ Expander: ⚙️ Erweiterte Einstellungen (GFB-Wachstum, Pool-Rendite)
📊 Dashboard       – Kennzahlen, Wasserfall, Kaufkraft, Progressionszone-Ampel, Grundsicherungs-Hinweis
                     └─ Expander: 🔎 Was-wäre-wenn Steuerzone (interaktiv)
                     └─ Expander: 🧾 Steuer- & KV-Details (steuern.render_section)
                     └─ Expander: 📄 HTML-Export (Download-Button)
👥 Haushalt        – nur bei Partner: Paarvergleich, Splitting-Vorteil
                     └─ Witwen-/Witwerrente-Schätzung (§46 SGB VI)
🔮 Simulation      – Szenarien pessimistisch/neutral/optimistisch
🏦 Vorsorge-Bausteine – Vertragserfassung, Steuer-Steckbrief
💡 Entnahme-Optimierung – Auszahlungsstrategie, Jahresverlauf (real/nominal), Pool-Verlauf
                     └─ Expander: 🏠 Hypothek-Verwaltung (hypothek.render_section)
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
| `tabs/hypothek.py` | `render_section()`: Hypothek-Eingabe, Tilgungsplan, `get_ausgaben_plan()`, `_validate_hyp()` |
| `tabs/entnahme_opt.py` | Steuer-Steckbrief, Auszahlungsoptimierung, Jahresverlauf, Pool-Verlauf, Kapitalverzehr-Expander |
| `tabs/dokumentation.py` | Statische Erläuterungsseite |

### engine.py – wichtige Funktionen

| Funktion | Beschreibung |
|---|---|
| `regelaltersgrenze(geburtsjahr)` | §235 Abs. 2 SGB VI: RAG für Jahrgänge 1947–1963 aus `_RAG_TABLE`; ≤1946 → 65, ≥1964 → 67 |
| `einkommensteuer(zvE, grundfreibetrag=None)` | §32a EStG Grundtarif 2024; optionaler GFB-Override verschiebt alle Zonengrenzen um `delta = gfb - GRUNDFREIBETRAG_2024` |
| `solidaritaetszuschlag(est)` | §51a EStG: Freigrenze 17.543 €, Gleitzone bis 33.912 €, dann 5,5 % |
| `einkommensteuer_splitting(zvE_gesamt)` | §32a Abs. 5: 2× ESt(zvE/2) |
| `besteuerungsanteil(eintritt_jahr)` | §22 EStG / JStG 2022: ab 2023 +0,5 %/Jahr |
| `versorgungsfreibetrag(ruhestand_jahr, pension_jahres)` | §19 Abs. 2 EStG: Freibetrag für Beamtenpensionen; 0 ab 2040 |
| `altersentlastungsbetrag(geburtsjahr, qualifying_jahres, bereits_genutzt)` | §24a EStG: AEB für Personen ab 64 Jahren; Erstjahr = geburtsjahr+65 |
| `_pv_satz(kinder_anzahl)` | §55 Abs. 3a SGB XI: PV-Kinderstaffelung; returns (pv_voll, pv_halb) |
| `ertragsanteil(alter)` | §22 Nr. 1 S. 3a bb EStG: Tabellenwert als Dezimalzahl |
| `kapitalwachstum(kapital, sparrate, rendite_pa, jahre)` | Zinseszins mit monatlicher Sparrate |
| `_resolve_pool_rendite(prod, profil)` | Rendite-Priorität: `prod.kap_rendite_pa ≥ 0` → `profil.kap_pool_rendite_pa ≥ 0` → `profil.rendite_pa` |
| `_gehalt_fuer_jahr(profil, jahr, basis_gehalt)` | Gibt Periodengehalt zurück wenn `jahr` in einem Eintrag von `profil.gehalt_perioden` liegt, sonst `basis_gehalt` |
| `_berechne_pension_beamte(profil)` | § 14 BeamtVG: `min((bisherige_dj + jahre_bis_pension) × 1,79375 %, 71,75 %) × ruhegehalt_bezuege_mono`; gibt 0 wenn keine Bezüge angegeben |
| `berechne_rente(profil)` | Vollberechnung → `RentenErgebnis` (inkl. AEB, _pv_satz, Beamtenpension-Formel, Gehaltsperioden-EP) |
| `berechne_haushalt(erg1, erg2, veranlagung, mieteinnahmen_monatlich, profil1, profil2)` | Haushaltseinkommen mit Splitting, Mieteinnahmen und AEB auf Miete |
| `_netto_ueber_horizont(..., gehalt_monatlich, ausgaben_plan)` | Jahressimulation; Multi-Pool-Architektur; Rentenanpassung p.a.; KVdR vs. freiwillig GKV; Gehaltsperioden in Arbeitsjahren; optionaler Ausgabenplan (Hypothek) |
| `optimiere_auszahlungen(..., gehalt_monatlich)` | Brute-Force über alle Startjahr × Auszahlungsart-Kombinationen |

### Wichtige Konstanten (engine.py)

| Konstante | Wert | Quelle |
|---|---|---|
| `RENTENWERT_2024` | 39,32 € | DRV West, 01.07.2024 |
| `GRUNDFREIBETRAG_2024` | 11.604 € | §32a EStG 2024 |
| `BAV_FREIBETRAG_MONATLICH` | 187,25 € | §226 Abs. 2 SGB V 2024 |
| `BBG_KV_MONATLICH` | 5.175 € | BBG KV/PV 2024 |
| `MINDEST_BMG_FREIWILLIG_MONO` | 1.096,67 € | §240 Abs. 4 SGB V 2024 (1/90 Bezugsgröße) |
| `AKTUELLES_JAHR` | auto | `from datetime import date; AKTUELLES_JAHR = date.today().year` – kein manuelles Update nötig |
| `RIESTER_GRUNDZULAGE` | 175,0 € | §84 EStG |
| `RIESTER_KINDERZULAGE_NEU` | 300,0 € | §85 Abs. 1 S. 2 EStG (Kinder ab 01.01.2008) |
| `RIESTER_KINDERZULAGE_ALT` | 185,0 € | §85 Abs. 1 S. 1 EStG (Kinder vor 2008) |
| `GRUNDSICHERUNG_SCHWELLE` | 1.100,0 € | §41 SGB XII – indikativer Schwellenwert, kein Rechtsanspruch |
| `DURCHSCHNITTSENTGELT_2024` | 43.142,0 € | DRV – Rentenpunkt-Hochrechnung (EP = Brutto / DURCHSCHNITTSENTGELT) |
| `BBG_RV_MONATLICH` | 7.550,0 € | Beitragsbemessungsgrenze Rentenversicherung 2024 |
| `_VERSORGUNGSSATZ_PRO_JAHR` | 0,0179375 | § 14 Abs. 1 BeamtVG: 1,79375 % Ruhegehalt je Dienstjahr |
| `_VERSORGUNGSSATZ_MAX` | 0,7175 | § 14 Abs. 1 S. 4 BeamtVG: max. 71,75 % (= 40 Dienstjahre) |

---

## Beamtenpensionär-Support

`ist_pensionaer=True` aktiviert folgende abweichende Logik:

- **Einkommensteuer:** `versorgungsfreibetrag()` nach §19 Abs. 2 EStG (statt Besteuerungsanteil §22)
- **KV-Basis:** Voller Pensionsbetrag (§229 Abs. 1 Nr. 1 SGB V), kein bAV-Freibetrag
- **Beihilfe + PKV:** Eigener Versicherungsarten-Radio im Profil-Tab
- **DUV:** Dienstunfähigkeitsversicherung mit Ertragsanteil §22 Nr. 1 S. 3a bb; nicht KVdR-pflichtig
- **Rentenpunkte:** Werden auf 0 gesetzt; `rentenanpassung_pa` konfigurierbar per Slider (Default 0 %)
- **Profil-Eingabe (aktiver Beamter, `bereits_rentner=False`):** Pension wird nach §14 BeamtVG berechnet via `_berechne_pension_beamte()`:
  - Eingaben: `ruhegehalt_bezuege_mono` (ruhegehaltfähige Dienstbezüge €/Mon.) + `bisherige_dienstjahre`
  - Formel: `min((bisherige_dj + jahre_bis_pension) × 1,79375 %, 71,75 %) × ruhegehalt_bezuege_mono`
  - Fallback: wenn `ruhegehalt_bezuege_mono == 0`, wird `aktuelles_brutto_monatlich` als direkte Pensionseingabe genutzt (Abwärtskompatibilität)
  - UI: 3 berechnete Metriken (Dienstjahre gesamt, Versorgungssatz %, Bruttopension); collapsed Expander für Legacy-Direkteingabe
  - Gehaltsperioden: `gehalt_perioden`-Expander (Dienstbezüge-Perioden) für Zeiträume mit abweichenden Bezügen
- **Profil-Eingabe (bereits Pensionär, `bereits_rentner=True`):** Einfaches Direkteingabefeld für monatliche Bruttopension; keine §14-Berechnung

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
Für Pensionäre ist `rentenanpassung_pa` per Slider konfigurierbar (Default 0 %). Für `bereits_rentner` startet die Simulation bei `rentenbeginn_jahr` (nicht `eintritt_jahr`).

## Berufsjahre-Simulation (`_netto_ueber_horizont`)

Wenn `gehalt_monatlich > 0` und nicht `bereits_rentner`:
- Simulation startet bei `AKTUELLES_JAHR` statt `eintritt_jahr`
- Arbeitsjahre (`jahr < eintritt_jahr`): Gehalt als zvE-Basis (100 % progressiv §19 EStG), AN-KV auf Gehalt
- Ab `eintritt_jahr`: gesetzliche Rente als zvE-Basis (mit `besteuerungsanteil`)
- `Src_Gehalt` in jahresdaten = Bruttogehalt in Arbeitsjahren, 0 in Rentenjahren
- Gesamtlänge jahresdaten = `max(0, eintritt_jahr - AKTUELLES_JAHR) + horizont_jahre`

## Person 2 Renteneintritt (`_netto_ueber_horizont`)

P2-Einkommen (Rente/Pension + Produkte) erscheint erst ab `profil2.eintritt_jahr`:
```python
_p2_in_rente = profil2.bereits_rentner or (jahr >= profil2.eintritt_jahr)
_r2_y        = max(0, jahr - _p2_eintritt) if _p2_in_rente else 0
p2_fak       = (1 + p2_anp) ** _r2_y if _p2_in_rente else 0.0
```
Vor `eintritt_jahr`: `p2_fak = 0` → P2-Brutto, P2-zvE, P2-KV alle = 0. Getrennte Jahresoffsets für Rentenanpassung (P1 nutzt `_r_y`, P2 nutzt `_r2_y`).

## Getrenntveranlagung mit Partner (`_netto_ueber_horizont`)

Für `veranlagung="Getrennt"` mit `hat_partner=True` werden P1 und P2 **einzeln veranlagt** (§ 25 EStG):
- `_est_p1 = einkommensteuer(zvE_p1)`, `_est_p2 = einkommensteuer(p2_zvE_j)`
- `steuer_progr = _est_p1 + _est_p2`
- Soli je separat: `solidaritaetszuschlag(_est_p1) + solidaritaetszuschlag(_est_p2)`
- Invariante: `netto_Getrennt ≈ netto_P1_solo + netto_P2_solo`

## Vorsorge-Beiträge (`_netto_ueber_horizont`)

`jaehrl_einzahlung` reduziert das Netto während der Beitragsphase (`jahr < startjahr`):
```python
_beitrag = prod.jaehrl_einzahlung * (1.0 + prod.jaehrl_dynamik) ** max(0, jahr - AKTUELLES_JAHR)
if prod.beitragsbefreiung_jahr <= 0 or jahr < prod.beitragsbefreiung_jahr:
    vorsorge_beitraege_j += _beitrag
netto -= vorsorge_beitraege_j
```
`einzel_einzahlung` (bereits geleistete Einmalzahlung) erzeugt keinen laufenden Abzug – nur Kostenbasis für Steuerberechnung. Jahresdaten-Feld: `Vorsorge_Beitraege`.

## Ausgaben-Plan / Hypothek (`_netto_ueber_horizont`)

`ausgaben_plan: dict[int, float]` – optionaler Parameter; Keys = Jahre, Values = Jahresausgaben.

- **Kapitalanlage-Pool first:** Im jeweiligen Jahr wird zunächst aus dem Pool entnommen; Restbetrag reduziert `netto`.
- **`Kap_Fehlbetrag`**: Nur > 0 wenn ein `als_kapitalanlage`-Pool konfiguriert war und nicht ausgereicht hat. Ohne Pool = 0 (direkte Netto-Kürzung, kein Warnsignal).
- **Herkunft:** `tabs/hypothek.get_ausgaben_plan()` – erzeugt den Plan aus `raten_in_simulation` (laufende Raten) und/oder Restschuld-Behandlung.
- **`raten_in_simulation`** (bool, default False): Bezieht die Hypothek-Jahresraten ins Ausgaben-Plan ein, sodass sie im Jahresverlauf der Entnahme-Optimierung sichtbar sind.

## VorsorgeProdukt – Felder

- **`laufende_kapitalertraege_mono`** (float, default 0.0): Monatliche laufende Kapitalerträge (Zinsen, Dividenden, ETF-Ausschüttungen). Fließen in Abgeltungsteuer-Pool ein; bei freiwillig GKV zusätzlich KV-pflichtig.
- **`einzel_einzahlung`** (float, default 0.0): Summe bereits geleisteter Einmaleinzahlungen (Kostenbasis für §20 Abs. 1 Nr. 6 / §20 InvStG).
- **`jaehrl_einzahlung`** (float, default 0.0): Laufender Jahresbeitrag ab AKTUELLES_JAHR bis Startjahr.
- **`jaehrl_dynamik`** (float, default 0.0): Jährliche Beitragssteigerung (z.B. 0.02 = 2 %).
- **`beitragsbefreiung_jahr`** (int, default 0): Ab diesem Jahr zahlt die Versicherung (BU-Schutz); Beitragsbefreiungsleistungen = konservativ als weitere Einzahlungen.
- **`als_kapitalanlage`** (bool, default False): Einmalauszahlung → interner Kapitalanlage-Pool. Nettobetrag wird reinvestiert und als Annuität über den Planungshorizont verzehrt (Gewinne → Abgeltungsteuer).
- **`kap_rendite_pa`** (float, default -1.0): Produktspezifische Pool-Rendite. Überschreibt `profil.kap_pool_rendite_pa` und `profil.rendite_pa` wenn ≥ 0. Auflösung: `_resolve_pool_rendite(prod, profil)`.
- **`etf_ausschuettend`** (bool, default False): Nur für ETF-Produkte. Bei True: Teilfreistellung 0 % (kein Fonds-Privileg); volle Abgeltungsteuer auf Ausschüttungen und Gewinne.
- **`riester_zulage_nutzen`** (bool, default False): Grundzulage 175 €/Jahr + Kinderzulagen zur Kostenbasis addieren. Nur für aktive Einzahlungsjahre (`j < fruehestes_startjahr`).
- **`riester_kinder_zulage`** (int, default 0): Anzahl Kinder, geboren ab 01.01.2008 → 300 €/Kind/Jahr (§85 Abs. 1 S. 2 EStG).
- **`riester_kinder_zulage_alt`** (int, default 0): Anzahl Kinder, geboren vor 01.01.2008 → 185 €/Kind/Jahr (§85 Abs. 1 S. 1 EStG).
- **`bav_ag_zuschuss`** (bool, default False): AG-Pflichtzuschuss 15 % (§1a Abs. 1a BetrAVG ab 2022). Effektive Einzahlung = `beitrag × 1,15`. Nur für aktive Einzahlungsjahre.

`einzahlungen_effektiv(startjahr: int) -> float`: Methode auf VorsorgeProdukt. Berechnet Gesamteinzahlungen bis `startjahr`. Fallback auf `einzahlungen_gesamt` wenn `jaehrl_einzahlung==0`. Riester-Zulagen und bAV-AG-Zuschuss enden bei `fruehestes_startjahr` (Renteneintrittsjahr).

## Multi-Pool-Architektur (`_netto_ueber_horizont`)

Jedes `als_kapitalanlage`-Produkt hat seinen eigenen Pool:

```python
_kap_pools: dict[str, float]  # pid → aktueller Poolwert
_kap_bases: dict[str, float]  # pid → Kostenbasis
_ka_prods:  list[VorsorgeProdukt]  # alle als_kapitalanlage-Produkte
```

- **Injektion (Startjahr des Produkts):** Nettobetrag nach Steuer wird in produktspezifischen Pool überführt; aus `netto` subtrahiert.
- **Entnahme (Folgejahre):** Annuität über verbleibende Jahre; Gewinnanteil `(pool - basis) / pool` → Abgeltungsteuer.
- **Rendite-Auflösung:** `_resolve_pool_rendite(prod, profil)` – Priorität: `prod.kap_rendite_pa ≥ 0` → `profil.kap_pool_rendite_pa ≥ 0` → `profil.rendite_pa`.
- **Jahresdaten-Felder:** `Src_Kap_{pid}` (Entnahme p.a.), `Kap_Pool_{pid}` (Poolwert am Jahresende) – je Pool ein eigenes Feld.
- **Rückwärtskompatibilität:** `Src_Kapitalverzehr` und `Kap_Pool` (aggregiert) bleiben erhalten.
- **`Kap_Injektion`** (int): Netto-Injektionsbetrag ins Kapitalanlage-Pool im Injektionsjahr; für Annotations in `entnahme_opt.py`.
- **`LHK`** (int): Jährliche Lebenshaltungskosten (`profil.lebenshaltungskosten_monatlich × 12`); bereits im Netto abgezogen.
- **`Vorsorge_Beitraege`** (int): Summe laufender Jahresbeiträge (`jaehrl_einzahlung`) aller Produkte in Beitragsphase (`jahr < startjahr`); im Netto abgezogen. Null wenn kein laufender Beitrag.
- **`Kap_Fehlbetrag`** (int): Pool-Warnsignal – nur > 0 wenn `als_kapitalanlage`-Pool konfiguriert war aber nicht ausgereicht hat. Ohne Pool = 0 (Sonderausgabe trotzdem direkt von Netto abgezogen).
- **Bekannte Vereinfachung:** Pool-Renditegewinne werden nochmals mit Abgeltungsteuer belastet (konservativ).

## Optimizer – Referenzstrategien

`optimiere_auszahlungen()` gibt neben `netto_alle_monatlich` / `netto_alle_einmal` (frühestmöglich) neu auch aus:
- **`netto_alle_monatlich_spaet`**: alle Produkte monatlich ab `spaetestes_startjahr`
- **`netto_alle_einmal_spaet`**: alle Produkte einmal ab `spaetestes_startjahr`

Im Strategievergleich-Balkendiagramm werden 5 Säulen angezeigt.

## Profil – Felder

- **`kvdr_pflicht`** (bool, default True): Ob Person KVdR-Pflichtmitglied ist. Steuert KV-Berechnungslogik in Rente. UI: Checkbox im Profil-Tab bei GKV.
- **`kirchensteuer`** (bool, default False): Ob Person kirchensteuerpflichtig ist. UI: Checkbox im Profil-Tab mit Rate-Radio (8 %/9 %).
- **`kirchensteuer_satz`** (float, default 0.09): Kirchensteuersatz (0.09 für alle Länder außer Bayern/Baden-Württemberg, 0.08 dort).
- **`kinder_anzahl`** (int, default 1): Anzahl Kinder für PV-Kinderstaffelung §55 Abs. 3a SGB XI. Nur relevant wenn `kinder=True`. UI: Zahlen-Input im Profil-Tab bei GKV-Wahl + Kinder-Checkbox.
- **`grundfreibetrag_wachstum_pa`** (float, default 0.0): Jährliches GFB-Wachstum p.a. (z.B. 0.01 = 1 %). Pro Simulationsjahr: `gfb = GRUNDFREIBETRAG_2024 × (1+wachstum)^y`. UI: Slider im "Erweiterte Einstellungen"-Expander.
- **`kap_pool_rendite_pa`** (float, default -1.0): Profilweite Default-Pool-Rendite für alle `als_kapitalanlage`-Produkte. Wird von `prod.kap_rendite_pa` überschrieben wenn ≥ 0. UI: Checkbox + Slider im "Erweiterte Einstellungen"-Expander.
- **`lebenshaltungskosten_monatlich`** (float, default 0.0): Monatliche Fixausgaben (Lebenshaltungskosten). Wird jährlich in `_netto_ueber_horizont()` vom Netto abgezogen (`LHK`-Feld in Jahresdaten). UI: number_input im "Erweiterte Einstellungen"-Expander.
- **`gehalt_perioden`** (list, default []): Zeiträume mit abweichendem Gehalt/Bezügen. Jeder Eintrag: `{"start_jahr": int, "end_jahr": int, "gehalt_monatlich": float}`. Bei GRV: beeinflusst EP-Berechnung und Simulationsgehalt. Bei Beamten: Dienstbezüge-Perioden. UI: `st.data_editor` im Expander "📅 Gehaltsänderungen (Perioden)"; stabiler Key `f"{pfx}_gehalt_perioden"`.
- **`ruhegehalt_bezuege_mono`** (float, default 0.0): Ruhegehaltfähige Dienstbezüge in €/Mon. (nur aktive Beamte, `ist_pensionaer=True` und `bereits_rentner=False`). Basis für §14-BeamtVG-Formel. 0 → Fallback auf `aktuelles_brutto_monatlich`.
- **`bisherige_dienstjahre`** (int, default 0): Bereits abgeleistete Dienstjahre (aktive Beamte). Fließt in `_berechne_pension_beamte()` als Summand ein: `bisherige_dj + jahre_bis_pension`.

## RentenErgebnis – Felder

- **`kirchensteuer_monatlich`** (float, default 0.0): Monatliche Kirchensteuer; in `steuer_monatlich` bereits enthalten.
- **`altersentlastungsbetrag_jahres`** (float, default 0.0): Genutzter AEB §24a EStG; für `berechne_haushalt()` als Cap-Basis bei Mieteinnahmen.

## Altersentlastungsbetrag § 24a EStG

`altersentlastungsbetrag(geburtsjahr, qualifying_jahres, bereits_genutzt=0.0)`:
- Erstjahr = `geburtsjahr + 65`; ab 2040: 0
- Qualifizierend: PrivRV-Ertragsanteil (§22 Nr.1 S.3a bb), Riester (§22 Nr.5), BUV/DUV, Mieteinnahmen (§21), Arbeitslohn (§19, kein Versorgungsbezug)
- Nicht qualifizierend: GRV/Rürup (§22 Nr.1 S.3a aa), bAV (§22 Nr.5 / §19 Abs.2), Beamtenpension (§19 Abs.2)
- In `berechne_rente()` und `_netto_ueber_horizont()` angewendet; in `berechne_haushalt()` für Mieteinnahmen mit `bereits_genutzt`-Cap

## PV-Kinderstaffelung § 55 Abs. 3a SGB XI

`_pv_satz(kinder_anzahl: int) -> tuple[float, float]` (pv_voll, pv_halb):
- 0 Kinder: 4,0 % / 2,3 % (Kinderlosenzuschlag 0,6 % trägt Versicherter allein)
- 1 Kind: 3,4 % / 1,7 % (Basisrate)
- Ab 2. Kind: −0,25 % je Kind (max. 5 Kinder → −1,0 %); z.B. 5 Kinder: 2,4 % / 0,7 %
- Ersetzt überall die früheren `0.017 if p.kinder else 0.023` Inline-Berechnungen

## Progressionszone-Ampel (dashboard.py)

`_steuerampel(zvE)` bestimmt Zone (steuerfrei/Zone1/Zone2/42%/45%), den analytischen Grenzsteuersatz, den Freiraum bis zur nächsten Zone und einen Handlungshinweis. Aufgerufen mit `ergebnis.zvE_jahres + mieteinnahmen * 12`. Zeigt 4 Spalten: Zone/Farbe, Grenzsteuersatz, Jahressteuer (ESt + Soli), Handlungshinweis.

## Szenario-Simulation (simulation.py, haushalt.py)

Szenarien verwenden seit dem Refactor **exakte `_netto_ueber_horizont`-Simulation** statt Näherungsformel `netto × (1+anp)^n`. Pro Szenario wird `dataclasses.replace(profil, rentenanpassung_pa=rpa, rendite_pa=kpa)` erstellt und `berechne_rente()` + `_netto_ueber_horizont()` aufgerufen. Ergebnis: Dict `{jahr: row}` je Szenario; Tabelle schlägt Betrachtungsjahr nach.

## GFB-Wachstum (engine.py, app.py)

`einkommensteuer(zvE, grundfreibetrag=None)`: Optionaler GFB-Parameter; alle Zonengrenzen verschieben sich um `delta = gfb - GRUNDFREIBETRAG_2024`.

Intercept-Verschiebungen (Zone 3 und 4 ändern sich durch das delta):
- Zone 3 Startbetrag: `9972.98 + 0.42 * delta`
- Zone 4 Startbetrag: `18307.73 + 0.45 * delta`

`_netto_ueber_horizont` berechnet pro Jahr: `gfb_y = GRUNDFREIBETRAG_2024 * (1 + grundfreibetrag_wachstum_pa) ** y` und übergibt diesen an `einkommensteuer()`.

## Inflationsrate (dashboard.py)

Im Kaufkraft-Abschnitt des Dashboards gibt es ein konfigurierbares `number_input` für die Inflation p.a. (0–5 %, Default 2 %). Keys: `f"rc{_rc}_dash_inflation"` (Einzelperson) und `f"rc{_rc}_dash_inflation_hh"` (Haushalt/Zusammen).

## Grundsicherungs-Hinweis (dashboard.py)

`GRUNDSICHERUNG_SCHWELLE = 1_100.0` (§41 SGB XII). Wenn projizierte Nettorente für das gewählte Betrachtungsjahr unter diesem Schwellenwert liegt, erscheint eine `st.warning()` mit Hinweis auf möglichen Grundsicherungsanspruch. Im Zusammen-Modus für beide Personen separat geprüft.

## Was-wäre-wenn Steuerzone (dashboard.py)

Expander "🔎 Was-wäre-wenn: Steuerzone" nach `_steuerampel()` in Einzelperson-Ansicht. Slider 0–50.000 € für Zusatzeinkommen. Zeigt zvE vorher/nachher, Jahressteuer vorher, Mehrsteuer absolut + Grenzbelastung in %, und eine zweite Steuerampel für das neue zvE. Key: `f"rc{_rc}_dash_ww_extra"`.

## HTML-Export (dashboard.py)

Expander "📄 Zusammenfassung exportieren" am Ende der Einzelperson-Ansicht. `st.download_button` mit HTML-Blob aus f-string. Enthält Kennzahlen, Profildaten, Disclaimer. Hinweis auf Drucken als PDF via Strg+P.

## Witwen-/Witwerrente (haushalt.py)

Abschnitt am Ende des Haushalt-Tabs. Schätzung: 55 % der gesetzl. Bruttorente (§46 Abs. 2 SGB VI, großes Witwengeld). Einkommensanrechnung nach §97 SGB VI: Freibetrag 26.400 €/Jahr; 40 % des übersteigenden Betrags werden monatlich angerechnet. Zwei Expander: "Tod von Person 1" / "Tod von Person 2". Vereinfachung: kein kleines Witwengeld, kein Bestandsschutz, keine Kinderzuschläge.

## Reale Werte / Inflationsbereinigung (entnahme_opt.py)

Checkbox "Reale Werte (inflationsbereinigt)" + `number_input` "Inflation p.a. %" vor dem Jahresverlauf-Chart. Bei Aktivierung werden alle numerischen Jahresdaten-Spalten mit `1 / (1+inf)^(j - start_j)` multipliziert. Keys: `f"rc{_rc}_eo_real"`, `f"rc{_rc}_eo_inflation"`.

## Zwei-Strategie-Vergleich (entnahme_opt.py)

Expander "📊 Zwei-Strategie-Vergleich" nach dem Jahresverlauf-Chart. Selectbox für Vergleichsstrategie (Monatlich/Einmal × frühest/spätestmöglich). Führt `_netto_ueber_horizont()` direkt mit fixen Entscheidungen aus (ohne Brute-Force). Zeigt zwei Netto-Linien (Optimal grün / Vergleich blau gestrichelt) und Differenzsumme. Berücksichtigt real-Werte-Toggle.

## Widget-Key-Namensraum

Alle Slider/Radio-Keys in Tabs sind mit `f"rc{_rc}_"` präfixiert (`_rc = st.session_state.get("_rc", 0)`). app.py verwendet `_RC` (Modul-Level, einmalig aus session_state gelesen). Verhindert stale-state-Bugs nach Reset (Reset inkrementiert `_rc`).

## Renteneintrittsalter-Validierung (app.py)

Nicht-Pensionäre und nicht bereits-Rentner erhalten eine Warnung wenn `renteneintrittsalter < 63`. Pensionäre können kein Renteneintrittsalter setzen (Pension gilt ab festem Ruhestandsdatum).

## tabs/hypothek.py

`render_section()`: Eingabeformular für Hypothek mit Validierung via `_validate_hyp(startjahr, endjahr, betrag, jaehrl_rate) -> list[str]`.

`get_ausgaben_plan() -> dict[int, float]`: Erzeugt den Ausgabenplan aus session_state. Gibt leeres Dict zurück wenn Hypothek nicht aktiv.

`get_restschuld_end() -> float`: Restschuld am Ende des Tilgungsplans.

`get_hyp_schedule() -> list[dict]`: Tilgungsplan als Jahresliste.

Validierungsregeln: `endjahr > startjahr`, `betrag > 0`, `rate > 0`, `rate <= betrag`.

## Bekannte Vereinfachungen

- Rentenabschlag bei Frühverrentung: 0,3 %/Monat vor individueller RAG (§ 77 SGB VI); `regelaltersgrenze(geburtsjahr)` mit §235-Übergangstabelle für Jahrgänge 1947–1963
- LV-Altvertrag (vor 2005): steuerfrei pauschal angenommen (5-J.-Beitragspflicht und 60%-Todesfallschutz werden nicht geprüft)
- Abgeltungsteuer auf LV/PrivateRV: vereinfacht 25 % (ohne Soli/KiSt auf Abgeltungsteuer)
- Kirchensteuer auf Abgeltungsteuer (Kapitalerträge): nicht berücksichtigt
- Private RV Einmalauszahlung: gleiche Regeln wie LV (§ 20 Abs. 1 Nr. 6 EStG); korrekt implementiert
- Private RV Monatsrente: Ertragsanteil § 22 Nr. 1 S. 3a bb EStG; korrekt implementiert
- Keine Rentenerhöhung durch Aufschub-Bonus (Zugangsfaktor) berücksichtigt
- Versorgungsfreibetrag Beamte: feste RAG-Tabelle; Übergangsregelungen für Jahrgänge vor 1964 nicht berücksichtigt
- ETF ausschüttend: Teilfreistellung 0 %; thesaurierend (Default): Teilfreistellung 30 % (§ 20 InvStG)
- Pool-Renditegewinne bei LV/PrivateRente als_kapitalanlage: nochmals Abgeltungsteuer (konservativ)
