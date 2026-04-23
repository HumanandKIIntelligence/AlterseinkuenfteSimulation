"""Haushalt-Tab – Gemeinsame Einkommensübersicht für Ehepaare."""

import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from engine import (
    Profil, RentenErgebnis,
    berechne_haushalt, einkommensteuer_splitting,
    simuliere_szenarien,
)


def render(
    T: dict,
    p1: Profil,
    p2: Profil,
    e1: RentenErgebnis,
    e2: RentenErgebnis,
    veranlagung: str,
    hh: dict,
    mieteinnahmen: float = 0.0,
    mietsteigerung: float = 0.0,
) -> None:
    with T["Haushalt"]:
        st.header("👥 Haushalts-Übersicht")

        veranlagung_label = "Zusammenveranlagung (Splitting)" if veranlagung == "Zusammen" \
            else "Getrennte Veranlagung"
        st.info(
            f"**Steuerliche Veranlagung:** {veranlagung_label}  |  "
            f"**Person 1:** Renteneintritt {p1.eintritt_jahr}  |  "
            f"**Person 2:** Renteneintritt {p2.eintritt_jahr}"
        )

        # ── Kennzahlen ────────────────────────────────────────────────────────
        st.subheader("Monatliches Haushaltseinkommen")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Brutto gesamt", f"{hh['brutto_gesamt']:,.0f} €",
                  help="Renten (brutto) beider Partner + Mieteinnahmen")
        c2.metric("Netto gesamt", f"{hh['netto_gesamt']:,.0f} €")
        c3.metric("Steuer gesamt", f"{hh['steuer_gesamt']:,.0f} €")
        if hh["steuerersparnis_splitting"] > 0:
            c4.metric(
                "Splitting-Vorteil",
                f"{hh['steuerersparnis_splitting']:,.0f} €/Mon.",
                delta=f"{hh['steuerersparnis_splitting'] * 12:,.0f} €/Jahr",
                help="Steuerersparnis durch Zusammenveranlagung gegenüber Einzelveranlagung.",
            )
        else:
            c4.metric("Splitting-Vorteil", "–")

        st.divider()

        # ── Seite-an-Seite Vergleich ──────────────────────────────────────────
        st.subheader("Person 1 vs. Person 2 – Monatlich")
        col1, col2, col3 = st.columns([2, 2, 3])

        with col1:
            st.markdown("**Person 1**")
            for label, wert in [
                ("Bruttorente", f"{e1.brutto_monatlich:,.0f} €"),
                ("− Steuer", f"{e1.steuer_monatlich:,.0f} €"),
                ("− KV / PV", f"{e1.kv_monatlich:,.0f} €"),
                ("**= Netto**", f"**{e1.netto_monatlich:,.0f} €**"),
                ("Rentenpunkte", f"{e1.gesamtpunkte:.1f}"),
                ("Renteneintritt", str(p1.eintritt_jahr)),
            ]:
                a, b = st.columns([2, 1])
                a.markdown(label)
                b.markdown(wert)

        with col2:
            st.markdown("**Person 2**")
            for label, wert in [
                ("Bruttorente", f"{e2.brutto_monatlich:,.0f} €"),
                ("− Steuer", f"{e2.steuer_monatlich:,.0f} €"),
                ("− KV / PV", f"{e2.kv_monatlich:,.0f} €"),
                ("**= Netto**", f"**{e2.netto_monatlich:,.0f} €**"),
                ("Rentenpunkte", f"{e2.gesamtpunkte:.1f}"),
                ("Renteneintritt", str(p2.eintritt_jahr)),
            ]:
                a, b = st.columns([2, 1])
                a.markdown(label)
                b.markdown(wert)

        with col3:
            fig = go.Figure()
            personen = ["Person 1", "Person 2"]
            farbe_brutto = ["#90CAF9", "#80DEEA"]
            farbe_steuer = ["#EF9A9A", "#F48FB1"]
            farbe_kv     = ["#FFF176", "#FFCC80"]
            farbe_netto  = ["#A5D6A7", "#C5E1A5"]
            for farben, werte, name in [
                (farbe_brutto, [e1.brutto_monatlich, e2.brutto_monatlich], "Brutto"),
                (farbe_steuer, [-e1.steuer_monatlich, -e2.steuer_monatlich], "− Steuer"),
                (farbe_kv,     [-e1.kv_monatlich, -e2.kv_monatlich], "− KV/PV"),
                (farbe_netto,  [e1.netto_monatlich, e2.netto_monatlich], "Netto"),
            ]:
                fig.add_trace(go.Bar(
                    name=name, x=personen, y=werte,
                    marker_color=farben,
                    text=[f"{abs(v):,.0f} €" for v in werte],
                    textposition="inside",
                ))
            fig.update_layout(
                barmode="overlay",
                template="plotly_white",
                height=320,
                yaxis=dict(title="€ / Monat"),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=0, r=0, t=30, b=0),
            )
            st.plotly_chart(fig, use_container_width=True)

        if mieteinnahmen > 0:
            st.info(
                f"🏠 **Mieteinnahmen:** {mieteinnahmen:,.0f} €/Monat "
                f"(+{mietsteigerung:.1%} p.a.) – in Steuerberechnung enthalten, keine KV-Pflicht."
            )

        st.divider()

        # ── Steuervergleich: Zusammen vs. Getrennt ────────────────────────────
        st.subheader("Steuervergleich: Zusammen- vs. Getrennte Veranlagung")

        hh_zusammen = berechne_haushalt(e1, e2, "Zusammen", mieteinnahmen)
        hh_getrennt = berechne_haushalt(e1, e2, "Getrennt", mieteinnahmen)

        sv1, sv2, sv3, sv4 = st.columns(4)
        sv1.metric("Steuer Zusammen (Mon.)", f"{hh_zusammen['steuer_gesamt']:,.0f} €")
        sv2.metric("Steuer Getrennt (Mon.)", f"{hh_getrennt['steuer_gesamt']:,.0f} €")
        sv3.metric("Netto Zusammen (Mon.)", f"{hh_zusammen['netto_gesamt']:,.0f} €")
        sv4.metric("Netto Getrennt (Mon.)", f"{hh_getrennt['netto_gesamt']:,.0f} €")

        ersparnis_monatlich = hh_zusammen["steuerersparnis_splitting"]
        if ersparnis_monatlich > 0:
            st.success(
                f"**Zusammenveranlagung spart {ersparnis_monatlich:,.0f} €/Monat "
                f"({ersparnis_monatlich * 12:,.0f} €/Jahr)** gegenüber getrennter Veranlagung."
            )
        else:
            st.info("In diesem Fall ergibt sich kein Splitting-Vorteil "
                    "(ähnlich hohe Einkommen beider Partner).")

        # Visualisierung Steuer-Vergleich
        fig_st = go.Figure(go.Bar(
            x=["Zusammenveranlagung\n(Splitting)", "Getrennte\nVeranlagung"],
            y=[hh_zusammen["steuer_gesamt"] * 12, hh_getrennt["steuer_gesamt"] * 12],
            marker_color=["#A5D6A7", "#EF9A9A"],
            text=[f"{v:,.0f} €/Jahr" for v in [
                hh_zusammen["steuer_gesamt"] * 12,
                hh_getrennt["steuer_gesamt"] * 12,
            ]],
            textposition="outside",
        ))
        fig_st.update_layout(
            template="plotly_white", height=300,
            yaxis=dict(title="Jahressteuer (€)", tickformat=",.0f"),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig_st, use_container_width=True)

        st.divider()

        # ── Szenarien-Vergleich Haushalt ──────────────────────────────────────
        st.subheader("Haushalt-Szenarien (pessimistisch / neutral / optimistisch)")

        sz1 = simuliere_szenarien(p1)
        sz2 = simuliere_szenarien(p2)
        rows = []
        for name in ["Pessimistisch", "Neutral", "Optimistisch"]:
            hh_sz = berechne_haushalt(sz1[name], sz2[name], veranlagung)
            rows.append({
                "Szenario": name,
                "Brutto gesamt (€/Mon.)": f"{hh_sz['brutto_gesamt']:,.0f}",
                "Netto gesamt (€/Mon.)": f"{hh_sz['netto_gesamt']:,.0f}",
                "Netto Person 1": f"{sz1[name].netto_monatlich:,.0f}",
                "Netto Person 2": f"{sz2[name].netto_monatlich:,.0f}",
            })
        st.dataframe(pd.DataFrame(rows).set_index("Szenario"), use_container_width=True)

        st.divider()

        # ── Gemeinsame Renteneintrittslücke ───────────────────────────────────
        st.subheader("Zeitraum mit unterschiedlichen Renteneintrittsjahren")
        years_diff = abs(p1.eintritt_jahr - p2.eintritt_jahr)
        if years_diff > 0:
            erster = "Person 1" if p1.eintritt_jahr <= p2.eintritt_jahr else "Person 2"
            zweiter = "Person 2" if erster == "Person 1" else "Person 1"
            e_erst = e1 if erster == "Person 1" else e2
            st.info(
                f"**{erster}** geht {years_diff} Jahr(e) früher in Rente als **{zweiter}**. "
                f"In dieser Zeit steht nur die Rente von {erster} zur Verfügung: "
                f"**{e_erst.netto_monatlich:,.0f} €/Monat netto**."
            )
        else:
            st.info("Beide Partner gehen im gleichen Jahr in Rente.")

        st.caption(
            "⚠️ Vereinfachte Berechnung. Splitting-Vorteil basiert auf Renteneinnahmen. "
            "Weitere Einkünfte (Mieten, Kapitalerträge) können das Ergebnis erheblich verändern. "
            "Steuerberatung empfohlen."
        )
