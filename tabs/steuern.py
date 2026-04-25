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
    einkommensteuer,
)


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def render_section(profil: Profil, ergebnis: RentenErgebnis,
                   mieteinnahmen: float = 0.0) -> None:
    """Steuern & KV ohne Tab-Wrapper – aufrufbar aus Dashboard-Expander."""
    # ── Einkommensteuer ───────────────────────────────────────────────────
    st.subheader("Einkommensteuer auf die Rente")

    jahresbrutto = ergebnis.brutto_monatlich * 12
    miet_jahres = mieteinnahmen * 12
    besteuerter_anteil = jahresbrutto * ergebnis.besteuerungsanteil
    abzuege = WERBUNGSKOSTEN_PAUSCHBETRAG + SONDERAUSGABEN_PAUSCHBETRAG
    zvE_gesamt = max(0.0, besteuerter_anteil + miet_jahres - abzuege)
    jahressteuer_gesamt = einkommensteuer(zvE_gesamt)

    col1, col2 = st.columns([1, 1])

    with col1:
        st.markdown("**Berechnung Schritt für Schritt:**")
        rows: dict = {
            "Jahresbruttorente":                    f"{_de(jahresbrutto)} €",
            f"× Besteuerungsanteil ({ergebnis.besteuerungsanteil:.1%}".replace(".", ",") + ")":
                                                    f"{_de(besteuerter_anteil)} €",
        }
        if miet_jahres > 0:
            rows[f"+ Mieteinnahmen (§ 21 EStG)"] = f"+{_de(miet_jahres)} €"
        rows.update({
            "− Werbungskosten-Pauschbetrag":        f"−{WERBUNGSKOSTEN_PAUSCHBETRAG} €",
            "− Sonderausgaben-Pauschbetrag":        f"−{SONDERAUSGABEN_PAUSCHBETRAG} €",
            "− Grundfreibetrag":                    f"−{_de(GRUNDFREIBETRAG_2024)} €",
            "**= Zu versteuerndes Einkommen**":     f"**{_de(zvE_gesamt)} €**",
            "**Jahressteuer**":                     f"**{_de(jahressteuer_gesamt)} €**",
            "**Steuer / Monat**":                   f"**{_de(jahressteuer_gesamt / 12)} €**",
            "**Effektiver Steuersatz**":
                f"**{jahressteuer_gesamt / (jahresbrutto + miet_jahres):.1%}**".replace(".", ",")
                if (jahresbrutto + miet_jahres) > 0 else "**0,0 %**",
        })
        for label, value in rows.items():
            c_l, c_r = st.columns([2, 1])
            c_l.markdown(label)
            c_r.markdown(value)

    with col2:
        x_labels = ["Jahresbrutto\n(Rente)", "Besteuerter\nAnteil"]
        y_vals = [jahresbrutto, besteuerter_anteil]
        colors = ["#90CAF9", "#FFF176"]
        if miet_jahres > 0:
            x_labels.append("Mieteinnahmen")
            y_vals.append(miet_jahres)
            colors.append("#FFCC80")
        x_labels += ["Steuerlast", "Netto (Jahr)"]
        y_vals += [jahressteuer_gesamt, (jahresbrutto + miet_jahres) - jahressteuer_gesamt - ergebnis.kv_monatlich * 12]
        colors += ["#EF9A9A", "#A5D6A7"]
        fig_st = go.Figure(go.Bar(
            x=x_labels, y=y_vals,
            marker_color=colors,
            text=[f"{_de(v)} €" for v in y_vals],
            textposition="outside",
        ))
        fig_st.update_layout(
            template="plotly_white",
            height=340,
            yaxis=dict(title="€ / Jahr", tickformat=",.0f"),
            margin=dict(l=0, r=10, t=10, b=10),
            separators=",.",
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
        annotation_text=f"Ihr Eintritt {profil.eintritt_jahr}: {ergebnis.besteuerungsanteil:.1%}".replace(".", ","),
        annotation_position="top left",
    )
    fig_ba.update_layout(
        template="plotly_white",
        height=280,
        yaxis=dict(title="Besteuerungsanteil (%)", range=[40, 105], ticksuffix=" %"),
        xaxis=dict(title="Renteneintritt"),
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=False,
        separators=",.",
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
            f"{kv_satz:.2%}".replace(".", ","),
            help="7,3 % Basis + halber Zusatzbeitrag. Die DRV übernimmt die andere Hälfte.",
        )
        c2.metric(
            "PV-Beitragssatz",
            f"{pv_satz:.2%}".replace(".", ","),
            help="3,4 % mit Kindern / 4,0 % ohne Kinder. Rentner tragen den vollen Beitrag.",
        )
        c3.metric("Gesamtbeitragssatz", f"{gesamt_satz:.2%}".replace(".", ","))
        c4.metric("Monatlicher Beitrag", f"{_de(ergebnis.kv_monatlich)} €")

        st.markdown("""
        **KVdR (Krankenversicherung der Rentner):**
        - Rentner zahlen **die Hälfte** des Krankenversicherungsbeitrags (7,3 % + ½ Zusatzbeitrag)
        - Die **Deutsche Rentenversicherung** übernimmt die andere Hälfte
        - Die **Pflegeversicherung** trägt der Rentner vollständig selbst
        - Beitragsbemessungsgrundlage: alle Renteneinnahmen (gesetzl. + bAV)
        """)

    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("PKV-Monatsbeitrag", f"{_de(profil.pkv_beitrag)} €")
        c2.metric("PKV-Jahresbeitrag", f"{_de(profil.pkv_beitrag * 12)} €")
        kv_satz_gkv = 0.073 + 0.017 / 2
        pv_satz_gkv = 0.034 if profil.kinder else 0.040
        gkv_sim = ergebnis.brutto_monatlich * (kv_satz_gkv + pv_satz_gkv)
        diff = profil.pkv_beitrag - gkv_sim
        _sign = "+" if diff >= 0 else ""
        c3.metric(
            "GKV-Beitrag (simuliert)", f"{_de(gkv_sim)} €",
            delta=f"{_sign}{_de(diff)} € vs. PKV",
            delta_color="inverse",
        )

        if diff > 0:
            st.error(
                f"PKV kostet **{_de(diff)} €/Monat** mehr als die simulierte GKV "
                f"({_de(diff * 12)} €/Jahr). Ein Rückwechsel in die GKV ist im Rentenalter "
                "i.d.R. nicht möglich – frühzeitig planen!"
            )
        else:
            st.success(
                f"PKV ist **{_de(-diff)} €/Monat** günstiger als die simulierte GKV "
                f"({_de(-diff * 12)} €/Jahr)."
            )

        fig_kv = go.Figure(go.Bar(
            x=["PKV (Eingabe)", "GKV (simuliert, Ø-Zusatzbeitrag 1,7 %)"],
            y=[profil.pkv_beitrag, gkv_sim],
            marker_color=["#EF9A9A" if diff > 0 else "#A5D6A7", "#A5D6A7"],
            text=[f"{_de(v)} €/Mon." for v in [profil.pkv_beitrag, gkv_sim]],
            textposition="outside",
        ))
        fig_kv.update_layout(
            template="plotly_white",
            height=300,
            yaxis=dict(title="€ / Monat"),
            margin=dict(l=10, r=10, t=10, b=10),
            separators=",.",
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
