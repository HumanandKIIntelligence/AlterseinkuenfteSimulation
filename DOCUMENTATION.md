# Alterseinkünfte-Simulation – Dokumentation

Umfassende Beschreibung aller Funktionen, Berechnungslogiken und Eingabefelder.

---

## Inhaltsverzeichnis

1. [Profil-Tab](#1-profil-tab)
2. [Dashboard](#2-dashboard)
3. [Haushalt-Tab](#3-haushalt-tab)
4. [Simulation-Tab](#4-simulation-tab)
5. [Vorsorge-Bausteine](#5-vorsorge-bausteine)
6. [Entnahme-Optimierung](#6-entnahme-optimierung)
7. [Steuer- und KV-Berechnung](#7-steuer--und-kv-berechnung)
8. [Gesetzliche Grundlagen](#8-gesetzliche-grundlagen)
9. [Bekannte Vereinfachungen](#9-bekannte-vereinfachungen)
10. [Haftungsausschluss](#10-haftungsausschluss)

---

## 1. Profil-Tab

### Personendaten

| Feld | Beschreibung |
|---|---|
| Geburtsjahr | Grundlage für Altersentlastungsbetrag (§24a EStG), Ertragsanteil (§22 EStG), Progressionsstufen |
| Renteneintrittsalter | Zieldatum für Rentenbeginn; Frührentenabschlag ab < 67 (0,3 %/Monat); Warnung bei < 63 |
| Rentenpunkte | Entgeltpunkte der DRV; Monatsrente = Punkte × Rentenwert (39,32 €/Punkt, West, 01.07.2024) |
| Beamtenpension (aktiv) | §14 BeamtVG: `min((bisherige_dj + jahre_bis_pension) × 1,79375 %, 71,75 %) × Dienstbezüge`. Eingabe: ruhegehaltfähige Dienstbezüge €/Mon. + bisherige Dienstjahre. Drei berechnete Kennzahlen (Dienstjahre gesamt, Versorgungssatz %, Bruttopension). Fallback auf direkte Pensionseingabe wenn keine Bezüge angegeben. |
| Beamtenpension (bereits Pensionär) | Direkteingabe der monatlichen Bruttopension; keine §14-Berechnung |
| Gehaltsperioden | Zeiträume mit abweichendem Gehalt/Bezügen (Elternzeit, Teilzeit, Sabbatjahr). Bei GRV: beeinflusst EP-Jahresberechnung und Simulationsgehalt. Bei Beamten: Dienstbezüge-Perioden. |
| Rentenanpassung p.a. | Jährliche Steigerungsrate der gesetzlichen Rente (GRV-Default 2 %; Pensionäre separat konfigurierbar, Default 0 %) |

### Krankenversicherung

| Option | Beschreibung |
|---|---|
| GKV – KVdR | Gesetzliche KV als Pflichtmitglied der KVdR (§5 Abs. 1 Nr. 11 SGB V): nur §229-Einkünfte beitragspflichtig |
| GKV – freiwillig | Gesetzliche KV als freiwilliges Mitglied (§240 SGB V): alle Einkünfte beitragspflichtig, inkl. Mindest-BMG |
| PKV | Private KV; fixer Monatsbeitrag unabhängig vom Einkommen |
| Beihilfe + PKV | Nur für Beamtenpensionäre; halber PKV-Beitrag, Rest über Beihilfe |

**Kinderstaffelung PV:** Bei GKV mit aktivierter Kinder-Checkbox kann die Anzahl der Kinder eingegeben werden. Bei 0 Kindern: voller Kinderlosenzuschlag (4,0 % PV). Ab 2. Kind: −0,25 % je Kind (max. −1,0 % bei 5 Kindern).

### Kirchensteuer

Optional aktivierbar. Rate: 9 % (alle Bundesländer außer Bayern/Baden-Württemberg) oder 8 %. Die Kirchensteuer wird auf Basis der Einkommensteuer berechnet und ist in `steuer_monatlich` bereits enthalten.

### DUV / BUV

| Feld | Beschreibung |
|---|---|
| DUV (Pensionäre) | Dienstunfähigkeitsversicherung; Ertragsanteil nach §22 Nr. 1 S. 3a bb EStG; läuft bis Endjahr |
| BUV (Angestellte) | Berufsunfähigkeitsversicherung; gleiche Besteuerungslogik; KV-Basis wird um BUV-Betrag reduziert |

Beide Versicherungen sind **nicht KVdR-pflichtig** (§229 SGB V nicht anwendbar).

### Mieteinnahmen

Eingabe als monatliche **Nettomieteinnahmen nach Werbungskosten** (Zinsen, AfA, Verwaltung etc. werden vom Nutzer selbst abgezogen). Die Nettomieteinnahmen werden voll zum zvE addiert (§21 EStG). Jährliche Steigerungsrate konfigurierbar.

KV: Mieteinnahmen sind bei KVdR nicht beitragspflichtig; bei freiwilliger GKV sind sie beitragspflichtig.

### Erweiterte Einstellungen (Expander)

| Feld | Beschreibung |
|---|---|
| GFB-Wachstum p.a. (%) | Jährliches Wachstum des Grundfreibetrags. Per Simulationsjahr: `GFB × (1+rate)^y`. Verschiebt alle ESt-Zonengrenzen. Default: 0 % |
| Separate Pool-Rendite | Checkbox: aktiviert profilweite Default-Rendite für alle Kapitalanlage-Pools |
| Pool-Rendite p.a. (%) | Nur sichtbar wenn Checkbox aktiv. Überschreibt `profil.rendite_pa` für alle Kapitalanlage-Pools; kann von produktspezifischer Rendite überschrieben werden |

---

## 2. Dashboard

### Kennzahlen

Zeigt auf einen Blick: Bruttorente, Nettoentnahme, Steuer + KV, freies Nettoeinkommen.

### Wasserfall-Chart

Visualisiert den Weg von Brutto zu Netto: Rente + Zusatzrenten → Steuern → KV/PV → Netto.

### Kaufkraft-Anpassung

Inflationsbereinigung der Nettorente. Konfigurierbarer Inflationsslider (0–5 %, Default 2 %). Zeigt den Kaufkraftverlust über einen einstellbaren Zeithorizont.

### Progressionszone-Ampel

Zeigt die aktuelle Steuerprogression mit Ampelfarben:
- **Steuerfrei** (< Grundfreibetrag)
- **Zone 1** (erste Progressionszone, bis 17.005 €)
- **Zone 2** (zweite Progressionszone, bis 66.760 €)
- **42 % Spitzensteuersatz** (bis 277.825 €)
- **45 % Reichensteuersatz** (> 277.825 €)

Zeigt außerdem: Grenzsteuersatz, Jahressteuer (ESt + Soli), Freiraum bis zur nächsten Zone, Handlungshinweis.

### Steuer- & KV-Details (Expander)

Detaillierte Aufschlüsselung aller Steuer- und KV-Posten inkl. Besteuerungsanteil-Chart und Marginalsteuersatz-Analyse.

---

## 3. Haushalt-Tab

Nur sichtbar wenn eine zweite Person erfasst wurde.

### Veranlagungsoptionen

| Option | Beschreibung |
|---|---|
| Getrennt | Jede Person wird einzeln veranlagt; Mieteinnahmen werden 50/50 aufgeteilt |
| Zusammen (Splitting) | §32a Abs. 5 EStG: ESt auf (Summe zvE / 2) × 2; oft deutlich günstiger bei unterschiedlichen Einkommen |

### Splitting-Vorteil

Zeigt die Steuerersparnis durch gemeinsame Veranlagung in €/Monat und €/Jahr.

### Szenario-Tabelle

Vergleich pessimistisch/neutral/optimistisch für den Haushalt gesamt.

---

## 4. Simulation-Tab

### Szenarien

| Szenario | Rentenanpassung | Kapitalrendite |
|---|---|---|
| Pessimistisch | 0,5 %/Jahr | 2 %/Jahr |
| Neutral | 2,0 %/Jahr | 5 %/Jahr |
| Optimistisch | 3,5 %/Jahr | 8 %/Jahr |

Jedes Szenario verwendet eine vollständige `_netto_ueber_horizont`-Simulation (keine Näherungsformel).

### Sensitivitätsanalyse

Zeigt den Effekt verschiedener Renteneintrittsalter (60–70) auf Nettorente und Kapitalstand.

---

## 5. Vorsorge-Bausteine

### Produkttypen

| Typ | Steuer bei Rente | KV (KVdR) | KV (freiwillig) | Bemerkung |
|---|---|---|---|---|
| **bAV** | Vollauszahlung §22 Nr. 5 EStG; Monatl. Ertragsanteil §22 Nr. 1 S. 3a | §229 pflichtig, Freibetrag 187,25 €/Mon. | Pflichtig ohne Freibetrag | Betriebliche Altersvorsorge |
| **Riester** | §22 Nr. 5 EStG (gefördert); Ertragsanteil §22 Nr. 1 S. 3a bb | §229 nicht pflichtig | Pflichtig | Zulagen §83 EStG (466 €/Jahr Basis + 185 €/Kind) |
| **Rürup** | Besteuerungsanteil §22 Nr. 1 S. 3a aa (wie GRV) | §229 nicht pflichtig | Pflichtig | Basisrente; kein Kapitalwahlrecht |
| **LV** | Halber Unterschiedsbetrag §20 Abs. 1 Nr. 6 EStG (nach 2005, ≥ 12 J.) | Nicht pflichtig | Pflichtig | Altvertrag (vor 2005): pauschal steuerfrei |
| **ETF** | §20 InvStG; Teilfreistellung 30 % (thesaurierend); 0 % (ausschüttend) | Nicht pflichtig | Pflichtig | Ausschüttend-Checkbox deaktiviert Teilfreistellung |
| **Private RV – Monatsrente** | Ertragsanteil §22 Nr. 1 S. 3a bb EStG | Nicht pflichtig | Pflichtig | Basiert auf Alter bei Rentenbeginn |
| **Private RV – Einmalauszahlung** | Wie LV: §20 Abs. 1 Nr. 6 EStG | Nicht pflichtig | Pflichtig | |

### Einzahlungsfelder je Produkt

| Feld | Beschreibung |
|---|---|
| Einzahlungen gesamt (€) | Bisher geleistete Gesamteinzahlungen (Kostenbasis für Steuerberechnung) |
| Einmaleinzahlung bisher (€) | Bereits geleistete Einmaleinzahlungen (Teil der Kostenbasis) |
| Jährl. Beitrag (€/Jahr) | Laufender Jahresbeitrag ab heute bis Startjahr |
| Dynamik p.a. (%) | Jährliche Beitragssteigerung |
| Beitragsbefreiung ab Jahr | BU-Schutz: ab diesem Jahr entfällt der Beitrag; Leistungen werden als Einzahlungen behandelt |
| Frühestmögl. Startmonat | Monat (1–12) in dem die Auszahlung im frühestmöglichen Startjahr beginnt. Das erste Auszahlungsjahr wird anteilig berechnet: `(13 − Startmonat) / 12`. Default: Januar (1). |
| Spätestmögl. Startmonat | Entsprechend für das spätestmögliche Startjahr. Default: Dezember (12). |

### Kapitalanlage-Pool

Checkbox „Als Kapitalanlage reinvestieren": Die Einmalauszahlung wird nicht direkt als Einkommen verbucht, sondern in einen internen Pool reinvestiert und über den Planungshorizont als Annuität entnommen.

**Produktspezifische Pool-Rendite:** Checkbox „Eigene Pool-Rendite" je Produkt erlaubt eine abweichende Rendite für diesen Pool.

**Rendite-Priorität:** Produktspezifische Rendite → Profilweite Pool-Rendite → allgemeine Profil-Rendite.

### Steuer/KV aus Nutzer-Selektion

Die Balken "Netto", "Steuer" und "KV/PV" im Optimale-Strategie-Chart spiegeln die tatsächlich gewählte Auszahlungsart jedes Produkts wider (monatliche Rente vs. Einmalauszahlung). Die Auswahl erfolgt über die interaktive Tabelle im gleichen Abschnitt.

### Strategievergleich

5-Säulen-Balkendiagramm: Frühest monatlich, Frühest einmal, Spätestens monatlich, Spätestens einmal, Optimal.

---

## 6. Entnahme-Optimierung

### Steuer-Steckbrief

Detailansicht der steuerlichen Behandlung jedes Vorsorgebausteins mit den relevanten §§.

### Auszahlungsoptimierung

Suche über alle Kombinationen aus:
- Startjahr je Produkt (frühestmöglich bis spätestmöglich)
- Auszahlungsart (monatliche Rente vs. Einmalauszahlung, soweit möglich)

Ziel: Maximierung des durchschnittlichen monatlichen Nettoeinkommens über den Planungshorizont.

**Referenzstrategien** für Vergleich: alle Produkte frühestmöglich monatlich, frühestmöglich einmal, spätestmöglich monatlich, spätestmöglich einmal. Die optimale Strategie ist stets ≥ jeder Referenzstrategie.

### Echtzeit-Propagation in andere Tabs

Änderungen an Auszahlungsart (monatlich/einmal) oder Startjahr in der "Empfehlungen zur Auszahlung"-Tabelle werden sofort in alle anderen Tabs übernommen: Dashboard-Wasserfall, Haushalt-Paarvergleich, Simulations-Jahresverlauf und Vorsorge-Bausteine-Chart spiegeln die gewählte Strategie ohne manuellen Reload.

### Steuer- und KV-Verlauf

Gestapeltes Balkendiagramm mit drei Komponenten:
- **ESt + Soli** (pink): Einkommensteuer §32a EStG + Solidaritätszuschlag §51a EStG + ggf. Kirchensteuer — entspricht der `Steuer`-Spalte abzüglich Abgeltungsteuer
- **Abgeltungsteuer** (hellrot): Nur sichtbar wenn Kapitalerträge abgeltungsteuerpflichtig sind
- **KV/PV** (gelb): Kranken- und Pflegeversicherungsbeiträge

Der Hover zeigt je Balken den Jahresbetrag. Der zvE-Verlauf wird als gestrichelte Linie auf der rechten Achse eingeblendet.

### Kapital-Zeitleiste

Zeigt das Sparkapital (aus dem Profil) als sich über die Zeit entwickelnde Linie. Vor Renteneintritt: Wachstum mit Sparrate. Ab Renteneintritt: annuitätsbasierter Kapitalverzehr (monatliche Entnahme = `kapital_monatlich` aus `berechne_rente()`). Zusätzlich: Kapitalanlage-Pools einzelner Vorsorgeprodukte (als_kapitalanlage=True) als separate Linien.

### Empfehlungen Kapital-Entnahmen

Tabelle mit Jahreszeilen: Frei verfügbares Einkommen, Mindesthaushalt, Abweichung, Pool-Bestand. Manuelle Pool-Entnahmen können direkt eingetragen werden.

**Ampeln in der Abweichungs-Spalte:**
- 🟢 Mindesthaushalt erreicht oder überschritten (`Abweichung ≥ 0`)
- 🔴 Einkommen unter Mindesthaushalt, auch nach manueller Pool-Entnahme (`Abweichung < 0`)

Die Abweichung berechnet sich als: `Netto − automatische Annuität − Hypothekenrate − Mindesthaushalt + manuelle Entnahme`. Ein Wert von 0 entspricht exakt dem Mindesthaushalt.

**Pool-Bestand (€):** Zeigt den Gesamtbestand aller Kapitalanlage-Pools (Vorsorgeprodukte mit "Als Kapitalanlage reinvestieren") **plus** das Sparkapital aus dem Profil. Das Sparkapital wird vor Renteneintritt mit Sparrate und Rendite angesammelt, ab Renteneintritt als Annuität (`kapital_monatlich` aus `berechne_rente()`) verzehrt.

### Jahresverlauf

Gestapeltes Balkendiagramm der Einkommensquellen je Jahr:
- Gesetzliche Rente
- Beamtenpension
- bAV, Riester, Rürup, LV, ETF, Private RV
- Kapitalverzehr je Pool (einzeln bei mehreren Pools)
- Gehalt (Arbeitsjahre)
- Mieteinnahmen

Warnhinweis wenn Nettoeinkommen in einem Jahr negativ ist (z.B. durch hohe Hypothekenrate oder Poolinjektion).

### Pool-Verlauf-Chart

Separater Chart für alle Kapitalanlage-Pools: Poolwert je Produkt über die Zeit (Linien) und Jahresentnahmen (Balken auf zweiter Y-Achse).

### Hypothek-Verwaltung (Expander)

Eingabe von Hypothekendaten mit Validierung:

| Feld | Beschreibung |
|---|---|
| Darlehensbetrag (€) | Restschuld bei Simulationsstart oder Neudarlehen |
| Jahresrate (€) | Jährliche Rückzahlungsrate (Tilgung + Zinsen) |
| Zinssatz p.a. (%) | Nominalzins |
| Startjahr / Startmonat | Beginn des Tilgungsplans; das Startjahr wird anteilig berechnet: `(13 − Startmonat) / 12` |
| Endjahr / Endmonat | Ende des Tilgungsplans; das Endjahr wird anteilig berechnet: `Endmonat / 12` |
| Raten in Simulation | Laufende Jahresraten in den Ausgaben-Plan einbeziehen (sichtbar im Jahresverlauf) |
| Restschuld-Behandlung | Keine / Als Kapitalanlage (Pool) / Als Ratenkredit nach Endjahr |

Validierungsregeln: Endjahr > Startjahr, Betrag > 0, Rate > 0, Rate ≤ Betrag.

### Kapitalverzehr-Kalkulator (Expander)

Separates Tool zur Berechnung: Wie lange reicht ein Kapitalstock bei fixer monatlicher Entnahme und gegebener Rendite?

---

## 7. Steuer- und KV-Berechnung

### Einkommensteuer §32a EStG

Grundtarif 2024 mit 5 Zonen:

| Zone | zvE-Bereich | Formel |
|---|---|---|
| Steuerfrei | 0 – 11.604 € | 0 € |
| Zone 1 | 11.604 – 17.005 € | Progressionsformel (14–24 %) |
| Zone 2 | 17.005 – 66.760 € | Progressionsformel (24–42 %) |
| Zone 3 | 66.760 – 277.825 € | 42 % flat (abzüglich Abschneidebetrag) |
| Zone 4 | > 277.825 € | 45 % flat (abzüglich Abschneidebetrag) |

Mit **GFB-Wachstum** verschieben sich alle Zonengrenzen um `delta = aktueller_GFB - GRUNDFREIBETRAG_2024`.

### Solidaritätszuschlag §51a EStG

- Freigrenze: 17.543 € ESt
- Gleitzone: bis 33.912 € ESt (linear auf 5,5 %)
- Vollsatz: 5,5 % der ESt ab 33.912 €

### Kirchensteuer §51a EStG

8 % (Bayern/Baden-Württemberg) oder 9 % der Einkommensteuer. Kirchensteuer mindert sich selbst (konfessioneller Abzug): effektiver Satz ca. 8,85 % / 9,94 % der ESt.

### Besteuerungsanteil §22 EStG (GRV / Rürup)

Ab 2005: gestaffelt von 50 % (Renteneintritt 2005) auf 100 % (Renteneintritt 2040). Ab 2023 (JStG 2022): +0,5 %/Jahr (statt +1 %/Jahr). Der Anteil wird einmalig beim Renteneintritt festgelegt und bleibt für die gesamte Rentenlaufzeit konstant.

### Versorgungsfreibetrag §19 Abs. 2 EStG (Pensionäre)

Gestaffelt von 40 % / max. 3.000 € (Ruhestand 2005) auf 0 % (Ruhestand ab 2040). Der Freibetrag wird einmalig beim Ruhestandsbeginn festgelegt.

### Altersentlastungsbetrag §24a EStG

Für Personen, die im Laufe des Veranlagungszeitraums das 64. Lebensjahr vollendet haben.

**Qualifizierende Einkünfte:** Private RV (Ertragsanteil), Riester, BUV/DUV, Mieteinnahmen (§21), Arbeitslohn (§19, kein Versorgungsbezug).

**Nicht qualifizierend:** GRV/Rürup (§22 Nr. 1 S. 3a aa), bAV, Beamtenpension.

Maximalbeträge 2024: 19,2 % der qualifizierenden Einkünfte, max. 912 €/Jahr. Ab 2040: 0.

### Ertragsanteil §22 Nr. 1 S. 3a bb EStG

Tabellenwert nach Alter bei Rentenbeginn (z.B. 67 Jahre → 17 %). Gilt für: private Rentenversicherung (Monatsrente), DUV, BUV.

### KV/PV – KVdR-Pflichtmitglied

Beitragspflichtige Einnahmen nach §229 SGB V:
- Gesetzliche Rente (vollständig)
- bAV: Freibetrag 187,25 €/Mon. (§226 Abs. 2 SGB V); Basis = max(0, bAV − Freibetrag)
- bAV-Einmalauszahlung: 1/120 pro Monat über 10 Jahre verteilt
- BBG-Deckel: 5.175 €/Mon.

Nicht beitragspflichtig: Private RV, Riester, LV, ETF, Mieteinnahmen, Kapitalerträge.

### KV/PV – Freiwillig GKV

Alle Einkünfte beitragspflichtig (§240 SGB V), inkl.:
- Gesetzliche Rente, bAV (ohne Freibetrag), Private RV, LV/ETF, Mieteinnahmen, laufende Kapitalerträge

Mindest-BMG: 1.096,67 €/Mon. (§240 Abs. 4 SGB V). BBG-Deckel: 5.175 €/Mon.

### PV-Kinderstaffelung §55 Abs. 3a SGB XI

| Kinder | Voller Satz | Halber Satz (AN) |
|---|---|---|
| 0 | 4,0 % | 2,3 % |
| 1 | 3,4 % | 1,7 % |
| 2 | 3,15 % | 1,45 % |
| 3 | 2,9 % | 1,2 % |
| 4 | 2,65 % | 0,95 % |
| ≥ 5 | 2,4 % | 0,7 % |

---

## 8. Gesetzliche Grundlagen

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
| §20 Abs. 1 Nr. 6 EStG | Ertragsanteil LV / Private RV Einmalauszahlung |
| §226 Abs. 2 SGB V | bAV-Freibetrag KVdR (187,25 €/Mon.) |
| §229 SGB V | Versorgungsbezüge KVdR-pflichtig |
| §240 SGB V | Freiwillig GKV: alle Einkünfte beitragspflichtig |
| §55 Abs. 3a SGB XI | PV-Kinderstaffelung: −0,25 % je Kind ab dem 2. Kind |
| §77 SGB VI | Rentenabschlag 0,3 %/Monat Frühverrentung |
| §83 EStG | Riester-Grundzulage 466 €/Jahr + 185 €/Kind |
| §14 BeamtVG | Versorgungssatz Beamtenpension: 1,79375 % je Dienstjahr, max. 71,75 % (40 Dienstjahre) |

---

## 9. Bekannte Vereinfachungen

- **Regelaltersgrenze:** §235 SGB VI-Übergangsregelung für Jahrgänge 1947–1963 ist korrekt implementiert (`regelaltersgrenze(geburtsjahr)`); Rentenabschlag 0,3 %/Monat bei Frühverrentung (§77 SGB VI)
- **LV-Altvertrag (vor 2005):** Pauschal steuerfrei; 5-Jahres-Beitragspflicht und 60%-Todesfallschutz werden nicht geprüft
- **Abgeltungsteuer:** 25 % auf Kapitalerträge (Soli/KiSt auf Abgeltungsteuer nicht berücksichtigt)
- **ETF thesaurierend:** Teilfreistellung 30 % (§20 Abs. 1 InvStG); Vorabpauschale nicht berücksichtigt
- **Pool-Doppelbesteuerung:** LV/PrivateRente als_kapitalanlage: Renditegewinne im Pool werden nochmals mit Abgeltungsteuer belastet (konservativ)
- **Zugangsfaktor:** Kein Aufschub-Bonus bei Rentenverzögerung berücksichtigt
- **Versorgungsfreibetrag:** Feste Tabelle; Übergangsregelungen für Jahrgänge vor 1964 nicht berücksichtigt
- **Riester-Zulagen:** Nicht in der Nettorenten-Berechnung eingebaut (Info-Box im Vorsorge-Tab)
- **Beitragsbefreiungsleistung:** Konservativ als weitere Einzahlungen gewertet (keine Ertragsanteil-Befreiung)

---

## 10. Haftungsausschluss

Diese Simulation dient ausschließlich **Informations- und Planungszwecken**. Sie stellt keine Steuer-, Rechts- oder Anlageberatung dar.

Alle Berechnungen basieren auf den gesetzlichen Regelungen des angegebenen Stands. Gesetzesänderungen, individuelle steuerliche Besonderheiten und persönliche Umstände können zu abweichenden tatsächlichen Ergebnissen führen.

Für verbindliche Auskünfte wenden Sie sich an:
- **Deutsche Rentenversicherung** (gesetzliche Rente, Rentenpunkte)
- **Steuerberater** (Einkommensteuer, Kirchensteuer, Abgeltungsteuer)
- **Krankenkasse** (KV-Beiträge, KVdR-Berechtigung)
- **Finanzberater** (Vorsorgeprodukte, Kapitalanlageentscheidungen)
