"""Dashboard-Tab – Rentenübersicht auf einen Blick."""

import plotly.graph_objects as go
import streamlit as st

from engine import Profil, RentenErgebnis


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis,
           mieteinnahmen: float = 0.0) -> None:
    with T["Dashboard"]:
        st.header("📊 Rentenübersicht")

        # Infozeile
        st.info(
            f"**Alter heute:** {profil.aktuelles_alter} Jahre  |  "
            f"**Renteneintritt:** {profil.renteneintritt_alter} Jahre ({profil.eintritt_jahr})  |  "
            f"**Noch {profil.jahre_bis_rente} Jahre bis zur Rente**"
        )

        # ── Kennzahlen ────────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Bruttorente / Monat", f"{ergebnis.brutto_monatlich:,.0f} €",
            help="Gesetzliche Rente + Zusatzrente vor Steuer und KV-Abzügen.",
        )
        c2.metric(
            "Nettorente / Monat", f"{ergebnis.netto_monatlich:,.0f} €",
            help="Nach Einkommensteuer und Kranken-/Pflegeversicherungsbeitrag.",
        )
        c3.metric(
            "Kapital bei Renteneintritt", f"{ergebnis.kapital_bei_renteneintritt:,.0f} €",
            help="Angewachsenes Spar- und Depotkapital zum Renteneintritt.",
        )
        c4.metric(
            "Rentenpunkte gesamt", f"{ergebnis.gesamtpunkte:.1f}",
            help=f"Aktuell {profil.aktuelle_punkte:.1f} + "
                 f"{profil.punkte_pro_jahr:.2f} Punkte/Jahr × {profil.jahre_bis_rente} Jahre.",
        )

        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Gesetzl. Rente (brutto)", f"{ergebnis.brutto_gesetzlich:,.0f} €/Monat")
        c6.metric("Steuerabzug / Monat", f"{ergebnis.steuer_monatlich:,.0f} €")
        c7.metric("KV-Abzug / Monat", f"{ergebnis.kv_monatlich:,.0f} €")
        c8.metric(
            "Mieteinnahmen (Haushalt)", f"{mieteinnahmen:,.0f} €/Monat",
            help="Gemeinsame Nettomieteinnahmen (§ 21 EStG). Steuerlich wirksam, keine KV-Pflicht."
        ) if mieteinnahmen > 0 else c8.metric(
            "Eff. Steuersatz", f"{ergebnis.effektiver_steuersatz:.1%}",
            help=f"Besteuerungsanteil: {ergebnis.besteuerungsanteil:.1%} "
                 f"(Renteneintritt {profil.eintritt_jahr})",
        )

        st.divider()

        # ── Wasserfall Brutto → Netto ─────────────────────────────────────────
        st.subheader("Brutto → Netto (monatlich)")
        fig_wf = go.Figure(go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "relative", "total"],
            x=["Bruttorente", "− Einkommensteuer", "− KV / PV", "Nettorente"],
            y=[
                ergebnis.brutto_monatlich,
                -ergebnis.steuer_monatlich,
                -ergebnis.kv_monatlich,
                ergebnis.netto_monatlich,
            ],
            text=[
                f"{ergebnis.brutto_monatlich:,.0f} €",
                f"−{ergebnis.steuer_monatlich:,.0f} €",
                f"−{ergebnis.kv_monatlich:,.0f} €",
                f"{ergebnis.netto_monatlich:,.0f} €",
            ],
            textposition="outside",
            connector=dict(line=dict(color="#888")),
            increasing=dict(marker=dict(color="#4CAF50")),
            decreasing=dict(marker=dict(color="#F44336")),
            totals=dict(marker=dict(color="#2196F3")),
        ))
        fig_wf.update_layout(
            template="plotly_white",
            height=360,
            yaxis=dict(title="€ / Monat", ticksuffix=" €"),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig_wf, use_container_width=True)

        st.divider()

        # ── Zusammensetzung + Kaufkraft ───────────────────────────────────────
        left, right = st.columns(2)

        with left:
            st.subheader("Rentenbausteine")
            labels = ["Gesetzl. Rente", "Zusatzrente (bAV/privat)"]
            values = [ergebnis.brutto_gesetzlich, profil.zusatz_monatlich]
            if any(v > 0 for v in values):
                fig_pie = go.Figure(go.Pie(
                    labels=labels,
                    values=[max(0.0, v) for v in values],
                    hole=0.45,
                    textinfo="percent+label",
                    hovertemplate="%{label}<br>%{value:,.0f} €/Mon.<extra></extra>",
                ))
                fig_pie.update_layout(
                    height=300,
                    margin=dict(l=0, r=0, t=10, b=0),
                    showlegend=False,
                )
                st.plotly_chart(fig_pie, use_container_width=True)

        with right:
            st.subheader("Kaufkraft heute vs. Rente")
            inflation = 0.02
            kaufkraft = ergebnis.netto_monatlich / (1 + inflation) ** profil.jahre_bis_rente
            verlust = ergebnis.netto_monatlich - kaufkraft
            st.metric(
                "Nettorente in heutiger Kaufkraft (2 % Inflation)",
                f"{kaufkraft:,.0f} €",
                delta=f"−{verlust:,.0f} € Kaufkraftverlust",
                delta_color="inverse",
            )
            st.caption(
                f"Die Nettorente von **{ergebnis.netto_monatlich:,.0f} €** in {profil.eintritt_jahr} "
                f"entspricht bei 2 % Inflation der heutigen Kaufkraft von nur **{kaufkraft:,.0f} €**. "
                f"Die eigene Rentenanpassungs-Annahme von {profil.rentenanpassung_pa:.0%} p.a. "
                f"{'federt dies ab' if profil.rentenanpassung_pa >= inflation else 'deckt dies nicht vollständig ab'}."
            )

        st.caption(
            "⚠️ Alle Angaben sind Simulationswerte auf Basis vereinfachter Annahmen. "
            "Keine Steuer- oder Anlageberatung."
        )
