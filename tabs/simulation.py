"""Simulation-Tab – Szenarien-Vergleich und Kapitalentwicklung."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    AKTUELLES_JAHR, Profil, RentenErgebnis,
    berechne_haushalt, kapitalwachstum, simuliere_szenarien,
)

_FARBEN = {
    "Pessimistisch": "#F44336",
    "Neutral":       "#2196F3",
    "Optimistisch":  "#4CAF50",
}

_PARAMS = {
    "Pessimistisch": (0.01, 0.03),
    "Neutral":       (None, None),
    "Optimistisch":  (0.03, 0.07),
}


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis,
           profil2: Profil | None = None,
           ergebnis2: RentenErgebnis | None = None,
           veranlagung: str = "Getrennt",
           mieteinnahmen: float = 0.0) -> None:
    with T["Simulation"]:
        st.header("🔮 Szenarien-Simulation")

        hat_partner = profil2 is not None and ergebnis2 is not None
        wahl = "Person 1"
        if hat_partner:
            wahl = st.radio("Ansicht", ["Person 1", "Person 2", "Zusammen"],
                            horizontal=True, key="sim_person")

        zusammen_modus = wahl == "Zusammen"

        if wahl == "Person 2":
            profil, ergebnis = profil2, ergebnis2

        if zusammen_modus:
            sz1 = simuliere_szenarien(profil)
            sz2 = simuliere_szenarien(profil2)
            szenarien = sz1   # nur als Fallback für Kapitalchart
        else:
            szenarien = simuliere_szenarien(profil)

        # ── Szenario-Vergleich Tabelle ────────────────────────────────────────
        st.subheader("Vergleich der drei Szenarien")
        rows = []
        for name in ["Pessimistisch", "Neutral", "Optimistisch"]:
            ren_pa, kap_pa = _PARAMS[name]
            if ren_pa is None:
                ren_pa = profil.rentenanpassung_pa
                kap_pa = profil.rendite_pa
            if zusammen_modus:
                hh = berechne_haushalt(sz1[name], sz2[name], veranlagung, mieteinnahmen)
                kapital = (sz1[name].kapital_bei_renteneintritt
                           + sz2[name].kapital_bei_renteneintritt)
                rows.append({
                    "Szenario": name,
                    "Rentenanpassung p.a.": f"{ren_pa:.1%}".replace(".", ","),
                    "Kapitalrendite p.a.": f"{kap_pa:.1%}".replace(".", ","),
                    "Brutto Haushalt (€/Mon.)": _de(hh["brutto_gesamt"]),
                    "Netto Haushalt (€/Mon.)": _de(hh["netto_gesamt"]),
                    "Kapital gesamt (€)": _de(kapital),
                })
            else:
                erg = szenarien[name]
                rows.append({
                    "Szenario": name,
                    "Rentenanpassung p.a.": f"{ren_pa:.1%}".replace(".", ","),
                    "Kapitalrendite p.a.": f"{kap_pa:.1%}".replace(".", ","),
                    "Brutto (€/Mon.)": _de(erg.brutto_monatlich),
                    "Netto (€/Mon.)": _de(erg.netto_monatlich),
                    "Kapital bei Eintritt (€)": _de(erg.kapital_bei_renteneintritt),
                    "Rentenpunkte": f"{erg.gesamtpunkte:.1f}".replace(".", ","),
                })
        st.dataframe(
            pd.DataFrame(rows).set_index("Szenario"),
            use_container_width=True,
        )

        st.divider()

        # ── Nettorente / Haushalt Szenarien ───────────────────────────────────
        col_l, col_r = st.columns(2)

        with col_l:
            if zusammen_modus:
                st.subheader("Netto Haushalt im Vergleich")
                netto_vals = [
                    berechne_haushalt(sz1[n], sz2[n], veranlagung, mieteinnahmen)["netto_gesamt"]
                    for n in ["Pessimistisch", "Neutral", "Optimistisch"]
                ]
                y_title = "Netto Haushalt (€/Monat)"
            else:
                st.subheader("Nettorente im Vergleich")
                netto_vals = [szenarien[n].netto_monatlich
                              for n in ["Pessimistisch", "Neutral", "Optimistisch"]]
                y_title = "Nettorente (€/Monat)"
            namen = ["Pessimistisch", "Neutral", "Optimistisch"]
            fig_bar = go.Figure(go.Bar(
                x=namen,
                y=netto_vals,
                marker_color=[_FARBEN[n] for n in namen],
                text=[f"{_de(v)} €" for v in netto_vals],
                textposition="outside",
                hovertemplate="%{x}<br>%{y:,.0f} €/Mon.<extra></extra>",
            ))
            fig_bar.update_layout(
                template="plotly_white",
                height=340,
                yaxis=dict(title=y_title, ticksuffix=" €"),
                margin=dict(l=10, r=10, t=10, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_bar, use_container_width=True)

        with col_r:
            st.subheader("Kapital bei Renteneintritt")
            if zusammen_modus:
                kapital_vals = [
                    sz1[n].kapital_bei_renteneintritt + sz2[n].kapital_bei_renteneintritt
                    for n in namen
                ]
            else:
                kapital_vals = [szenarien[n].kapital_bei_renteneintritt for n in namen]
            fig_kap = go.Figure(go.Bar(
                x=namen,
                y=kapital_vals,
                marker_color=[_FARBEN[n] for n in namen],
                text=[f"{_de(v)} €" for v in kapital_vals],
                textposition="outside",
                hovertemplate="%{x}<br>%{y:,.0f} €<extra></extra>",
            ))
            fig_kap.update_layout(
                template="plotly_white",
                height=340,
                yaxis=dict(title="Kapital (€)", tickformat=",.0f"),
                margin=dict(l=10, r=10, t=10, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_kap, use_container_width=True)

        st.divider()

        # ── Kapitalwachstum über die Jahre ────────────────────────────────────
        st.subheader("Kapitalentwicklung bis Renteneintritt")
        jahre_range = list(range(profil.jahre_bis_rente + 1))
        jahre_labels = [AKTUELLES_JAHR + j for j in jahre_range]

        renditen = {
            "Pessimistisch": 0.03,
            "Neutral":       profil.rendite_pa,
            "Optimistisch":  0.07,
        }

        fig_k = go.Figure()
        for name, r in renditen.items():
            werte = [kapitalwachstum(profil.sparkapital, profil.sparrate, r, j)
                     for j in jahre_range]
            if zusammen_modus and profil2 is not None:
                werte2 = [kapitalwachstum(profil2.sparkapital, profil2.sparrate, r, j)
                          for j in jahre_range]
                werte = [a + b for a, b in zip(werte, werte2)]
            fig_k.add_trace(go.Scatter(
                x=jahre_labels,
                y=werte,
                name=name,
                line=dict(color=_FARBEN[name], width=2),
                hovertemplate=f"{name}<br>%{{x}}: %{{y:,.0f}} €<extra></extra>",
            ))
        fig_k.update_layout(
            template="plotly_white",
            height=380,
            yaxis=dict(title="Kapital (€)", tickformat=",.0f"),
            xaxis=dict(title="Jahr"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=40, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_k, use_container_width=True)

        st.divider()

        # ── Renteneintrittsalter-Sensitivität ────────────────────────────────
        if not zusammen_modus:
            st.subheader("Nettorente nach Renteneintrittsalter")
            st.caption("Wie stark beeinflusst das Renteneintrittsalter die Nettorente?")

            from dataclasses import replace
            from engine import berechne_rente

            alter_range = list(range(60, 71))
            netto_alter = []
            for a in alter_range:
                p_var = replace(profil, renteneintritt_alter=a)
                netto_alter.append(berechne_rente(p_var).netto_monatlich)

            fig_alter = go.Figure(go.Scatter(
                x=alter_range,
                y=netto_alter,
                mode="lines+markers",
                line=dict(color="#2196F3", width=2),
                marker=dict(size=8),
                hovertemplate="Alter %{x}: %{y:,.0f} €/Mon.<extra></extra>",
            ))
            fig_alter.add_vline(
                x=profil.renteneintritt_alter,
                line_dash="dash",
                line_color="#FF9800",
                annotation_text=f"Ihr Alter: {profil.renteneintritt_alter}",
                annotation_position="top right",
            )
            fig_alter.update_layout(
                template="plotly_white",
                height=320,
                xaxis=dict(title="Renteneintrittsalter", dtick=1),
                yaxis=dict(title="Nettorente (€/Monat)", ticksuffix=" €"),
                margin=dict(l=10, r=10, t=30, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_alter, use_container_width=True)

            st.caption(
                "**Abschläge:** 0,3 % pro Monat Frührente (§ 77 SGB VI).  "
                "Rentenabschlag und weniger Beitragsjahre wirken zusammen."
            )
