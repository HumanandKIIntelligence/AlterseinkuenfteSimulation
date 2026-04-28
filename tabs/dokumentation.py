"""Dokumentations-Tab – Erläuterung der Berechnungsgrundlagen und Funktionen."""

import streamlit as st

from engine import (
    RENTENWERT_2024,
    GRUNDFREIBETRAG_2024,
    WERBUNGSKOSTEN_PAUSCHBETRAG,
    SONDERAUSGABEN_PAUSCHBETRAG,
    BAV_FREIBETRAG_MONATLICH,
    BBG_KV_MONATLICH,
    MINDEST_BMG_FREIWILLIG_MONO,
    AKTUELLES_JAHR,
)


def render(T: dict) -> None:
    with T["Dokumentation"]:
        st.header("📖 Dokumentation & Berechnungsgrundlagen")
        st.caption(
            "Diese Seite erläutert alle Formeln, Annahmen und gesetzlichen Grundlagen "
            "der Simulation. Alle Werte beziehen sich auf das Steuerjahr 2024."
        )

        # ── Übersicht ─────────────────────────────────────────────────────────
        st.subheader("Überblick")
        st.markdown("""
        Die **Alterseinkünfte-Simulation** berechnet das voraussichtliche Renteneinkommen
        einer oder zweier Personen unter Berücksichtigung von:

        - Gesetzliche Rente (DRV) nach Rentenpunkten; Regelaltersgrenze § 235 Abs. 2 SGB VI; Abschlag § 77 SGB VI
        - Beamtenpension mit Versorgungsfreibetrag (§ 19 Abs. 2 EStG); Beihilfe + PKV
        - Vorsorgeprodukte: bAV (§ 19/§ 22 Nr. 5 EStG), Riester (§§ 83–85 EStG), Rürup (§ 10 Abs. 1 Nr. 2b EStG), Lebensversicherung (§ 20 Abs. 1 Nr. 6 EStG), ETF (§ 20 InvStG), private RV (§ 22 Nr. 1 S. 3a bb EStG)
        - Kapital und monatliche Sparrate bis zum Renteneintritt
        - Einkommensteuer § 32a EStG (Grundtarif 2024) inkl. Solidaritätszuschlag + Kirchensteuer (§ 51a EStG)
        - Altersentlastungsbetrag (§ 24a EStG) für Personen ab 65 Jahren
        - Besteuerungsanteil gesetzliche Rente (§ 22 EStG / JStG 2022)
        - Kranken- und Pflegeversicherung: KVdR (§ 5 Abs. 1 Nr. 11 SGB V), freiwillig (§ 240 SGB V), PKV; PV-Kinderstaffelung (§ 55 Abs. 3a SGB XI)
        - bAV-Freibetrag KVdR (§ 226 Abs. 2 SGB V); Einmalauszahlung 10-Jahres-Verteilung (§ 229 Abs. 1 S. 3 SGB V)
        - Dienstunfähigkeitsversicherung (DUV) und Berufsunfähigkeitsversicherung (BUV) – Ertragsanteil § 22 Nr. 1 S. 3a bb EStG
        - Mieteinnahmen als Haushaltseinkommen (§ 21 EStG)
        - Ehegatten-Splitting (§ 32a Abs. 5 EStG) und Getrenntveranlagung (§ 25 EStG)
        - Witwen-/Witwerrente (§ 46 Abs. 2 SGB VI) mit Einkommensanrechnung (§ 97 SGB VI)
        - Grundsicherungshinweis (§ 41 SGB XII) bei Nettorente unter 1.100 €/Mon.
        """)

        st.subheader("App-Aufbau (6 Tabs)")
        st.markdown("""
        | Tab | Inhalt |
        |---|---|
        | ⚙️ **Profil** | Alle Personendaten, KV-Wahl, DUV/BUV, Mieteinnahmen, Speichern/Laden |
        | 📊 **Dashboard** | Kennzahlen, Brutto→Netto-Wasserfall, Kaufkraft, Progressionszone-Ampel, Steuer & KV-Details (Expander) |
        | 👥 **Haushalt** | Nur bei Partner: Paarvergleich, Splitting-Vorteil, Szenario-Tabelle |
        | 🔮 **Simulation** | Drei Szenarien (pessimistisch/neutral/optimistisch), Kapitalverlauf |
        | 🏦 **Vorsorge-Bausteine** | Vertragserfassung, Steuer-Steckbrief, Kombinations-Optimierung |
        | 💡 **Entnahme-Optimierung** | Optimale Auszahlungsstrategie, Jahresverlauf, Kapitalverzehr-Kalkulator (Expander) |
        """)

        st.divider()

        # ── Gesetzliche Rente ──────────────────────────────────────────────────
        with st.expander("📌 Gesetzliche Rente – Berechnung (DRV)", expanded=True):
            st.markdown(f"""
            **Formel:**
            > Bruttorente = Gesamtpunkte × Rentenwert × Rentenanpassungsfaktor

            | Parameter | Erläuterung |
            |---|---|
            | **Gesamtpunkte** | Aktuelle Rentenpunkte + (Punkte/Jahr × Restjahre bis Rente) |
            | **Rentenwert** | {RENTENWERT_2024:.2f} € / Punkt (West, Stand 01.07.2024) |
            | **Rentenanpassung** | Eingabe in % p.a.; wird über Restjahre aufgezinst |
            | **Durchschnittsentgelt (§ 18 Abs. 1 SGB IV)** | 43.142 €/Jahr (2024); Basis für EP = Brutto / Durchschnittsentgelt |

            ---

            **Regelaltersgrenze – § 235 Abs. 2 SGB VI:**

            | Geburtsjahrgang | Regelaltersgrenze |
            |---|---|
            | ≤ 1946 | 65 Jahre |
            | 1947 | 65 Jahre + 1 Monat |
            | 1948–1958 | schrittweise bis 66 Jahre |
            | 1959 | 66 Jahre + 2 Monate |
            | 1960 | 66 Jahre + 4 Monate |
            | 1961 | 66 Jahre + 6 Monate |
            | 1962 | 66 Jahre + 8 Monate |
            | 1963 | 66 Jahre + 10 Monate |
            | ≥ 1964 | 67 Jahre |

            Die Übergangstabelle ist vollständig in `regelaltersgrenze(geburtsjahr)` implementiert.

            ---

            **Rentenabschlag – § 77 SGB VI:** 0,3 % pro Monat Frühverrentung vor der
            individuellen Regelaltersgrenze; entspricht max. −10,8 % bei 3 Jahren Frühverrentung.

            **Wartezeit – § 36 SGB VI:** 35 Beitragsjahre ermöglichen Frühverrentung ab 63
            (mit Abschlag). Die App zeigt bei Renteneintrittsalter < 63 eine Warnung
            (§ 236b SGB VI: 45-Jährige-Regelung ist nicht implementiert).

            **Grundsicherungshinweis (§ 41 SGB XII):** Wenn die projizierte Nettorente
            unter 1.100 €/Mon. liegt, erscheint im Dashboard ein Hinweis auf einen
            möglichen Grundsicherungsanspruch (indikativ – kein Rechtsanspruch).
            """)

        # ── Beamtenpension ─────────────────────────────────────────────────────
        with st.expander("🏛 Beamtenpension – § 19 Abs. 2 EStG (Versorgungsfreibetrag)"):
            st.markdown("""
            Für Beamtinnen und Beamte gilt statt des Besteuerungsanteils der gesetzlichen
            Rente der **Versorgungsfreibetrag** nach § 19 Abs. 2 EStG.

            **Formel:**
            > zvE = Jahrespension − Versorgungsfreibetrag − Werbungskosten-Pauschbetrag − Sonderausgaben-Pauschbetrag

            **Versorgungsfreibetrag (Auszug):**

            | Versorgungsbeginn | Anteil | Max.-Betrag | Zuschlag |
            |---|---|---|---|
            | 2005 | 40,0 % | 3.000 € | 900 € |
            | 2015 | 24,0 % | 1.800 € | 540 € |
            | 2024 | 12,8 % | 960 € | 288 € |
            | ab 2040 | 0 % | 0 € | 0 € |

            **KV-Basis Beamtenpension (§ 229 Abs. 1 Nr. 1 SGB V):**
            Beamtenversorgung ist KVdR-pflichtig auf den vollen Pensionsbetrag –
            ohne den bAV-Freibetrag (187,25 €), der nur für Betriebsrenten gilt (§ 226 Abs. 2 SGB V).

            **Beihilfe + PKV:** Beamte erhalten i.d.R. 70 % Beihilfe für Krankheitskosten.
            Die PKV-Eingabe enthält nur den Eigenanteil (30 %).
            """)

        # ── DUV / BUV ──────────────────────────────────────────────────────────
        with st.expander("🛡 Dienstunfähigkeits- und Berufsunfähigkeitsversicherung (DUV / BUV)"):
            st.markdown("""
            Beide Versicherungsleistungen sind **nicht KVdR-pflichtig** (§ 229 SGB V erfasst
            nur gesetzliche Renten und Versorgungsbezüge, keine privaten Versicherungsleistungen).

            **Steuerbehandlung (§ 22 Nr. 1 S. 3a bb EStG – Ertragsanteil):**

            | Alter bei Leistungsbeginn | Ertragsanteil (beispielhaft) |
            |---|---|
            | 40 Jahre | 38 % |
            | 50 Jahre | 30 % |
            | 60 Jahre | 22 % |

            > zvE-Anteil = Monatsrente × 12 × Ertragsanteil(Alter bei Leistungsbeginn)

            **DUV** ist nur für Beamte relevant (Absicherung bei Dienstunfähigkeit).
            Die Leistung läuft bis zum eingegebenen Endjahr (z. B. reguläres Pensionierungsalter).

            **BUV** ist für GRV-Versicherte (Nicht-Beamte). Die gesetzliche
            Erwerbsminderungsrente wird stattdessen als „Bereits in Rente" erfasst.
            """)

        # ── Altersentlastungsbetrag ────────────────────────────────────────────
        with st.expander("🎁 Altersentlastungsbetrag – § 24a EStG"):
            st.markdown("""
            Steuerpflichtige, die zu Beginn des Veranlagungszeitraums das 64. Lebensjahr
            vollendet haben, erhalten einen Altersentlastungsbetrag auf qualifizierende
            Einkünfte. Der Betrag richtet sich nach dem **Jahr des erstmaligen Bezugs**
            (= Geburtsjahr + 65) und wird jährlich abgebaut.

            **Qualifizierende Einkunftsarten:**

            | Einkunftsart | Qualifizierend? | Hinweis |
            |---|---|---|
            | Gesetzliche Rente (§ 22 Nr. 1 S. 3a aa EStG) | ❌ Nein | Abgegolten durch Besteuerungsanteil |
            | Rürup-Rente (§ 22 Nr. 1 S. 3a aa EStG) | ❌ Nein | Gleiche Vorschrift |
            | bAV, Beamtenpension (§ 19 Abs. 2 EStG) | ❌ Nein | Versorgungsbezüge |
            | Arbeitslohn (§ 19 EStG, kein Versorgungsbezug) | ✅ Ja | Z. B. Teilzeit in Rente |
            | Ertragsanteil private RV / DUV / BUV (§ 22 Nr. 1 S. 3a bb) | ✅ Ja | |
            | Riester (§ 22 Nr. 5 EStG) | ✅ Ja | |
            | Mieteinnahmen (§ 21 EStG) | ✅ Ja | |

            **Phase-out-Tabelle (Auszug):**

            | Erstjahr (Geburtsjahr + 65) | Prozentsatz | Höchstbetrag |
            |---|---|---|
            | bis 2005 | 40,0 % | 1.900 € |
            | 2010 | 32,0 % | 1.520 € |
            | 2020 | 16,0 % | 760 € |
            | 2025 | 12,0 % | 570 € |
            | 2030 | 8,0 % | 380 € |
            | ab 2040 | 0 % | 0 € |

            **Beispiel:** Person geboren 1960, Erstjahr AEB = 2025 → 12,0 % auf qualifizierendes
            Einkommen, maximal 570 €/Jahr. Bei 400 € PrivRV-Ertragsanteil/Jahr:
            AEB = min(400 × 12 % = 48 €, 570 €) = 48 €.

            **Umsetzung:** Der AEB wird in `berechne_rente()` und im Jahres-Simulationsloop
            (`_netto_ueber_horizont()`) automatisch angewendet. Bei Mieteinnahmen über
            `berechne_haushalt()` wird der verbleibende Restbetrag (nach Abzug der
            bereits genutzten AEB-Summe aus `berechne_rente()`) berücksichtigt.
            """)

        # ── Einkommensteuer ────────────────────────────────────────────────────
        with st.expander("🧾 Einkommensteuer – § 32a EStG Grundtarif 2024"):
            st.markdown(f"""
            Das zu versteuernde Einkommen (zvE) wird wie folgt ermittelt:

            > zvE = Jahresbruttorente × **Besteuerungsanteil** − Werbungskosten-Pauschbetrag − Sonderausgaben-Pauschbetrag

            | Pauschbetrag | Wert |
            |---|---|
            | Werbungskosten (§ 9a EStG) | {WERBUNGSKOSTEN_PAUSCHBETRAG} €/Jahr |
            | Sonderausgaben (§ 10c EStG) | {SONDERAUSGABEN_PAUSCHBETRAG} €/Jahr |
            | Grundfreibetrag (§ 32a EStG) | {GRUNDFREIBETRAG_2024:,} €/Jahr |

            **Steuertarif 2024 (§ 32a EStG):**

            | zvE | Formel | Grenzsteuersatz |
            |---|---|---|
            | ≤ {GRUNDFREIBETRAG_2024:,} € | 0 € | 0 % |
            | {GRUNDFREIBETRAG_2024:,} – 17.005 € | (928,37 · y + 1.400) · y | 14–24 % |
            | 17.005 – 66.760 € | (176,64 · z + 2.397) · z + 1.025,38 | 24–42 % |
            | 66.760 – 277.825 € | 42 % × zvE − 9.972,98 € | 42 % |
            | > 277.825 € | 45 % × zvE − 18.307,73 € | 45 % |

            **Solidaritätszuschlag (§ 51a EStG):**

            | Jahressteuer (ESt) | Soli |
            |---|---|
            | ≤ 17.543 € | 0 € (unter Freigrenze) |
            | 17.543 – 33.912 € | Gleitzone: min(5,5 % × ESt ; 20 % × (ESt − 17.543 €)) |
            | > 33.912 € | 5,5 % × ESt |

            Für die meisten Rentner mit ESt unter der Freigrenze fällt kein Soli an.

            **Kirchensteuer (§ 51a EStG):**

            | Bundesland | Satz |
            |---|---|
            | Bayern, Baden-Württemberg | 8 % der Einkommensteuer |
            | alle anderen Bundesländer | 9 % der Einkommensteuer |

            Kirchensteuer wird nur berechnet, wenn die Checkbox „Kirchensteuerpflichtig"
            im Profil-Tab aktiviert ist. Bei Ehegatten-Splitting: jeder Partner zahlt
            Kirchensteuer auf seinen Anteil der Splitting-ESt.

            **Progressionszone-Ampel im Dashboard:** Zeigt die aktuelle Steuerzone,
            den analytischen Grenzsteuersatz, die Jahressteuer (ESt + Soli) und den
            Freiraum bis zur nächsten Zone mit einem konkreten Handlungshinweis.
            """)

        # ── Besteuerungsanteil ─────────────────────────────────────────────────
        with st.expander("📈 Besteuerungsanteil der Rente – § 22 EStG / JStG 2022"):
            st.markdown("""
            Der Besteuerungsanteil bestimmt, welcher Prozentsatz der gesetzlichen Rente
            steuerpflichtig ist. Gilt **nicht** für Beamtenpensionen (dort: Versorgungsfreibetrag).

            **Entwicklung:**

            | Renteneintritt | Besteuerungsanteil |
            |---|---|
            | bis 2005 | 50 % |
            | 2006–2020 | +2 % pro Jahr (bis max. 80 %) |
            | 2021 | 81 % |
            | 2022 | 82 % |
            | ab 2023 | 82,5 % + 0,5 % pro Jahr (JStG 2022) |
            | ab 2058 | 100 % |

            **Jahressteuergesetz 2022 (JStG 2022):** Seit 2023 steigt der Anteil nur noch
            um **0,5 % p.a.** statt 1 %. Vollständige Besteuerung erst ab Renteneintritt **2058**
            (statt ursprünglich 2040). Dies entlastet vor allem Jahrgänge ab ca. 1974.
            """)

        # ── Ehegatten-Splitting ────────────────────────────────────────────────
        with st.expander("👥 Ehegatten-Splitting – § 32a Abs. 5 EStG / Getrenntveranlagung – § 25 EStG"):
            st.markdown("""
            **Zusammenveranlagung – Splittingtarif (§ 32a Abs. 5 EStG):**
            Das gemeinsame zvE wird halbiert, die Steuer nach Grundtarif berechnet und verdoppelt:

            > Splitting-Steuer = 2 × ESt(zvE_gesamt / 2)

            **Vorteil:** Entsteht bei ungleichen Einkommen, da die progressive Steuerkurve
            abgeflacht wird. Bei gleich hohen Einkommen kein Vorteil.

            **Mieteinnahmen im Splitting:**
            - Zusammenveranlagung: Mieteinnahmen fließen vollständig ins gemeinsame zvE → werden mitgesplittet.
            - Getrennte Veranlagung: Mieteinnahmen werden 50/50 aufgeteilt.

            ---

            **Getrennte Veranlagung (§ 25 EStG):**
            Jeder Partner wird einzeln veranlagt:
            > Steuer_gesamt = ESt(zvE_P1) + ESt(zvE_P2)

            Solidaritätszuschlag und Kirchensteuer ebenfalls getrennt je Person berechnet.
            Im Haushalt-Tab wird der Splitting-Vorteil (Zusammen minus Getrennt) ausgewiesen.

            **Witwen-/Witwerrente – § 46 Abs. 2 SGB VI / § 97 SGB VI:**

            Beim Tod eines Partners erhalten Hinterbliebene das **große Witwengeld**:
            > Witwenrente = 55 % der gesetzl. Bruttorente des Verstorbenen

            Eigenes Einkommen wird nach § 97 SGB VI angerechnet:
            - Freibetrag: 26.400 €/Jahr (ca. 2.200 €/Mon.)
            - Übersteigendes Einkommen: 40 % werden auf die Witwenrente angerechnet

            **Vereinfachungen:** Kein kleines Witwengeld (2 Jahre nach Heirat), kein
            Bestandsschutz, keine Kinderzuschläge (§ 48 SGB VI). Sichtbar im Haushalt-Tab.
            """)

        # ── GKV/PKV ────────────────────────────────────────────────────────────
        with st.expander("🏥 Kranken- und Pflegeversicherung in der Rente"):
            st.markdown(f"""
            **Gesetzlich versichert (GKV) – Beitragssätze:**

            | Beitragsart | Satz | Träger |
            |---|---|---|
            | KV-Basis | 7,3 % | Rentner zahlt die Hälfte; DRV übernimmt die andere Hälfte |
            | KV-Zusatzbeitrag | ½ × kassenbezogener Zusatzbeitrag | Rentner |
            | PV 1 Kind | 3,4 % | Rentner trägt voll |
            | PV 2 Kinder | 3,15 % | −0,25 % Abschlag ab 2. Kind |
            | PV 3 Kinder | 2,90 % | −0,50 % Abschlag |
            | PV 4 Kinder | 2,65 % | −0,75 % Abschlag |
            | PV 5+ Kinder | 2,40 % | −1,00 % Abschlag (Maximum) |
            | PV ohne Kinder | 4,0 % | inkl. Kinderlosenzuschlag 0,6 % |

            ---

            ### KVdR-Pflichtmitglied (§ 5 Abs. 1 Nr. 11 SGB V)

            Nur §229-Einkünfte sind beitragspflichtig:

            | Einkommensquelle | Beitragspflichtig? | Besonderheit |
            |---|---|---|
            | Gesetzliche Rente | ✅ Ja | Volle Basis |
            | Beamtenpension | ✅ Ja | Volle Basis, kein Freibetrag |
            | bAV (Versorgungsbezüge) | ✅ Ja | Freibetrag {BAV_FREIBETRAG_MONATLICH:.2f} €/Mon. (§ 226 Abs. 2 SGB V) |
            | bAV-Einmalauszahlung | ✅ Ja | 1/120 pro Monat über 10 Jahre |
            | Private RV, Riester, LV | ❌ Nein | – |
            | DUV, BUV (private Vers.) | ❌ Nein | Nicht unter § 229 SGB V |
            | Mieteinnahmen | ❌ Nein | – |
            | Kapitalerträge (Zinsen, Dividenden) | ❌ Nein | – |

            **BBG-Deckelung:** max. **{BBG_KV_MONATLICH:,.0f} €/Mon.**

            ---

            ### Freiwillig GKV-Versicherter (§ 240 SGB V)

            **ALLE** Einnahmen sind beitragspflichtig – ohne den bAV-Freibetrag:

            | Einkommensquelle | Beitragspflichtig? |
            |---|---|
            | Gesetzliche Rente | ✅ Ja |
            | bAV | ✅ Ja (kein Freibetrag!) |
            | Private RV, Riester, LV | ✅ Ja |
            | Mieteinnahmen | ✅ Ja |
            | Kapitalerträge (Zinsen, Dividenden, ETF-Ausschüttungen) | ✅ Ja |

            **Mindestbemessungsgrundlage:** Beiträge werden mindestens auf
            **{MINDEST_BMG_FREIWILLIG_MONO:,.2f} €/Mon.** berechnet (§ 240 Abs. 4 SGB V),
            auch wenn das Einkommen darunter liegt.

            Die laufenden Kapitalerträge je Vorsorgebaustein werden im
            **Bearbeitungsdialog der Vorsorge-Bausteine** erfasst.

            **Profil-Einstellung:** Im Tab „Profil" erscheint bei GKV-Wahl eine Checkbox
            „KVdR-Pflichtmitglied". Default: aktiviert (Pflichtmitglied).

            ---

            **Privat versichert (PKV):**
            Der PKV-Beitrag wird als fixer Monatsbetrag eingegeben. Der DRV-Beitragszuschuss
            ist vereinfacht nicht gesondert ausgewiesen.
            """)

        # ── PV-Kinderstaffelung ────────────────────────────────────────────────
        with st.expander("👶 PV-Kinderstaffelung – § 55 Abs. 3a SGB XI"):
            st.markdown("""
            Seit dem **01.07.2023** staffelt sich der Pflegeversicherungsbeitrag nach
            der Anzahl der Kinder (§ 55 Abs. 3a SGB XI). Der Abschlag gilt nur für den
            **eigenen Anteil** des Versicherten, nicht für den Arbeitgeber- bzw. DRV-Anteil.

            **Beitragssätze 2024 (eigener Anteil):**

            | Kinder | Voller Satz (freiwillig GKV) | Halber Satz (KVdR / AN) |
            |---|---|---|
            | 0 (kinderlos) | 4,00 % | 2,30 % |
            | 1 | 3,40 % | 1,70 % |
            | 2 | 3,15 % | 1,45 % |
            | 3 | 2,90 % | 1,20 % |
            | 4 | 2,65 % | 0,95 % |
            | 5+ | 2,40 % | 0,70 % |

            **Kinderlosenzuschlag:** 0,6 % trägt der Versicherte allein (bei 0 Kindern).

            **Abschlag:** Ab dem 2. Kind je −0,25 % auf den eigenen PV-Anteil;
            maximal −1,0 % bei 5 oder mehr Kindern.

            **Nachweis:** Kinder müssen der Pflegekasse nachgewiesen werden. Die App
            nimmt keine automatische Altersgrenze (Kinder unter 25 J.) an – der
            Nutzer gibt die relevante Kinderzahl direkt ein.

            **Eingabe:** Im Tab „Profil" bei GKV-Wahl erscheint bei aktivierter
            Checkbox „Hat Kinder" ein Zahlenfeld „Anzahl Kinder (1–5)".
            """)

        # ── Vorsorge-Bausteine ─────────────────────────────────────────────────
        with st.expander("🏦 Vorsorge-Bausteine & Steueroptimierung"):
            st.markdown("""
            **Vertragstypen, Steuerbehandlung und KVdR:**

            | Typ | Steuer Monatsrente | Steuer Einmal | KVdR |
            |---|---|---|---|
            | **bAV** | 100 % progressiv (§ 19 / § 22 Nr. 5 EStG) | 100 % progressiv | Ja (mit Freibetrag) |
            | **Riester** | 100 % progressiv (§ 22 Nr. 5 EStG) | 100 % progressiv | Nein |
            | **Rürup** | Besteuerungsanteil (§ 22 Nr. 1 EStG) | Nicht möglich | Nein |
            | **Private RV** | Ertragsanteil (§ 22 Nr. 1 S. 3a bb) | Halbeinkünfte / Abgeltung | Nein |
            | **Lebensversicherung** | – | Halbeinkünfte / Abgeltung / steuerfrei (Altvertrag) | Nein |
            | **ETF-Depot** | – | 25 % Abgeltung auf (1−TF) × Gewinn | Nein |

            *Halbeinkünfte (§ 20 Abs. 1 Nr. 6 EStG):* gilt ausschließlich für **private** LV und RV
            (Beiträge aus versteuertem Nettoeinkommen), bei Laufzeit ≥ 12 Jahre und Alter ≥ 62
            im Auszahlungsjahr – dann wird nur 50 % des Gewinns mit dem persönlichen Steuersatz
            besteuert, statt 25 % Abgeltungsteuer auf den vollen Gewinn.
            **Für bAV gilt diese Regel nicht:** Da Beiträge steuerbefreit aus dem Bruttogehalt
            fließen, werden bei Auszahlung sowohl Beitragsanteile als auch Erträge vollständig
            mit dem persönlichen Einkommensteuersatz besteuert (§ 22 Nr. 5 EStG) –
            unabhängig von Laufzeit oder Auszahlungsalter.
            *Altvertrag:* Vertragsabschluss vor 2005 → Einmalauszahlung steuerfrei.

            ---

            **ETF-Depot – § 20 InvStG (Investmentsteuergesetz):**

            | Eigenschaft | Wert |
            |---|---|
            | Teilfreistellung thesaurierend | 30 % der Gewinne steuerfrei |
            | Steuerlast auf Gewinn | 25 % Abgeltungsteuer × 70 % (effektiv 17,5 %) |
            | ETF ausschüttend (`etf_ausschuettend=True`) | Keine Teilfreistellung; volle 25 % auf Gewinne |
            | Sparerpauschbetrag (§ 20 Abs. 9 EStG) | 1.000 €/Person/Jahr; mindert Abgeltungsteuer-Basis |

            ---

            **Riester-Förderung – §§ 83–85 EStG:**

            | Zulage | Betrag | Rechtsgrundlage |
            |---|---|---|
            | Grundzulage | 175 €/Jahr | § 84 EStG |
            | Kinderzulage (Kind ab 01.01.2008) | 300 €/Kind/Jahr | § 85 Abs. 1 S. 2 EStG |
            | Kinderzulage (Kind vor 01.01.2008) | 185 €/Kind/Jahr | § 85 Abs. 1 S. 1 EStG |

            Zulagen zählen zur **Kostenbasis** für die Ertragsermittlung (nur in Beitragsjahren,
            also vor Renteneintritt). Mindestbeitrag (§ 83 EStG): 4 % des Vorjahresbruttos
            abzgl. Zulagen; mindestens 60 €/Jahr.

            ---

            **bAV – Arbeitgeber-Pflichtzuschuss – § 1a Abs. 1a BetrAVG:**
            Seit 01.01.2022 muss der Arbeitgeber bei Entgeltumwandlung **15 %** des
            umgewandelten Betrags als Pflichtanteil zuschießen (Weitergabe der
            ersparten Sozialversicherungsbeiträge). Checkbox „AG-Pflichtzuschuss 15 %"
            im Vertragsdialog → effektive Einzahlung = Beitrag × 1,15.

            ---

            **Rürup-Rente – § 10 Abs. 1 Nr. 2b EStG:**
            Rürup-Verträge haben **kein Kapitalwahlrecht** (keine Einmalauszahlung möglich).
            Leistungen dürfen frühestens ab dem 62. Lebensjahr als monatliche Rente
            ausgezahlt werden. Übertragung und Beleihung sind ausgeschlossen (§ 10 Abs. 1
            Nr. 2b Satz 2 i.V.m. § 97 EStG). In der App daher nur „Monatliche Rente" wählbar.

            **Aufschubverzinsung:**
            Wird der Vertrag nicht zum frühestmöglichen Zeitpunkt abgerufen, wächst der
            Auszahlungsbetrag mit der eingegebenen Aufschubrendite (% p.a.) an:
            > Wert bei Startjahr = Maximalwert × (1 + Aufschubrendite)^(Aufschubjahre)

            **Einzahlungsfelder je Vertrag:**

            | Feld | Bedeutung |
            |---|---|
            | **Summe Einmaleinzahlungen** | Bereits geleistete Einmalzahlungen (Kostenbasis für Steuerberechnung) |
            | **Jährl. Einzahlung** | Laufender Jahresbeitrag ab heute bis zum Startjahr |
            | **Jährl. Dynamik (%)** | Jährliche Beitragssteigerung (z. B. 2 % für Inflation) |
            | **Jahr Beitragsbefreiung** | Ab diesem Jahr werden keine weiteren Jahresbeiträge gezählt |

            Die **Gesamteinzahlungen bis zum Startjahr** werden automatisch berechnet und
            als Kostenbasis für die Ertragsermittlung (§ 20 Abs. 1 Nr. 6 EStG, § 20 InvStG)
            verwendet. Der Range fruehestes–spätestes Startjahr bestimmt den möglichen Bereich
            der Kostenbasis.

            **Beitragsbefreiung:** Bei einem BU-Ereignis übernimmt die Versicherung die
            laufenden Beiträge. Diese Leistungen gelten steuerlich als weitere Einzahlungen
            des Versicherers (konservative Betrachtung; individuelle Behandlung im
            Einzelfall mit Steuerberater prüfen).

            **Laufende Kapitalerträge je Baustein:**
            Zinsen, Dividenden und ETF-Ausschüttungen können je Vertrag als monatlicher
            Betrag erfasst werden. Wirkung:
            - Fließen in den gemeinsamen **Abgeltungsteuer-Pool** (Sparerpauschbetrag 1.000 €/P.)
            - Bei **freiwillig GKV-Versicherten** zusätzlich KV-pflichtig (§ 240 SGB V)
            - Bei **KVdR-Mitgliedern** nur steuerlich relevant (nicht KV-pflichtig)

            **Steueroptimierung – Brute-Force-Verfahren:**
            Das System prüft alle Kombinationen aus:
            - **Startjahr** je Vertrag: bis zu 4 Stützstellen im erlaubten Bereich
            - **Auszahlungsart** je Vertrag: Einmal (100 %), Kombiniert (50/50), Monatlich (0 %)

            Für jede Kombination wird das **Netto-Gesamteinkommen über den Zeithorizont**
            (Steuer + KV berücksichtigt, Jahr für Jahr) berechnet. Die Kombination mit dem
            höchsten Gesamtnetto wird als optimal ausgegeben.

            **Strategievergleich (5 Referenzstrategien):**
            Optimal · Alles monatlich frühest · Alles monatlich spätestens ·
            Alles einmal frühest · Alles einmal spätestens

            **Berufsjahre-Simulation:** Bei Angabe eines aktuellen Bruttogehalts
            (in den Optimierungs-Parametern) startet die Simulation ab {AKTUELLES_JAHR}
            und verwendet das Gehalt als zvE-Basis in den Arbeitsjahren (§ 19 EStG, 100 % progressiv).
            Die Charts zeigen Arbeits- und Rentenphasen getrennt mit vertikaler Trennlinie am
            Renteneintritts-Jahr.
            """)

        # ── Kapitalanlage-Pool ─────────────────────────────────────────────────
        with st.expander("💼 Kapitalanlage-Pool – Als Kapitalanlage anlegen"):
            st.markdown("""
            Das Flag **„Als Kapitalanlage anlegen"** bewirkt, dass die Nettosumme einer
            Einmalauszahlung nicht sofort ausgezahlt, sondern in einen internen
            **Kapitalstock** (Pool) überführt wird.

            **Mechanismus:**
            1. Im Auszahlungsjahr wird Steuer und KV auf den Bruttobetrag berechnet.
            2. Der verbleibende **Nettobetrag** fließt in den Pool.
            3. Der Pool wächst jährlich mit der eingestellten Rendite.
            4. Der Pool wird als **gleichmäßige Annuität** über den Planungshorizont verzehrt.
            5. Der Gewinnanteil jeder Entnahme unterliegt der **Abgeltungsteuer** (25 %).

            **Gewinnanteils-Tracking:**
            > Gewinnanteil = max(0, (Pool − Kostenbasis) / Pool)

            Die Kostenbasis (netto eingezahlter Betrag) sinkt mit jeder Tilgungsentnahme;
            Renditegewinne des Pools erhöhen die Steuerlast entsprechend.

            **Darstellung im Jahresverlauf:**
            - `Src_Kapitalverzehr` (oliv) zeigt die jährliche Entnahme aus dem Pool.
            - `Kap_Pool` in den Rohdaten zeigt den Poolwert am Jahresende.

            **Bekannte Vereinfachung:**
            Bei LV- und PrivateRente-Produkten werden die Gewinne im Auszahlungsjahr
            bereits über das Halbeinkünfteverfahren oder die Abgeltungsteuer erfasst.
            Der Pool behandelt das netto eingezahlte Kapital als vollständig versteuert;
            **Pool-Renditegewinne werden beim Verzehr dennoch nochmals mit Abgeltungsteuer
            belastet.** Dies führt zu einer konservativen (leicht zu hohen) Steuerbelastung
            für LV/PrivateRente als Kapitalanlage. Für steuerfreie Altverträge (vor 2005)
            tritt diese Doppelbelastung nicht auf (da die Erstgewinne steuerfrei waren).

            **Empfehlung:** Das Feature eignet sich besonders für Produkte mit steuerfreier
            oder niedrig besteuerter Erstentnahme (Altverträge, ETF-TF-Anteil), um eine
            Steuerprogression durch große Einmalzahlungen zu glätten.
            """)

        # ── Mieteinnahmen ──────────────────────────────────────────────────────
        with st.expander("🏠 Mieteinnahmen – § 21 EStG"):
            st.markdown("""
            Mieteinnahmen werden als **gemeinsamer Haushaltswert** eingegeben und behandelt.

            - **Eingabe:** Nettomieteinnahmen nach abzugsfähigen Werbungskosten
              (Abschreibung, Zinsen, Reparaturen, Verwaltungskosten)
            - **Steuerpflicht:** Voll zum zvE addiert, kein Besteuerungsanteil
            - **KV-Pflicht:** Keine (Mieteinnahmen sind keine Versorgungsbezüge)
            - **Steigerung:** Jährliche Erhöhung parametrierbar (z. B. 1,5 % p.a.)

            **Progressionseffekt:**
            Mieteinnahmen erhöhen das zvE und damit den Grenzsteuersatz auf alle anderen
            Einkünfte. Die Progressionszone-Ampel im Dashboard berücksichtigt die
            Mieteinnahmen automatisch.
            """)

        # ── Kapitalverzehr ─────────────────────────────────────────────────────
        with st.expander("💰 Kapitalverzehr-Kalkulator (Entnahme-Tab)"):
            st.markdown("""
            Der Kapitalverzehr-Kalkulator (erreichbar im Tab **Entnahme-Optimierung**) vergleicht
            zwei Strategien für das angesparte Kapital:

            **Strategie 1 – Kapitalverzehr (Annuität):**
            Das Kapital wird über die gewählte Laufzeit aufgezehrt. Die monatliche Rate
            ergibt sich aus der Annuitätsformel:
            > Monatsrate = K × r_m / (1 − (1 + r_m)^(−n))

            mit K = Kapital, r_m = Monatsrendite, n = Laufzeit in Monaten.
            Nach Ablauf der Laufzeit ist das Kapital aufgebraucht (kein Erbe).

            **Strategie 2 – Externe monatliche Rente:**
            Eine feste monatliche Zahlung aus einem externen Produkt (z. B. privater RV).
            Der **Break-Even** zeigt, nach wie vielen Jahren die Annuität die externe Rente
            kumuliert übersteigt.
            """)

        # ── Szenarien ──────────────────────────────────────────────────────────
        with st.expander("🔮 Szenarien (Simulation-Tab)"):
            st.markdown("""
            | Szenario | Rentenanpassung p.a. | Kapitalrendite p.a. |
            |---|---|---|
            | Pessimistisch | 1,0 % | 3,0 % |
            | Neutral | Eigene Eingabe | Eigene Eingabe |
            | Optimistisch | 3,0 % | 7,0 % |

            **Exakte Jahres-Simulation:** Jedes Szenario wird mit vollständiger
            `_netto_ueber_horizont`-Simulation berechnet (nicht Näherungsformel).
            Dabei werden szenariospezifische `rentenanpassung_pa` und `rendite_pa`
            verwendet – Steuer und KV werden Jahr für Jahr korrekt ermittelt.

            Die Renteneintrittsalter-Sensitivitätsanalyse zeigt, wie sich eine Verschiebung
            des Renteneintritts (60–70 Jahre) auf Nettorente und Kapital auswirkt.

            **Rentenanpassung im Jahresverlauf:** In der Entnahme-Optimierung wird die
            gesetzliche Rente im Simulationshorizont jährlich um `rentenanpassung_pa` erhöht.
            Für Pensionäre gilt 0 % (keine DRV-Rentenanpassung).
            """)

        # ── Gesetzesreferenz ───────────────────────────────────────────────────
        st.divider()
        with st.expander("⚖️ Alle berücksichtigten Gesetze – Kurzreferenz"):
            st.markdown("""
            | Paragraph | Gesetz | Wirkung in der App |
            |---|---|---|
            | § 9a | EStG | Werbungskosten-Pauschbetrag 102 €/Jahr (Rentner) |
            | § 10 Abs. 1 Nr. 2b | EStG | Rürup: kein Kapitalwahlrecht, nur Monatsrente ab 62 |
            | § 10c | EStG | Sonderausgaben-Pauschbetrag 36 €/Jahr |
            | § 19 | EStG | Arbeitslohn (Gehalt in Berufsjahren, Beamtenpension): 100 % progressiv |
            | § 19 Abs. 2 | EStG | Versorgungsfreibetrag für Beamtenpensionen; sinkt auf 0 % bis 2040 |
            | § 20 Abs. 1 Nr. 6 | EStG | LV / Private RV Einmal: Halbeinkünfte bei ≥ 12 J. + Alter ≥ 62; sonst Abgeltungsteuer |
            | § 20 Abs. 9 | EStG | Sparerpauschbetrag 1.000 €/Person/Jahr auf Abgeltungsteuer-Basis |
            | § 21 | EStG | Mieteinnahmen: voll progressiv steuerpflichtig, keine KV-Pflicht |
            | § 22 Nr. 1 S. 3a aa | EStG | Besteuerungsanteil gesetzliche / Rürup-Rente; steigt bis 2058 auf 100 % |
            | § 22 Nr. 1 S. 3a bb | EStG | Ertragsanteil private RV-Rente, DUV, BUV (altersabhängig, z. B. 22 % mit 60) |
            | § 22 Nr. 5 | EStG | bAV und Riester: volle nachgelagerte Besteuerung; keine 12-Jahres-Regel |
            | § 24a | EStG | Altersentlastungsbetrag ab 65: Prozentsatz sinkt jährlich bis 2040 auf 0 |
            | § 25 | EStG | Getrenntveranlagung: P1 und P2 werden einzeln veranlagt |
            | § 32a | EStG | Grundtarif 2024: 5 Zonen, 14–45 %; bildet Basis aller ESt-Berechnungen |
            | § 32a Abs. 5 | EStG | Splitting: 2 × ESt(zvE/2); vorteilhaft bei ungleichen Einkommen |
            | § 51a | EStG | Solidaritätszuschlag 5,5 % (Freigrenze 17.543 €) + Kirchensteuer 8/9 % |
            | § 83 | EStG | Riester-Mindestbeitrag: 4 % Vorjahresbrutto − Zulagen; mind. 60 €/Jahr |
            | § 84 | EStG | Riester-Grundzulage 175 €/Jahr |
            | § 85 Abs. 1 S. 1 | EStG | Riester-Kinderzulage 185 €/Kind/Jahr (Kinder vor 2008) |
            | § 85 Abs. 1 S. 2 | EStG | Riester-Kinderzulage 300 €/Kind/Jahr (Kinder ab 2008) |
            | § 20 | InvStG | ETF-Teilfreistellung 30 % (thesaurierend); 0 % bei ausschüttenden ETFs |
            | § 1a Abs. 1a | BetrAVG | Arbeitgeber-Pflichtzuschuss 15 % bei bAV-Entgeltumwandlung ab 2022 |
            | § 18 Abs. 1 | SGB IV | Durchschnittsentgelt 43.142 €/Jahr (2024); Basis für Rentenpunkte |
            | § 5 Abs. 1 Nr. 11 | SGB V | KVdR-Pflichtmitgliedschaft: nur § 229-Einkünfte beitragspflichtig |
            | § 226 Abs. 2 | SGB V | bAV-Freibetrag 187,25 €/Mon. (nur für KVdR-Mitglieder) |
            | § 229 Abs. 1 Nr. 1 | SGB V | Beamtenpension: voller Betrag als KV-Basis, kein Freibetrag |
            | § 229 Abs. 1 S. 3 | SGB V | bAV-Einmalauszahlung: KV-Basis auf 120 Monate verteilt |
            | § 240 | SGB V | Freiwillig GKV: alle Einnahmen beitragspflichtig (ohne bAV-Freibetrag) |
            | § 240 Abs. 4 | SGB V | Mindest-BMG freiwillig: 1.096,67 €/Mon. (auch bei niedrigerem Einkommen) |
            | § 36 | SGB VI | Wartezeit 35 Jahre → Frühverrentung ab 63 möglich (mit Abschlag) |
            | § 46 Abs. 2 | SGB VI | Großes Witwengeld: 55 % der gesetzl. Bruttorente des Verstorbenen |
            | § 77 | SGB VI | Rentenabschlag 0,3 %/Monat vor individueller Regelaltersgrenze |
            | § 97 | SGB VI | Einkommensanrechnung Witwenrente: Freibetrag 26.400 €/Jahr; 40 % Abzug |
            | § 235 Abs. 2 | SGB VI | Regelaltersgrenze: 65 (≤ 1946) bis 67 (≥ 1964); Übergangstabelle für 1947–1963 |
            | § 41 | SGB XII | Grundsicherung im Alter: Hinweis bei proj. Nettorente < 1.100 €/Mon. |
            | § 55 Abs. 3a | SGB XI | PV-Kinderstaffelung: 1 Kind 3,4 %; je weiteres Kind −0,25 % (max. −1,0 %) |
            """)

        # ── Vereinfachungen ────────────────────────────────────────────────────
        st.divider()
        st.subheader("Bekannte Vereinfachungen")
        st.warning("""
        Die folgenden Punkte sind in der Simulation vereinfacht oder nicht implementiert.
        Für verbindliche Auskünfte empfehlen wir die Beratung durch einen Steuerberater
        oder die Deutsche Rentenversicherung.
        """)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("""
            **Rente / Pension:**
            - Kein expliziter Zugangsfaktor für Spätverrentung
            - Keine Unterscheidung Ost/West-Rentenwert
            - Keine Mütterrente, Grundrente, Wartezeiten
            - Versorgungsfreibetrag: feste RAG 67; Übergangsregelungen für Jahrgänge vor 1964 nicht implementiert

            **Steuer:**
            - Keine Günstigerprüfung bei Kapitalerträgen
            - Abgeltungsteuer LV/PrivateRV: 25 % ohne Soli/KiSt
            - Kirchensteuer auf Abgeltungsteuer (Kapitalerträge) nicht berücksichtigt
            - Kapitalanlage-Pool (LV/PrivateRente): Pool-Renditegewinne werden nochmals mit Abgeltungsteuer belastet (konservativ, s. Kapitalanlage-Pool-Expander)
            """)
        with col2:
            st.markdown("""
            **KV/PV:**
            - PKV-Beitragszuschuss der DRV nicht explizit ausgewiesen
            - Beitragsentlastungsmodelle (PKV) nicht berücksichtigt
            - Beihilfesatz fix 70 % (landesspezifische Abweichungen nicht modelliert)

            **Allgemein:**
            - Inflation konfigurierbar im Dashboard (Default 2 % p.a.; gilt nur für Kaufkraft-Anzeige)
            - Keine Erbschafts-/Schenkungssteuer
            - Keine anderen Einkunftsarten (Wertpapiererträge, Selbständigkeit)
            - Steueroptimierung ohne individuelle Freibeträge (Soli und KiSt werden berücksichtigt)
            """)

        # ── Rechtlicher Hinweis ────────────────────────────────────────────────
        st.divider()
        st.error("""
        ⚠️ **Haftungsausschluss**

        Diese Simulation dient ausschließlich **Informations- und Planungszwecken**.
        Sie stellt keine Steuer-, Rechts- oder Anlageberatung dar und ersetzt keine
        professionelle Beratung. Alle Berechnungen basieren auf vereinfachten Annahmen
        und den Gesetzesständen des Jahres 2024. Zukünftige Gesetzesänderungen (Rentenrecht,
        Steuerrecht, SGB V) können die tatsächlichen Auszahlungen erheblich verändern.

        Für verbindliche Aussagen wenden Sie sich an:
        - **Deutsche Rentenversicherung** (DRV): [www.deutsche-rentenversicherung.de](https://www.deutsche-rentenversicherung.de)
        - **Steuerberater** für individuelle Steuerplanung
        - **Krankenkasse** für aktuelle Beitragssätze und KVdR-Berechnung
        """)

        st.caption(
            f"Gesetzesstand: 2024 · Rentenwert West: {RENTENWERT_2024:.2f} € · "
            f"Grundfreibetrag: {GRUNDFREIBETRAG_2024:,} € · "
            f"bAV-Freibetrag KVdR: {BAV_FREIBETRAG_MONATLICH:.2f} €/Mon. · "
            f"Mindest-BMG freiwillig: {MINDEST_BMG_FREIWILLIG_MONO:,.2f} €/Mon. · "
            f"BBG KV: {BBG_KV_MONATLICH:,.0f} €/Mon. · "
            f"Simulationsjahr: {AKTUELLES_JAHR}"
        )
