"""Dashboard-Tab – Rentenübersicht auf einen Blick."""

import plotly.graph_objects as go
import streamlit as st

from engine import Profil, RentenErgebnis, GRUNDFREIBETRAG_2024
from tabs import steuern


def _de(v: float, dec: int = 0) -> str:
    """Zahl im deutschen Format: 1.234,56"""
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _grenzsteuersatz(zvE: float) -> float:
    if zvE <= 11_604:
        return 0.0
    if zvE <= 17_005:
        y = (zvE - 11_604) / 10_000
        return (1_856.74 * y + 1_400) / 10_000
    if zvE <= 66_760:
        z = (zvE - 17_005) / 10_000
        return (353.28 * z + 2_397) / 10_000
    if zvE <= 277_825:
        return 0.42
    return 0.45


def _kv_pv_split(profil: Profil, kv_gesamt: float,
                  ergebnis: RentenErgebnis | None = None) -> tuple[float, float]:
    """Gibt (GKV-Anteil, PV-Anteil) des monatlichen KV-Beitrags zurück."""
    if ergebnis is not None and (ergebnis.kv_gkv_monatlich + ergebnis.kv_pv_monatlich) > 0:
        return ergebnis.kv_gkv_monatlich, ergebnis.kv_pv_monatlich
    if profil.krankenversicherung == "PKV":
        return kv_gesamt, 0.0
    _freiwillig = profil.ist_pensionaer or not profil.kvdr_pflicht
    if _freiwillig:
        _kv_rate = 0.146 + profil.gkv_zusatzbeitrag
        _pv_rate = 0.034 if profil.kinder else 0.040
    else:
        _kv_rate = 0.073 + profil.gkv_zusatzbeitrag / 2
        _pv_rate = 0.017 if profil.kinder else 0.023
    _total = _kv_rate + _pv_rate
    if _total == 0:
        return 0.0, 0.0
    return kv_gesamt * _kv_rate / _total, kv_gesamt * _pv_rate / _total


def _steuerampel(zvE: float) -> None:
    if zvE <= 0:
        zvE = 0.0

    if zvE <= GRUNDFREIBETRAG_2024:
        zone = "Steuerfrei"
        farbe = "✅"
        gst = 0.0
        freiraum = GRUNDFREIBETRAG_2024 - zvE
        naechste = f"Grundfreibetrag ({_de(GRUNDFREIBETRAG_2024)} €)"
        tipp = "Optimale Zone – Einkommen vollständig unter Grundfreibetrag."
    elif zvE <= 17_005:
        zone = "Progressionszone 1 (14–24 %)"
        farbe = "🟢"
        gst = _grenzsteuersatz(zvE)
        freiraum = 17_005 - zvE
        naechste = "Zone 2 (17.005 €)"
        tipp = "Geringe Progression – Einnahmen vorziehen oder strecken prüfen."
    elif zvE <= 66_760:
        zone = "Progressionszone 2 (24–42 %)"
        farbe = "🟡"
        gst = _grenzsteuersatz(zvE)
        freiraum = 66_760 - zvE
        naechste = "42%-Zone (66.760 €)"
        tipp = "Wachsende Progression – Aufschub oder Einmalentnahme-Streckung sinnvoll."
    elif zvE <= 277_825:
        zone = "Proportionalzone 42 %"
        farbe = "🟠"
        gst = 0.42
        freiraum = 277_825 - zvE
        naechste = "Spitzensteuersatz (277.825 €)"
        tipp = "42 % Grenzsteuersatz – Einnahmen auf mehrere Jahre verteilen."
    else:
        zone = "Spitzensteuersatz 45 %"
        farbe = "🔴"
        gst = 0.45
        freiraum = 0.0
        naechste = "–"
        tipp = "Maximale Steuerbelastung – intensive Steuerplanung und -beratung empfohlen."

    st.subheader(f"{farbe} Steuerzone: {zone}")
    zc1, zc2, zc3 = st.columns(3)
    zc1.metric("Grenzsteuersatz", f"{gst:.1%}".replace(".", ","),
               help="Steuersatz auf jeden zusätzlichen Euro Einkommen.")
    zc2.metric("zvE aktuell", f"{_de(zvE)} €/Jahr")
    if freiraum > 0:
        zc3.metric(f"Freiraum bis {naechste}", f"{_de(freiraum)} €",
                   help="Um diesen Betrag kann das zvE noch steigen, bevor der nächste Steuersatz greift.")
    else:
        zc3.metric("Nächste Zone", "–")
    st.info(f"💡 **Handlungshinweis:** {tipp}")


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis,
           mieteinnahmen: float = 0.0,
           profil2: Profil | None = None,
           ergebnis2: RentenErgebnis | None = None) -> None:
    with T["Dashboard"]:
        st.header("📊 Rentenübersicht")

        if profil2 is not None and ergebnis2 is not None:
            wahl = st.radio("Person", ["Person 1", "Person 2"],
                            horizontal=True, key="dash_person")
            if wahl == "Person 2":
                profil, ergebnis = profil2, ergebnis2

        abschlag_info = (
            f"  |  **Rentenabschlag:** {ergebnis.rentenabschlag:.1%}".replace(".", ",") +
            f" ({(67 - profil.renteneintritt_alter) * 12} Monate × 0,3 % § 77 SGB VI)"
            if ergebnis.rentenabschlag > 0 else ""
        )
        st.info(
            f"**Alter heute:** {profil.aktuelles_alter} Jahre  |  "
            f"**Renteneintritt:** {profil.renteneintritt_alter} Jahre ({profil.eintritt_jahr})  |  "
            f"**Noch {profil.jahre_bis_rente} Jahre bis zur Rente**"
            + abschlag_info
        )

        # ── Kennzahlen ────────────────────────────────────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Bruttorente / Monat", f"{_de(ergebnis.brutto_monatlich)} €",
            help="Gesetzliche Rente + Zusatzrente vor Steuer und KV-Abzügen.",
        )
        c2.metric(
            "Nettorente / Monat", f"{_de(ergebnis.netto_monatlich)} €",
            help="Nach Einkommensteuer und Kranken-/Pflegeversicherungsbeitrag.",
        )
        c3.metric(
            "Kapital bei Renteneintritt", f"{_de(ergebnis.kapital_bei_renteneintritt)} €",
            help="Angewachsenes Spar- und Depotkapital zum Renteneintritt.",
        )
        c4.metric(
            "Rentenpunkte gesamt", f"{ergebnis.gesamtpunkte:.1f}".replace(".", ","),
            help=f"Aktuell {ergebnis.gesamtpunkte - profil.punkte_pro_jahr * profil.jahre_bis_rente:.1f} "
                 f"+ {profil.punkte_pro_jahr:.2f} Punkte/Jahr × {profil.jahre_bis_rente} Jahre.".replace(".", ","),
        )

        # KV/PV-Split berechnen
        gkv_mono, pv_mono = _kv_pv_split(profil, ergebnis.kv_monatlich, ergebnis)
        _kv_label = "PKV / Monat" if profil.krankenversicherung == "PKV" else "KV / Monat"
        _pv_label = "–" if profil.krankenversicherung == "PKV" else "PV / Monat"

        c5, c6, c7, c8, c9 = st.columns(5)
        c5.metric(
            "Gesetzl. Rente (brutto)", f"{_de(ergebnis.brutto_gesetzlich)} €/Mon.",
            help=f"Rentenabschlag: {ergebnis.rentenabschlag:.1%}".replace(".", ",") + " (§ 77 SGB VI)"
                 if ergebnis.rentenabschlag > 0 else None,
        )
        c6.metric("Steuerabzug / Monat", f"{_de(ergebnis.steuer_monatlich)} €")
        c7.metric(
            _kv_label, f"{_de(gkv_mono)} €",
            help="Krankenversicherungsbeitrag (eigener Anteil).",
        )
        if profil.krankenversicherung == "GKV":
            _freiwillig = profil.ist_pensionaer or not profil.kvdr_pflicht
            _pv_info = (
                "Freiwillig GKV: voller PV-Satz (kein DRV-Trägeranteil)"
                if _freiwillig else
                "KVdR: DRV trägt die Hälfte des PV-Beitrags"
            )
            c8.metric("PV / Monat", f"{_de(pv_mono)} €", help=_pv_info)
        else:
            c8.metric("PV / Monat", "–")
        if mieteinnahmen > 0:
            c9.metric(
                "Mieteinnahmen (Haushalt)", f"{_de(mieteinnahmen)} €/Mon.",
                help="Gemeinsame Nettomieteinnahmen (§ 21 EStG). Steuerlich wirksam, keine KV-Pflicht."
            )
        else:
            c9.metric(
                "Eff. Steuersatz", f"{ergebnis.effektiver_steuersatz:.1%}".replace(".", ","),
                help=f"Besteuerungsanteil: {ergebnis.besteuerungsanteil:.1%}".replace(".", ",") +
                     f" (Renteneintritt {profil.eintritt_jahr})",
            )

        st.divider()

        # ── Wasserfall Brutto → Netto ─────────────────────────────────────────
        st.subheader("Brutto → Netto (monatlich)")
        fig_wf = go.Figure(go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "relative", "relative", "total"],
            x=["Bruttorente", "− Einkommensteuer", "− KV", "− PV", "Nettorente"],
            y=[
                ergebnis.brutto_monatlich,
                -ergebnis.steuer_monatlich,
                -gkv_mono,
                -pv_mono,
                ergebnis.netto_monatlich,
            ],
            text=[
                f"{_de(ergebnis.brutto_monatlich)} €",
                f"−{_de(ergebnis.steuer_monatlich)} €",
                f"−{_de(gkv_mono)} €",
                f"−{_de(pv_mono)} €",
                f"{_de(ergebnis.netto_monatlich)} €",
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
            separators=",.",
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
                    separators=",.",
                )
                st.plotly_chart(fig_pie, use_container_width=True)

        with right:
            st.subheader("Kaufkraft heute vs. Rente")
            inflation = 0.02
            kaufkraft = ergebnis.netto_monatlich / (1 + inflation) ** profil.jahre_bis_rente
            verlust = ergebnis.netto_monatlich - kaufkraft
            st.metric(
                "Nettorente in heutiger Kaufkraft (2 % Inflation)",
                f"{_de(kaufkraft)} €",
                delta=f"−{_de(verlust)} € Kaufkraftverlust",
                delta_color="inverse",
            )
            st.caption(
                f"Die Nettorente von **{_de(ergebnis.netto_monatlich)} €** in {profil.eintritt_jahr} "
                f"entspricht bei 2 % Inflation der heutigen Kaufkraft von nur **{_de(kaufkraft)} €**. "
                f"Die eigene Rentenanpassungs-Annahme von "
                f"{profil.rentenanpassung_pa:.0%}".replace(".", ",") + " p.a. "
                f"{'federt dies ab' if profil.rentenanpassung_pa >= inflation else 'deckt dies nicht vollständig ab'}."
            )

        st.divider()

        zvE_mit_miete = ergebnis.zvE_jahres + mieteinnahmen * 12
        _steuerampel(zvE_mit_miete)

        st.divider()

        with st.expander("🧾 Steuer- & KV-Details", expanded=False):
            steuern.render_section(profil, ergebnis, mieteinnahmen)

        st.caption(
            "⚠️ Alle Angaben sind Simulationswerte auf Basis vereinfachter Annahmen. "
            "Keine Steuer- oder Anlageberatung."
        )
