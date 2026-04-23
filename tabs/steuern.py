"""Steuern & KV-Tab – detaillierte Steuer- und Krankenversicherungsberechnung."""

import plotly.graph_objects as go
import streamlit as st

from engine import (
    GRUNDFREIBETRAG_2024,
    SONDERAUSGABEN_PAUSCHBETRAG,
    WERBUNGSKOSTEN_PAUSCHBETRAG,
    Profil,
    RentenErgebnis,
    besteuerungsanteil,
)


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis) -> None:
    with T["Steuern"]:
        st.header("🧾 Steuern & Krankenversicherung")

        # ── Einkommensteuer ───────────────────────────────────────────────────
        st.subheader("Einkommensteuer auf die Rente")

        jahresbrutto = ergebnis.brutto_monatlich * 12
        besteuerter_anteil = jahresbrutto * ergebnis.besteuerungsanteil
        abzuege = WERBUNGSKOSTEN_PAUSCHBETRAG + SONDERAUSGABEN_PAUSCHBETRAG
        unterhalb_freibetrag = max(0.0, besteuerter_anteil - GRUNDFREIBETRAG_2024 - abzuege)

        col1, col2 = st.columns([1, 1])

        with col1:
            st.markdown("**Berechnung Schritt für Schritt:**")
            rows = {
                "Jahresbruttorente":                    f"{jahresbrutto:,.0f} €",
                f"× Besteuerungsanteil ({ergebnis.besteuerungsanteil:.1%})":
                                                        f"{besteuerter_anteil:,.0f} €",
                "− Werbungskosten-Pauschbetrag":        f"−{WERBUNGSKOSTEN_PAUSCHBETRAG} €",
                "− Sonderausgaben-Pauschbetrag":        f"−{SONDERAUSGABEN_PAUSCHBETRAG} €",
                "− Grundfreibetrag":                    f"−{GRUNDFREIBETRAG_2024:,} €",
                "**= Zu versteuerndes Einkommen**":     f"**{ergebnis.zvE_jahres:,.0f} €**",
                "**Jahressteuer**":                     f"**{ergebnis.jahressteuer:,.0f} €**",
                "**Steuer / Monat**":                   f"**{ergebnis.steuer_monatlich:,.0f} €**",
                "**Effektiver Steuersatz**":            f"**{ergebnis.effektiver_steuersatz:.1%}**",
            }
            for label, value in rows.items():
                c_l, c_r = st.columns([2, 1])
                c_l.markdown(label)
                c_r.markdown(value)

        with col2:
            fig_st = go.Figure(go.Bar(
                x=["Jahresbrutto", "Besteuerter\nAnteil", "Steuerlast", "Netto (Jahr)"],
                y=[
                    jahresbrutto,
                    besteuerter_anteil,
                    ergebnis.jahressteuer,
                    ergebnis.netto_monatlich * 12,
                ],
                marker_color=["#90CAF9", "#FFF176", "#EF9A9A", "#A5D6A7"],
                text=[
                    f"{v:,.0f} €"
                    for v in [jahresbrutto, besteuerter_anteil,
                               ergebnis.jahressteuer, ergebnis.netto_monatlich * 12]
                ],
                textposition="outside",
            ))
            fig_st.update_layout(
                template="plotly_white",
                height=340,
                yaxis=dict(title="€ / Jahr", tickformat=",.0f"),
                margin=dict(l=0, r=10, t=10, b=10),
            )
            st.plotly_chart(fig_st, use_container_width=True)

        st.divider()

        # ── Besteuerungsanteil-Entwicklung ────────────────────────────────────
        st.subheader("Entwicklung des Besteuerungsanteils (§ 22 EStG)")
        jahre = list(range(2020, 2062))
        anteile = [besteuerungsanteil(j) * 100 for j in jahre]

        fig_ba = go.Figure()
        fig_ba.add_trace(go.Scatter(
            x=jahre, y=anteile,
            line=dict(color="#2196F3", width=2),
            hovertemplate="%{x}: %{y:.1f} %<extra></extra>",
            name="Besteuerungsanteil",
        ))
        fig_ba.add_vline(
            x=profil.eintritt_jahr,
            line_dash="dash",
            line_color="#FF9800",
            annotation_text=f"Ihr Eintritt {profil.eintritt_jahr}: {ergebnis.besteuerungsanteil:.1%}",
            annotation_position="top left",
        )
        fig_ba.update_layout(
            template="plotly_white",
            height=280,
            yaxis=dict(title="Besteuerungsanteil (%)", range=[40, 105], ticksuffix=" %"),
            xaxis=dict(title="Renteneintritt"),
            margin=dict(l=10, r=10, t=30, b=10),
            showlegend=False,
        )
        st.plotly_chart(fig_ba, use_container_width=True)

        st.info(
            "**Jahressteuergesetz 2022 (JStG 2022):** Seit 2023 steigt der Besteuerungsanteil "
            "nur noch um **0,5 % p.a.** (statt 1 %). Vollständige Besteuerung erst ab dem "
            "Renteneintritt **2058**. Die Reform entlastet vor allem jüngere Jahrgänge."
        )

        st.divider()

        # ── Krankenversicherung ───────────────────────────────────────────────
        st.subheader("Krankenversicherung in der Rente")

        if profil.krankenversicherung == "GKV":
            kv_satz = 0.073 + profil.gkv_zusatzbeitrag / 2
            pv_satz = 0.034 if profil.kinder else 0.040
            gesamt_satz = kv_satz + pv_satz

            c1, c2, c3, c4 = st.columns(4)
            c1.metric(
                "KV-Beitragssatz (Rentner)",
                f"{kv_satz:.2%}",
                help="7,3 % Basis + halber Zusatzbeitrag. Die DRV übernimmt die andere Hälfte.",
            )
            c2.metric(
                "PV-Beitragssatz",
                f"{pv_satz:.2%}",
                help="3,4 % mit Kindern / 4,0 % ohne Kinder. Rentner tragen den vollen Beitrag.",
            )
            c3.metric("Gesamtbeitragssatz", f"{gesamt_satz:.2%}")
            c4.metric("Monatlicher Beitrag", f"{ergebnis.kv_monatlich:,.0f} €")

            st.markdown("""
            **KVdR (Krankenversicherung der Rentner):**
            - Rentner zahlen **die Hälfte** des Krankenversicherungsbeitrags (7,3 % + ½ Zusatzbeitrag)
            - Die **Deutsche Rentenversicherung** übernimmt die andere Hälfte
            - Die **Pflegeversicherung** trägt der Rentner vollständig selbst
            - Beitragsbemessungsgrundlage: alle Renteneinnahmen (gesetzl. + bAV)
            """)

        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("PKV-Monatsbeitrag", f"{profil.pkv_beitrag:,.0f} €")
            c2.metric("PKV-Jahresbeitrag", f"{profil.pkv_beitrag * 12:,.0f} €")
            # Simulierter GKV-Vergleich
            kv_satz_gkv = 0.073 + 0.017 / 2
            pv_satz_gkv = 0.034 if profil.kinder else 0.040
            gkv_sim = ergebnis.brutto_monatlich * (kv_satz_gkv + pv_satz_gkv)
            diff = profil.pkv_beitrag - gkv_sim
            c3.metric(
                "GKV-Beitrag (simuliert)", f"{gkv_sim:,.0f} €",
                delta=f"{diff:+,.0f} € vs. PKV",
                delta_color="inverse",
            )

            if diff > 0:
                st.error(
                    f"PKV kostet **{diff:,.0f} €/Monat** mehr als die simulierte GKV "
                    f"({diff * 12:,.0f} €/Jahr). Ein Rückwechsel in die GKV ist im Rentenalter "
                    "i.d.R. nicht möglich – frühzeitig planen!"
                )
            else:
                st.success(
                    f"PKV ist **{-diff:,.0f} €/Monat** günstiger als die simulierte GKV "
                    f"({-diff * 12:,.0f} €/Jahr)."
                )

            # PKV vs GKV Chart
            fig_kv = go.Figure(go.Bar(
                x=["PKV (Eingabe)", "GKV (simuliert, Ø-Zusatzbeitrag 1,7 %)"],
                y=[profil.pkv_beitrag, gkv_sim],
                marker_color=["#EF9A9A" if diff > 0 else "#A5D6A7", "#A5D6A7"],
                text=[f"{v:,.0f} €/Mon." for v in [profil.pkv_beitrag, gkv_sim]],
                textposition="outside",
            ))
            fig_kv.update_layout(
                template="plotly_white",
                height=300,
                yaxis=dict(title="€ / Monat"),
                margin=dict(l=10, r=10, t=10, b=10),
            )
            st.plotly_chart(fig_kv, use_container_width=True)

            st.warning(
                "⚠️ **PKV im Rentenalter:** PKV-Beiträge steigen mit Alter und Leistungsnutzung "
                "erheblich. Bei der Deutschen Rentenversicherung gibt es keinen Arbeitgeberzuschuss "
                "– nur einen pauschalen Beitragszuschuss (halber GKV-Beitrag auf die Rente)."
            )

        st.caption(
            "⚠️ Vereinfachte Berechnung. Individuelle Steuer- und KV-Situation kann abweichen. "
            "Steuerberatung und Sozialversicherungsberatung empfohlen."
        )
