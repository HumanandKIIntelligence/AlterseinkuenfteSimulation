"""Auszahlung-Tab – Kapitalauszahlung vs. monatliche Verrentung."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import Profil, RentenErgebnis, kapital_vs_rente


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def render_section(profil: Profil, ergebnis: RentenErgebnis) -> None:
    """Kapitalverzehr-Kalkulator ohne Tab-Wrapper – aufrufbar aus Entnahme-Expander."""
    st.info(
        "Vergleiche, ob eine **Einmalauszahlung** (z.B. Lebensversicherung, Betriebsrente, "
        "ETF-Depot) oder eine **monatliche Verrentung** langfristig mehr einbringt. "
        "Der Break-Even-Punkt zeigt, ab wann du dein Kapital durch Rentenzahlungen "
        "zurückerhalten hast."
    )

    # ── Eingaben ──────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        kapital = st.number_input(
            "Verfügbares Kapital (€)",
            min_value=0.0, max_value=5_000_000.0,
            value=max(float(round(ergebnis.kapital_bei_renteneintritt, -3)), 100_000.0),
            step=1_000.0,
            key="az_kapital",
            help="Einmalbetrag, der zur Verrentung oder als Kapital genutzt wird. "
                 "Vorbelegt mit dem berechneten Sparkapital bei Renteneintritt.",
        )
        rendite_entnahme = st.slider(
            "Rendite bei Kapitalanlage p.a. (%)", 0.0, 8.0, 3.0, step=0.1,
            key="az_rendite",
            help="Rendite, die das Kapital bei Beibehaltung als Anlage erzielen würde.",
        ) / 100

    with col2:
        laufzeit = st.slider(
            "Laufzeit ab Renteneintritt (Jahre)",
            min_value=5, max_value=40, value=25,
            key="az_laufzeit",
            help="Statistik: Lebenserwartung 67-jährige Männer ~18 J., Frauen ~21 J. "
                 "25–30 Jahre = konservative Planung.",
        )
        rente_extern = st.number_input(
            "Monatliche Rente laut Angebot / Vertrag (€) – optional",
            min_value=0.0, max_value=20_000.0, value=0.0, step=50.0,
            key="az_rente_extern",
            help="Falls ein Versicherungsangebot vorliegt, hier eintragen. "
                 "Sonst wird die Annuität aus dem Kapital berechnet.",
        )

    # ── Berechnung ────────────────────────────────────────────────────────
    result = kapital_vs_rente(kapital, rendite_entnahme, laufzeit)
    monatsrente_verzehr = result["monatsrate"]
    monatsrente = rente_extern if rente_extern > 0 else monatsrente_verzehr

    st.divider()

    # ── Kennzahlen ────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Monatliche Rate (Annuität)",
        f"{_de(monatsrente_verzehr)} €",
        help="Monatliche Entnahme, die das Kapital inklusive Zinsen über die gewählte "
             "Laufzeit exakt aufbraucht.",
    )
    breakeven = kapital / monatsrente if monatsrente > 0 else 0.0
    c2.metric(
        "Break-Even-Punkt",
        f"{_de(breakeven / 12, dec=1)} Jahre",
        help="Nach dieser Zeit hast du das eingezahlte Kapital durch Rentenzahlungen "
             "vollständig zurückerhalten.",
    )
    c3.metric(
        "Gesamtauszahlung (Annuität)",
        f"{_de(result['gesamtauszahlung'])} €",
    )
    gewinn = result["gesamtauszahlung"] - kapital
    _sign = "+" if gewinn >= 0 else ""
    c4.metric(
        "Gewinn über Kapital",
        f"{_sign}{_de(gewinn)} €",
        delta_color="normal",
    )

    st.divider()

    # ── Kapitalverlauf ────────────────────────────────────────────────────
    st.subheader("Kapitalverlauf bei Verzehr (Annuität)")
    verlauf_df = pd.DataFrame(result["verlauf"])
    verlauf_df["Alter"] = profil.renteneintritt_alter + verlauf_df["Monat"] / 12

    fig_vl = go.Figure()
    fig_vl.add_trace(go.Scatter(
        x=verlauf_df["Alter"],
        y=verlauf_df["Kapital"],
        fill="tozeroy",
        fillcolor="rgba(33,150,243,0.12)",
        line=dict(color="#2196F3", width=2),
        name="Restkapital",
        hovertemplate="Alter %{x:.1f}: %{y:,.0f} €<extra></extra>",
    ))
    if monatsrente > 0:
        be_alter = profil.renteneintritt_alter + breakeven / 12
        if be_alter <= profil.renteneintritt_alter + laufzeit:
            fig_vl.add_vline(
                x=be_alter,
                line_dash="dash",
                line_color="#FF9800",
                annotation_text=f"Break-Even (Alter {be_alter:.0f})",
                annotation_position="top right",
            )
    fig_vl.update_layout(
        template="plotly_white",
        height=360,
        xaxis=dict(title="Alter"),
        yaxis=dict(title="Restkapital (€)", tickformat=",.0f"),
        margin=dict(l=10, r=10, t=10, b=10),
        separators=",.",
    )
    st.plotly_chart(fig_vl, use_container_width=True)

    st.divider()

    # ── Lebenserwartungsszenarien ─────────────────────────────────────────
    st.subheader("Sensitivität: verschiedene Laufzeiten")
    daten = []
    for lz in [15, 20, 25, 30, 35]:
        r = kapital_vs_rente(kapital, rendite_entnahme, lz)
        _g = r["gesamtauszahlung"] - kapital
        _gs = "+" if _g >= 0 else ""
        daten.append({
            "Laufzeit ab Rente (J.)": lz,
            "Monatliche Rate (€)": _de(r["monatsrate"]),
            "Gesamtauszahlung (€)": _de(r["gesamtauszahlung"]),
            "Gewinn vs. Kapital (€)": f"{_gs}{_de(_g)}",
            "Break-Even (Jahre)": _de(kapital / r["monatsrate"] / 12, dec=1) if r["monatsrate"] > 0 else "–",
        })
    st.dataframe(
        pd.DataFrame(daten).set_index("Laufzeit ab Rente (J.)"),
        use_container_width=True,
    )

    st.divider()

    # ── Verrentung vs. Entnahme-Vergleich ────────────────────────────────
    st.subheader("Kumulierte Auszahlung: Annuität vs. feste Rente")
    if rente_extern > 0:
        monate_range = list(range(laufzeit * 12 + 1))
        kumuliert_annuitaet = [result["monatsrate"] * m for m in monate_range]
        kumuliert_extern = [rente_extern * m for m in monate_range]
        alter_range = [profil.renteneintritt_alter + m / 12 for m in monate_range]

        fig_kum = go.Figure()
        fig_kum.add_trace(go.Scatter(
            x=alter_range, y=kumuliert_annuitaet,
            name="Kapitalverzehr (Annuität)", line=dict(color="#2196F3", width=2),
            hovertemplate="Alter %{x:.1f}: %{y:,.0f} €<extra></extra>",
        ))
        fig_kum.add_trace(go.Scatter(
            x=alter_range, y=kumuliert_extern,
            name="Externes Rentenangebot", line=dict(color="#4CAF50", width=2),
            hovertemplate="Alter %{x:.1f}: %{y:,.0f} €<extra></extra>",
        ))
        fig_kum.add_hline(y=kapital, line_dash="dot", line_color="#888",
                          annotation_text="Eingesetztes Kapital", annotation_position="right")
        fig_kum.update_layout(
            template="plotly_white", height=340,
            xaxis=dict(title="Alter"),
            yaxis=dict(title="Kumulierte Auszahlung (€)", tickformat=",.0f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=40, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_kum, use_container_width=True)
    else:
        st.caption("Trage ein externes Rentenangebot ein, um den kumulierten Vergleich zu sehen.")

    st.caption(
        "⚠️ Diese Berechnung berücksichtigt keine steuerliche Behandlung der Kapitalentnahme. "
        "Lebensversicherungen, Riester, Rürup und ETF-Entnahmen werden steuerlich sehr "
        "unterschiedlich behandelt. Individuelle Steuerberatung empfohlen."
    )
