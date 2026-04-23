"""Dokumentations-Tab – Erläuterung der Berechnungsgrundlagen und Funktionen."""

import streamlit as st

from engine import (
    RENTENWERT_2024,
    GRUNDFREIBETRAG_2024,
    WERBUNGSKOSTEN_PAUSCHBETRAG,
    SONDERAUSGABEN_PAUSCHBETRAG,
    BAV_FREIBETRAG_MONATLICH,
    BBG_KV_MONATLICH,
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

        - Gesetzlicher Rente (DRV/BFA) auf Basis von Rentenpunkten
        - Zusatzversorgung (bAV, private Rentenversicherung, Riester, Lebensversicherung)
        - Sparkapital und monatlicher Sparrate bis zum Renteneintritt
        - Einkommensteuer nach §32a EStG (Grundtarif 2024)
        - Kranken- und Pflegeversicherung in der Rente (GKV/PKV)
        - Mieteinnahmen als Haushaltseinkommen (§21 EStG)
        - Ehegatten-Splitting bei Zusammenveranlagung (§32a Abs. 5 EStG)
        """)

        st.divider()

        # ── Gesetzliche Rente ──────────────────────────────────────────────────
        with st.expander("📌 Gesetzliche Rente – Berechnung", expanded=True):
            st.markdown(f"""
            **Formel:**
            > Bruttorente = Gesamtpunkte × Rentenwert × Rentenanpassungsfaktor

            | Parameter | Erläuterung |
            |---|---|
            | **Gesamtpunkte** | Aktuelle Rentenpunkte + (Punkte/Jahr × Restjahre bis Rente) |
            | **Rentenwert** | {RENTENWERT_2024:.2f} € / Punkt (West, Stand 01.07.2024) |
            | **Rentenanpassung** | Eingabe in % p.a.; wird über Restjahre aufgezinst |

            **Hinweis:** Frühverrentung (vor 67) oder Spätverrentung (nach 67) verändern
            die Gesamtpunkte über die unterschiedliche Ansparzeit. Ein expliziter
            Zugangsfaktor (±0,3 %/Monat) ist vereinfacht nicht implementiert.
            """)

        # ── Einkommensteuer ────────────────────────────────────────────────────
        with st.expander("🧾 Einkommensteuer – §32a EStG Grundtarif 2024"):
            st.markdown(f"""
            Das zu versteuernde Einkommen (zvE) wird wie folgt ermittelt:

            > zvE = Jahresbruttorente × **Besteuerungsanteil** − Werbungskosten-Pauschbetrag − Sonderausgaben-Pauschbetrag

            | Pauschbetrag | Wert |
            |---|---|
            | Werbungskosten (§9a EStG) | {WERBUNGSKOSTEN_PAUSCHBETRAG} €/Jahr |
            | Sonderausgaben (§10c EStG) | {SONDERAUSGABEN_PAUSCHBETRAG} €/Jahr |
            | Grundfreibetrag (§32a EStG) | {GRUNDFREIBETRAG_2024:,} €/Jahr |

            **Steuertarif 2024 (§32a EStG):**

            | zvE | Formel |
            |---|---|
            | ≤ {GRUNDFREIBETRAG_2024:,} € | 0 € |
            | {GRUNDFREIBETRAG_2024:,} – 17.005 € | (928,37 · y + 1.400) · y, mit y = (zvE − {GRUNDFREIBETRAG_2024:,}) / 10.000 |
            | 17.005 – 66.760 € | (176,64 · z + 2.397) · z + 1.025,38, mit z = (zvE − 17.005) / 10.000 |
            | 66.760 – 277.825 € | 42 % × zvE − 9.972,98 € |
            | > 277.825 € | 45 % × zvE − 18.307,73 € |
            """)

        # ── Besteuerungsanteil ─────────────────────────────────────────────────
        with st.expander("📈 Besteuerungsanteil der Rente – §22 EStG / JStG 2022"):
            st.markdown("""
            Der Besteuerungsanteil bestimmt, welcher Prozentsatz der gesetzlichen Rente
            steuerpflichtig ist.

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
        with st.expander("👥 Ehegatten-Splitting – §32a Abs. 5 EStG"):
            st.markdown("""
            Beim Splittingtarif wird das **gemeinsame zvE halbiert**, die Steuer nach
            Grundtarif berechnet und **verdoppelt**:

            > Splitting-Steuer = 2 × ESt(zvE_gesamt / 2)

            **Vorteil:** Entsteht bei ungleichen Einkommen beider Partner, da die progressive
            Steuerkurve abgeflacht wird. Bei zwei gleich hohen Einkommen ist kein Vorteil vorhanden.

            **Mieteinnahmen im Splitting:**
            - Zusammenveranlagung: Mieteinnahmen werden zum gemeinsamen zvE addiert, dann gesplittet.
            - Getrennte Veranlagung: Mieteinnahmen werden 50/50 auf beide Partner aufgeteilt.
            """)

        # ── GKV/PKV ────────────────────────────────────────────────────────────
        with st.expander("🏥 Kranken- und Pflegeversicherung in der Rente (KVdR)"):
            st.markdown(f"""
            **Gesetzlich versichert (GKV / KVdR):**

            | Beitragsart | Satz | Träger |
            |---|---|---|
            | KV-Basis | 7,3 % | Rentner zahlt die Hälfte; DRV übernimmt die andere Hälfte |
            | KV-Zusatzbeitrag | ½ × kassenbezogener Zusatzbeitrag | Rentner |
            | PV mit Kindern | 3,4 % | Rentner trägt voll |
            | PV ohne Kinder | 4,0 % | Rentner trägt voll |

            **Beitragsbemessungsgrundlage:**
            - Gesetzliche Rente: voll einbezogen
            - **bAV (Versorgungsbezüge):** KVdR-pflichtig, aber **Freibetrag {BAV_FREIBETRAG_MONATLICH:.2f} €/Mon.** (§226 Abs. 2 SGB V)
            - **bAV-Einmalauszahlung:** KV-Basis wird auf 10 Jahre verteilt (§229 Abs. 1 S. 3 SGB V: 1/120 pro Monat)
            - **Private RV / Riester / LV:** Nicht KVdR-pflichtig
            - **Mieteinnahmen:** Nicht KVdR-pflichtig
            - **BBG-Deckelung:** KV-Beitragsbemessungsgrundlage max. **{BBG_KV_MONATLICH:,.0f} €/Mon.**

            **Privat versichert (PKV):**
            Der PKV-Beitrag wird als fixer Monatsbetrag eingegeben. Die Deutsche Rentenversicherung
            gewährt einen pauschalen Beitragszuschuss (halber GKV-Satz auf die Renteneinnahmen) –
            dieser ist in der Simulation vereinfacht nicht gesondert ausgewiesen.
            """)

        # ── Vorsorge-Bausteine ─────────────────────────────────────────────────
        with st.expander("🏦 Vorsorge-Bausteine & Steueroptimierung"):
            st.markdown("""
            **Vertragstypen und KV-Behandlung:**

            | Typ | Steuer | KVdR-pflichtig |
            |---|---|---|
            | bAV | Voll (§19 Abs. 2 / §22 Nr. 5 EStG) | Ja (mit Freibetrag) |
            | Riester-Rente | Voll (§22 Nr. 5 EStG) | Nein |
            | Rürup/Private RV | Vereinfacht voll (konservativ) | Nein |
            | Lebensversicherung | Vereinfacht voll (konservativ) | Nein |

            **Aufschubverzinsung:**
            Wird der Vertrag nicht zum frühestmöglichen Zeitpunkt abgerufen, wächst der
            Auszahlungsbetrag mit der eingegebenen Aufschubrendite (% p.a.) an:
            > Wert bei Startjahr = Maximalwert × (1 + Aufschubrendite)^(Aufschubjahre)

            **Steueroptimierung – Brute-Force-Verfahren:**
            Das System prüft alle Kombinationen aus:
            - **Startjahr** je Vertrag: bis zu 4 gleichmäßig verteilte Stützstellen im erlaubten Bereich
            - **Auszahlungsart** je Vertrag: Einmal (100 %), Kombiniert (50/50), Monatlich (0 %)

            Für jede Kombination wird das **Netto-Gesamteinkommen über den Zeithorizont**
            (Steuer + KV berücksichtigt, Jahr für Jahr) berechnet. Die Kombination mit dem
            höchsten Gesamtnetto wird als optimal ausgegeben.

            **Annuitäts-Formel** (für Kapitalverzehr):
            > Monatsrate = K × (r_m) / (1 − (1 + r_m)^(−n))

            mit K = Kapital, r_m = Monatsrendite, n = Laufzeit in Monaten.
            """)

        # ── Mieteinnahmen ──────────────────────────────────────────────────────
        with st.expander("🏠 Mieteinnahmen – §21 EStG"):
            st.markdown("""
            Mieteinnahmen werden als **gemeinsamer Haushaltswert** eingegeben und behandelt.

            - **Eingabe:** Nettomieteinnahmen nach abzugsfähigen Werbungskosten
              (Abschreibung, Zinsen, Reparaturen, Verwaltungskosten)
            - **Steuerpflicht:** Voll zum zvE addiert, kein Besteuerungsanteil
            - **KV-Pflicht:** Keine (Mieteinnahmen sind keine Versorgungsbezüge)
            - **Steigerung:** Jährliche Erhöhung parametrierbar (z. B. 1,5 % p.a.)

            **Veranlagungseffekt:**
            Bei der Steueroptimierung erhöhen Mieteinnahmen die Steuerprogression –
            zusätzliche Vertragsauszahlungen werden damit marginaler besteuert.
            Die optimale Auszahlungsstrategie kann sich dadurch verändern.
            """)

        # ── Kapital vs. Rente ──────────────────────────────────────────────────
        with st.expander("💰 Kapital vs. Rente (Auszahlung-Tab)"):
            st.markdown("""
            Der Tab vergleicht zwei Strategien für das angesparte Kapital:

            **Strategie 1 – Kapitalverzehr (Annuität):**
            Das Kapital wird über die gewählte Laufzeit aufgezehrt. Die monatliche Rate
            ergibt sich aus der Annuitätsformel (s. o.). Nach Ablauf der Laufzeit ist das
            Kapital aufgebraucht (kein Erbe).

            **Strategie 2 – Externe monatliche Rente:**
            Eine feste monatliche Zahlung aus einem externen Produkt (z. B. privater RV).
            Das Kapital bleibt unangetastet (kann vererbt werden).

            Der **Break-Even** zeigt, nach wie vielen Jahren die Annuität die externe Rente
            kumuliert übersteigt – ab diesem Punkt lohnt sich die Annuität.
            """)

        # ── Szenarien ──────────────────────────────────────────────────────────
        with st.expander("🔮 Szenarien (Simulation-Tab)"):
            st.markdown("""
            | Szenario | Rentenanpassung p.a. | Kapitalrendite p.a. |
            |---|---|---|
            | Pessimistisch | 1,0 % | 3,0 % |
            | Neutral | Eigene Eingabe | Eigene Eingabe |
            | Optimistisch | 3,0 % | 7,0 % |

            Die Renteneintrittsalter-Sensitivitätsanalyse zeigt, wie sich eine Verschiebung
            des Renteneintritts (60–70 Jahre) auf Nettorente und Kapital auswirkt.
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
            **Rente:**
            - Kein Zugangsfaktor (±0,3 %/Monat bei Früh-/Spätverrentung)
            - Keine Unterscheidung Ost/West-Rentenwert
            - Keine Mütterrente, Grundrente, Wartezeiten

            **Steuer:**
            - Private RV / LV: vereinfacht voll steuerpflichtig (konservativ); korrekt wäre Ertragsanteil nach §22 Nr. 1 S. 3 EStG
            - Kein Solidaritätszuschlag (entfällt ab 2021 für die meisten Rentner)
            - Keine Kirchensteuer
            - Keine Günstigerprüfung bei Kapitalerträgen
            """)
        with col2:
            st.markdown("""
            **KV/PV:**
            - `berechne_rente` wendet Besteuerungsanteil vereinfacht auch auf die Zusatzrente an
              (korrekt: bAV ist voll steuerpflichtig)
            - PKV-Beitragszuschuss der DRV nicht explizit ausgewiesen
            - Beitragsentlastungsmodelle (PKV) nicht berücksichtigt

            **Allgemein:**
            - Keine Inflation auf Auszahlungswerte (Realwert nicht ausgewiesen)
            - Keine Erbschafts-/Schenkungssteuer
            - Keine anderen Einkunftsarten (Wertpapiererträge, Selbständigkeit)
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
            f"BBG KV: {BBG_KV_MONATLICH:,.0f} €/Mon. · "
            f"Simulationsjahr: {AKTUELLES_JAHR}"
        )
