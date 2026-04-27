"""Dashboard-Tab – Rentenübersicht auf einen Blick."""

import plotly.graph_objects as go
import streamlit as st

from engine import (
    Profil, RentenErgebnis, GRUNDFREIBETRAG_2024, AKTUELLES_JAHR,
    GRUNDSICHERUNG_SCHWELLE,
    berechne_haushalt, _netto_ueber_horizont,
    einkommensteuer, einkommensteuer_splitting, solidaritaetszuschlag,
)
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


def _steuerampel(zvE: float, titel: str = "", splitting: bool = False) -> None:
    """zvE: bei splitting=True das kombinierte Haushalts-zvE; sonst individuelles zvE."""
    if zvE <= 0:
        zvE = 0.0
    f = 2 if splitting else 1              # Grenzen × 2 für Splitting-Haushalt
    zvE_ind = zvE / f                      # individuelles zvE für Grenzsteuersatz

    _GFB = GRUNDFREIBETRAG_2024 * f
    _Z1  = 17_005 * f
    _Z2  = 66_760 * f
    _Z42 = 277_825 * f

    if zvE <= _GFB:
        zone = "Steuerfrei"
        farbe = "✅"
        gst = 0.0
        freiraum = _GFB - zvE
        naechste = f"Grundfreibetrag ({_de(_GFB)} €)"
        tipp = "Optimale Zone – Einkommen vollständig unter Grundfreibetrag."
    elif zvE <= _Z1:
        zone = "Progressionszone 1 (14–24 %)"
        farbe = "🟢"
        gst = _grenzsteuersatz(zvE_ind)
        freiraum = _Z1 - zvE
        naechste = f"Zone 2 ({_de(_Z1)} €)"
        tipp = "Geringe Progression – Einnahmen vorziehen oder strecken prüfen."
    elif zvE <= _Z2:
        zone = "Progressionszone 2 (24–42 %)"
        farbe = "🟡"
        gst = _grenzsteuersatz(zvE_ind)
        freiraum = _Z2 - zvE
        naechste = f"42%-Zone ({_de(_Z2)} €)"
        tipp = "Wachsende Progression – Aufschub oder Einmalentnahme-Streckung sinnvoll."
    elif zvE <= _Z42:
        zone = "Proportionalzone 42 %"
        farbe = "🟠"
        gst = 0.42
        freiraum = _Z42 - zvE
        naechste = f"Spitzensteuersatz ({_de(_Z42)} €)"
        tipp = "42 % Grenzsteuersatz – Einnahmen auf mehrere Jahre verteilen."
    else:
        zone = "Spitzensteuersatz 45 %"
        farbe = "🔴"
        gst = 0.45
        freiraum = 0.0
        naechste = "–"
        tipp = "Maximale Steuerbelastung – intensive Steuerplanung und -beratung empfohlen."

    _header = f"{farbe} Steuerzone: {zone}"
    if titel:
        _header = f"{farbe} {titel} – {zone}"
    st.subheader(_header)
    zc1, zc2, zc3, zc4 = st.columns(4)
    zc1.metric("Grenzsteuersatz", f"{gst:.1%}".replace(".", ","),
               help="Steuersatz auf jeden zusätzlichen Euro Einkommen.")
    _zvE_label = "zvE Haushalt" if splitting else "zvE aktuell"
    zc2.metric(_zvE_label, f"{_de(zvE)} €/Jahr")
    if splitting:
        _est  = einkommensteuer_splitting(zvE)
        _soli = 2 * solidaritaetszuschlag(einkommensteuer(zvE_ind))
    else:
        _est  = einkommensteuer(zvE)
        _soli = solidaritaetszuschlag(_est)
    zc3.metric("Jahressteuer (ESt + Soli)",
               f"{_de(_est + _soli)} €",
               help=f"ESt: {_de(_est)} € + Soli: {_de(_soli, 2)} € (5,5 % ab 17.543 € ESt)")
    if freiraum > 0:
        zc4.metric(f"Freiraum bis {naechste}", f"{_de(freiraum)} €",
                   help="Um diesen Betrag kann das zvE noch steigen, bevor der nächste Steuersatz greift.")
    else:
        zc4.metric("Nächste Zone", "–")
    st.info(f"💡 **Handlungshinweis:** {tipp}")


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis,
           mieteinnahmen: float = 0.0,
           mietsteigerung: float = 0.0,
           profil2: Profil | None = None,
           ergebnis2: RentenErgebnis | None = None,
           veranlagung: str = "Getrennt") -> None:
    _rc = st.session_state.get("_rc", 0)
    with T["Dashboard"]:
        st.header("📊 Rentenübersicht")

        hat_partner = profil2 is not None and ergebnis2 is not None
        wahl = "Person 1"
        if hat_partner:
            wahl = st.radio("Ansicht", ["Person 1", "Person 2", "Zusammen"],
                            horizontal=True, key=f"rc{_rc}_dash_person")

        zusammen_modus = wahl == "Zusammen"

        if wahl == "Person 2":
            profil, ergebnis = profil2, ergebnis2

        # ══════════════════════════════════════════════════════════════════════
        # ZUSAMMEN-ANSICHT
        # ══════════════════════════════════════════════════════════════════════
        if zusammen_modus:
            hh = berechne_haushalt(ergebnis, ergebnis2, veranlagung, mieteinnahmen, profil, profil2)

            # Jahressimulationen für Slider (HH kombiniert + Einzelpersonen)
            _g_p1 = 0.0 if profil.ist_pensionaer  or profil.bereits_rentner  else profil.aktuelles_brutto_monatlich
            _g_p2 = 0.0 if profil2.ist_pensionaer or profil2.bereits_rentner else profil2.aktuelles_brutto_monatlich
            _start_p1_ret = profil.rentenbeginn_jahr  if profil.bereits_rentner  else profil.eintritt_jahr
            _start_p2_ret = profil2.rentenbeginn_jahr if profil2.bereits_rentner else profil2.eintritt_jahr
            _start_hh     = min(_start_p1_ret, _start_p2_ret)
            _end_hh       = _start_hh + 30
            _start_slider_hh = AKTUELLES_JAHR if (_g_p1 > 0 or _g_p2 > 0) else _start_hh
            _hz_p1 = _end_hh - _start_p1_ret + 1
            _hz_p2 = _end_hh - _start_p2_ret + 1
            _, _jd_dash    = _netto_ueber_horizont(
                profil, ergebnis, [], _hz_p1, mieteinnahmen, mietsteigerung,
                profil2=profil2, ergebnis2=ergebnis2, veranlagung=veranlagung,
                gehalt_monatlich=_g_p1,
            )
            _, _jd_dash_p1 = _netto_ueber_horizont(profil,  ergebnis,  [], _hz_p1, 0.0, 0.0, gehalt_monatlich=_g_p1)
            _, _jd_dash_p2 = _netto_ueber_horizont(profil2, ergebnis2, [], _hz_p2, 0.0, 0.0, gehalt_monatlich=_g_p2)
            _sel_j_dash = st.slider(
                "Betrachtungsjahr", _start_slider_hh, _end_hh,
                min(_end_hh, max(_start_slider_hh, _start_hh)), key=f"rc{_rc}_dash_jahr",
                help="Zeigt projizierte Haushaltswerte mit Rentenanpassung für das gewählte Jahr.",
            )
            _row_dash    = next((r for r in _jd_dash    if r["Jahr"] == _sel_j_dash), None)
            _row_dash_p1 = next((r for r in _jd_dash_p1 if r["Jahr"] == _sel_j_dash), None)
            _row_dash_p2 = next((r for r in _jd_dash_p2 if r["Jahr"] == _sel_j_dash), None)
            # Einzelnetto für P1 vs P2 Chart (keine Mieteinnahmen → nur Rente)
            _p1_n_y = _row_dash_p1["Netto"]  / 12 if _row_dash_p1 else ergebnis.netto_monatlich
            _p2_n_y = _row_dash_p2["Netto"]  / 12 if _row_dash_p2 else ergebnis2.netto_monatlich
            # P1/P2 Brutto aus Src-Feldern des HH-Datensatzes (ohne Produkte = nur Rente/Gehalt)
            _p1_b_y = (_row_dash.get("Src_GesRente", 0) + _row_dash.get("Src_Gehalt", 0)) / 12 \
                      if _row_dash else ergebnis.brutto_monatlich
            _p2_b_y = _row_dash.get("Src_P2_Rente", 0) / 12 if _row_dash else ergebnis2.brutto_monatlich
            _miete_y = _row_dash.get("Src_Miete", 0) / 12 if _row_dash else mieteinnahmen
            # zvE für Steuerampel
            _zvE_dash = _row_dash["zvE"] if _row_dash else (ergebnis.zvE_jahres + ergebnis2.zvE_jahres + mieteinnahmen * 12)
            _zvE_p1_y = _row_dash_p1["zvE"] if _row_dash_p1 else ergebnis.zvE_jahres
            _zvE_p2_y = _row_dash_p2["zvE"] if _row_dash_p2 else ergebnis2.zvE_jahres
            # Miete wächst mit Mietsteigerung
            _miet_r_y = max(0, _sel_j_dash - _start_hh)
            _miete_zvE_half = mieteinnahmen * (1 + mietsteigerung) ** _miet_r_y * 6  # halbes Jahresmiete je Person

            # Header: beide Personen
            hi1, hi2 = st.columns(2)
            with hi1:
                _ab1 = (
                    f"  |  Abschlag: {ergebnis.rentenabschlag:.1%}".replace(".", ",")
                    if ergebnis.rentenabschlag > 0 else ""
                )
                st.info(
                    f"**P1:** {profil.aktuelles_alter} Jahre  |  "
                    f"Renteneintritt {profil.renteneintritt_alter} ({profil.eintritt_jahr})  |  "
                    f"Noch {profil.jahre_bis_rente} Jahre" + _ab1
                )
            with hi2:
                _ab2 = (
                    f"  |  Abschlag: {ergebnis2.rentenabschlag:.1%}".replace(".", ",")
                    if ergebnis2.rentenabschlag > 0 else ""
                )
                st.info(
                    f"**P2:** {profil2.aktuelles_alter} Jahre  |  "
                    f"Renteneintritt {profil2.renteneintritt_alter} ({profil2.eintritt_jahr})  |  "
                    f"Noch {profil2.jahre_bis_rente} Jahre" + _ab2
                )

            # ── Top-Kennzahlen (Jahr-spezifisch) ─────────────────────────────
            _hh_brutto = _row_dash["Brutto"] / 12 if _row_dash else hh["brutto_gesamt"]
            _hh_netto  = _row_dash["Netto"]  / 12 if _row_dash else hh["netto_gesamt"]
            _hh_steuer = _row_dash["Steuer"] / 12 if _row_dash else hh["steuer_gesamt"]
            _hh_kv     = _row_dash["KV_PV"]  / 12 if _row_dash else hh["kv_gesamt"]
            _hh_kv_p1  = _row_dash["KV_P1"]  / 12 if _row_dash and "KV_P1" in _row_dash else None
            _hh_kv_p2  = _row_dash["KV_P2"]  / 12 if _row_dash and "KV_P2" in _row_dash else None

            c1, c2, c3, c4 = st.columns(4)
            c1.metric(
                f"Brutto Haushalt {_sel_j_dash}", f"{_de(_hh_brutto)} €/Mon.",
                help="Gesetzliche Renten + Zusatzrenten beider Personen + Mieteinnahmen.",
            )
            c2.metric(
                f"Netto Haushalt {_sel_j_dash}", f"{_de(_hh_netto)} €/Mon.",
                help="Nach Einkommensteuer und KV/PV beider Personen.",
            )
            kapital_gesamt = ergebnis.kapital_bei_renteneintritt + ergebnis2.kapital_bei_renteneintritt
            c3.metric(
                "Kapital gesamt (Eintritt)", f"{_de(kapital_gesamt)} €",
                help="Summe des angewachsenen Spar- und Depotkapitals beider Personen.",
            )
            if hh["steuerersparnis_splitting"] > 0:
                c4.metric(
                    "Splitting-Ersparnis / Mon.", f"{_de(hh['steuerersparnis_splitting'])} €",
                    help="Steuerersparnis durch Zusammenveranlagung (§ 32a Abs. 5 EStG) gegenüber getrennter Veranlagung.",
                )
            else:
                c4.metric(f"Steuer {_sel_j_dash} / Mon.", f"{_de(_hh_steuer)} €")

            # ── Zeile 2: P1/P2 Netto + Steuer / KV ──────────────────────────
            c5, c6, c7, c8, c9 = st.columns(5)
            c5.metric(f"P1 Netto {_sel_j_dash}", f"{_de(_p1_n_y)} €/Mon.")
            c6.metric(f"P2 Netto {_sel_j_dash}", f"{_de(_p2_n_y)} €/Mon.")
            c7.metric(f"Steuer {_sel_j_dash} / Mon.", f"{_de(_hh_steuer)} €")
            c8.metric(f"KV/PV {_sel_j_dash} / Mon.", f"{_de(_hh_kv)} €")
            if mieteinnahmen > 0:
                c9.metric(
                    "Mieteinnahmen", f"{_de(mieteinnahmen)} €/Mon.",
                    help="Gemeinsame Nettomieteinnahmen (§ 21 EStG).",
                )
            else:
                c9.metric(
                    "Veranlagung", veranlagung,
                    help="Getrennte oder gemeinsame Einkommensteuerveranlagung.",
                )

            st.divider()

            # ── Wasserfall Haushalt Brutto → Netto ───────────────────────────
            st.subheader(f"Haushalt Brutto → Netto {_sel_j_dash} (monatlich)")
            _wf_x = ["P1 Brutto", "P2 Brutto"]
            _wf_m = ["absolute", "relative"]
            _wf_y = [_p1_b_y, _p2_b_y]
            _wf_t = [
                f"{_de(_p1_b_y)} €",
                f"+{_de(_p2_b_y)} €",
            ]
            if _miete_y > 0:
                _wf_x.append("Mieteinnahmen")
                _wf_m.append("relative")
                _wf_y.append(_miete_y)
                _wf_t.append(f"+{_de(_miete_y)} €")
            _wf_x += ["− Einkommensteuer", "− KV/PV", "Netto Haushalt"]
            _wf_m += ["relative", "relative", "total"]
            _wf_y += [-_hh_steuer, -_hh_kv, _hh_netto]
            _wf_t += [
                f"−{_de(_hh_steuer)} €",
                f"−{_de(_hh_kv)} €",
                f"{_de(_hh_netto)} €",
            ]
            fig_wf = go.Figure(go.Waterfall(
                orientation="v",
                measure=_wf_m,
                x=_wf_x,
                y=_wf_y,
                text=_wf_t,
                textposition="outside",
                connector=dict(line=dict(color="#888")),
                increasing=dict(marker=dict(color="#4CAF50")),
                decreasing=dict(marker=dict(color="#F44336")),
                totals=dict(marker=dict(color="#2196F3")),
            ))
            fig_wf.update_layout(
                template="plotly_white",
                height=380,
                yaxis=dict(title="€ / Monat", ticksuffix=" €"),
                margin=dict(l=10, r=10, t=10, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_wf, use_container_width=True)

            st.divider()

            # ── Vergleich P1 / P2 + Kaufkraft ────────────────────────────────
            left, right = st.columns(2)

            with left:
                st.subheader(f"Nettorente P1 vs. P2 – {_sel_j_dash}")
                fig_bar = go.Figure(go.Bar(
                    x=["Person 1", "Person 2"],
                    y=[_p1_n_y, _p2_n_y],
                    marker_color=["#2196F3", "#4CAF50"],
                    text=[f"{_de(_p1_n_y)} €", f"{_de(_p2_n_y)} €"],
                    textposition="outside",
                    hovertemplate="%{x}: %{y:,.0f} €/Mon.<extra></extra>",
                ))
                fig_bar.update_layout(
                    template="plotly_white", height=300,
                    yaxis=dict(title="Nettorente (€/Mon.)", ticksuffix=" €"),
                    margin=dict(l=10, r=10, t=10, b=10),
                    separators=",.",
                )
                st.plotly_chart(fig_bar, use_container_width=True)

            with right:
                st.subheader(f"Kaufkraft Haushalt heute vs. {_sel_j_dash}")
                _inf_pct_hh = st.number_input(
                    "Inflation p.a. (%)", 0.0, 5.0, 2.0, 0.1,
                    key=f"rc{_rc}_dash_inflation_hh",
                    help="Angenommene jährliche Inflationsrate für die Kaufkraftberechnung.",
                )
                inflation = _inf_pct_hh / 100
                jahre_max = _sel_j_dash - _start_hh + max(profil.jahre_bis_rente, profil2.jahre_bis_rente)
                kaufkraft = _hh_netto / (1 + inflation) ** max(0, jahre_max)
                verlust = _hh_netto - kaufkraft
                st.metric(
                    f"Haushaltsnetto {_sel_j_dash} in heutiger Kaufkraft ({_inf_pct_hh:.1f} % Inflation)".replace(".", ","),
                    f"{_de(kaufkraft)} €",
                    delta=f"−{_de(verlust)} € Kaufkraftverlust",
                    delta_color="inverse",
                )
                st.caption(
                    f"Das Haushaltsnetto von **{_de(_hh_netto)} €** im Jahr {_sel_j_dash} "
                    f"entspricht bei {_inf_pct_hh:.1f} % Inflation".replace(".", ",") +
                    f" der heutigen Kaufkraft von nur **{_de(kaufkraft)} €**."
                )

            st.divider()

            # ── Steuerampel ───────────────────────────────────────────────────
            if veranlagung == "Zusammen":
                st.caption(
                    f"Steuerampel auf Basis des gemeinsamen Haushalts-zvE bei Splitting "
                    f"(§ 32a Abs. 5 EStG). Grenzen = 2 × Einzelperson."
                )
                _steuerampel(_zvE_dash, splitting=True)
            else:
                ac1, ac2 = st.columns(2)
                with ac1:
                    _steuerampel(_zvE_p1_y + _miete_zvE_half, titel="Person 1")
                with ac2:
                    _steuerampel(_zvE_p2_y + _miete_zvE_half, titel="Person 2")

            st.divider()

            with st.expander("🧾 Steuer- & KV-Details Person 1", expanded=False):
                steuern.render_section(profil, ergebnis, mieteinnahmen / 2 if mieteinnahmen > 0 else 0.0)
            with st.expander("🧾 Steuer- & KV-Details Person 2", expanded=False):
                steuern.render_section(profil2, ergebnis2, mieteinnahmen / 2 if mieteinnahmen > 0 else 0.0)

            # Grundsicherungs-Hinweis für beide Personen
            for _gs_label, _gs_netto in [("Person 1", _p1_n_y), ("Person 2", _p2_n_y)]:
                if 0 < _gs_netto < GRUNDSICHERUNG_SCHWELLE:
                    st.warning(
                        f"⚠️ **Grundsicherungsrisiko {_gs_label}:** Nettorente "
                        f"**{_de(_gs_netto)} €/Mon.** im Jahr {_sel_j_dash} "
                        f"unter Grundsicherungsschwelle ca. {_de(GRUNDSICHERUNG_SCHWELLE)} €/Mon. "
                        f"(§ 41 SGB XII)."
                    )

            st.caption(
                "⚠️ Alle Angaben sind Simulationswerte auf Basis vereinfachter Annahmen. "
                "Keine Steuer- oder Anlageberatung."
            )
            return

        # ══════════════════════════════════════════════════════════════════════
        # EINZELPERSON-ANSICHT (Person 1 oder Person 2)
        # ══════════════════════════════════════════════════════════════════════

        # Jahressimulation für Slider (keine Produkte)
        _start_einzel = profil.rentenbeginn_jahr if profil.bereits_rentner else profil.eintritt_jahr
        _g_einzel = 0.0 if profil.ist_pensionaer or profil.bereits_rentner else profil.aktuelles_brutto_monatlich
        _start_slider_einzel = AKTUELLES_JAHR if _g_einzel > 0 else _start_einzel
        _end_einzel = _start_einzel + 30
        _, _jd_dash = _netto_ueber_horizont(profil, ergebnis, [], 31, mieteinnahmen, mietsteigerung, gehalt_monatlich=_g_einzel)
        _sel_j_dash = st.slider(
            "Betrachtungsjahr", _start_slider_einzel, _end_einzel,
            min(_end_einzel, max(_start_slider_einzel, _start_einzel)), key=f"rc{_rc}_dash_jahr",
            help="Zeigt projizierte Jahreswerte mit Rentenanpassung für das gewählte Jahr.",
        )
        _row_dash = next((r for r in _jd_dash if r["Jahr"] == _sel_j_dash), None)
        _d_brutto = _row_dash["Brutto"] / 12 if _row_dash else ergebnis.brutto_monatlich
        _d_netto  = _row_dash["Netto"]  / 12 if _row_dash else ergebnis.netto_monatlich
        _d_steuer = _row_dash["Steuer"] / 12 if _row_dash else ergebnis.steuer_monatlich
        _d_kv     = _row_dash["KV_PV"]  / 12 if _row_dash else ergebnis.kv_monatlich
        _d_zvE    = _row_dash["zvE"]         if _row_dash else ergebnis.zvE_jahres

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

        # ── Kennzahlen (Jahr-spezifisch via Slider) ───────────────────────────
        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            f"Bruttorente {_sel_j_dash}", f"{_de(_d_brutto)} €/Mon.",
            help="Gesetzliche Rente + Zusatzrente vor Steuer und KV-Abzügen.",
        )
        c2.metric(
            f"Nettorente {_sel_j_dash}", f"{_de(_d_netto)} €/Mon.",
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

        # KV/PV-Split berechnen (Eintrittsmonat-Verhältnis auf Jahr-KV anwenden)
        _kv_ratio = _kv_pv_split(profil, ergebnis.kv_monatlich, ergebnis)
        _kv_total_ratio = ergebnis.kv_monatlich if ergebnis.kv_monatlich > 0 else 1.0
        _kv_share_gkv = _kv_ratio[0] / _kv_total_ratio
        _kv_share_pv  = _kv_ratio[1] / _kv_total_ratio
        gkv_mono = _d_kv * _kv_share_gkv
        pv_mono  = _d_kv * _kv_share_pv
        _kv_label = "PKV / Monat" if profil.krankenversicherung == "PKV" else "KV / Monat"

        c5, c6, c7, c8, c9 = st.columns(5)
        c5.metric(
            "Gesetzl. Rente (brutto, Eintritt)", f"{_de(ergebnis.brutto_gesetzlich)} €/Mon.",
            help=f"Rentenabschlag: {ergebnis.rentenabschlag:.1%}".replace(".", ",") + " (§ 77 SGB VI)"
                 if ergebnis.rentenabschlag > 0 else None,
        )
        c6.metric(f"Steuer {_sel_j_dash} / Mon.", f"{_de(_d_steuer)} €")
        c7.metric(
            f"{_kv_label} {_sel_j_dash}", f"{_de(gkv_mono)} €",
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

        # ── Grundsicherungs-Hinweis ───────────────────────────────────────────
        if _d_netto < GRUNDSICHERUNG_SCHWELLE and _d_netto > 0:
            st.warning(
                f"⚠️ **Grundsicherungsrisiko:** Die projizierte Nettorente von "
                f"**{_de(_d_netto)} €/Mon.** im Jahr {_sel_j_dash} liegt unter der "
                f"Grundsicherungsschwelle von ca. {_de(GRUNDSICHERUNG_SCHWELLE)} €/Mon. "
                f"(§ 41 SGB XII). Ein ergänzender Anspruch auf Grundsicherung im Alter "
                f"könnte bestehen. Bitte prüfen Sie zusätzliche Vorsorgemöglichkeiten "
                f"(Riester, bAV, Rürup) und ggf. einen späteren Renteneintritt."
            )

        st.divider()

        # ── Wasserfall Brutto → Netto ─────────────────────────────────────────
        st.subheader(f"Brutto → Netto {_sel_j_dash} (monatlich)")
        fig_wf = go.Figure(go.Waterfall(
            orientation="v",
            measure=["absolute", "relative", "relative", "relative", "total"],
            x=["Bruttorente", "− Einkommensteuer", "− KV", "− PV", "Nettorente"],
            y=[
                _d_brutto,
                -_d_steuer,
                -gkv_mono,
                -pv_mono,
                _d_netto,
            ],
            text=[
                f"{_de(_d_brutto)} €",
                f"−{_de(_d_steuer)} €",
                f"−{_de(gkv_mono)} €",
                f"−{_de(pv_mono)} €",
                f"{_de(_d_netto)} €",
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
            st.subheader(f"Kaufkraft heute vs. {_sel_j_dash}")
            _inf_pct = st.number_input(
                "Inflation p.a. (%)", 0.0, 5.0, 2.0, 0.1,
                key=f"rc{_rc}_dash_inflation",
                help="Angenommene jährliche Inflationsrate für die Kaufkraftberechnung.",
            )
            inflation = _inf_pct / 100
            jahre_inflation = _sel_j_dash - profil.eintritt_jahr + profil.jahre_bis_rente
            kaufkraft = _d_netto / (1 + inflation) ** max(0, jahre_inflation)
            verlust = _d_netto - kaufkraft
            st.metric(
                f"Nettorente {_sel_j_dash} in heutiger Kaufkraft ({_inf_pct:.1f} % Inflation)".replace(".", ","),
                f"{_de(kaufkraft)} €",
                delta=f"−{_de(verlust)} € Kaufkraftverlust",
                delta_color="inverse",
            )
            st.caption(
                f"Die Nettorente von **{_de(_d_netto)} €** im Jahr {_sel_j_dash} "
                f"entspricht bei {_inf_pct:.1f} % Inflation".replace(".", ",") +
                f" der heutigen Kaufkraft von nur **{_de(kaufkraft)} €**. "
                f"Die eigene Rentenanpassungs-Annahme von "
                f"{profil.rentenanpassung_pa:.0%}".replace(".", ",") + " p.a. "
                f"{'federt dies ab' if profil.rentenanpassung_pa >= inflation else 'deckt dies nicht vollständig ab'}."
            )

        st.divider()

        _zvE_ampel = _d_zvE + mieteinnahmen * 12
        _steuerampel(_zvE_ampel)

        st.divider()

        with st.expander("🔎 Was-wäre-wenn: Steuerzone", expanded=False):
            st.caption(
                "Verschieben Sie den Slider, um zu sehen, wie sich ein "
                "zusätzliches Einkommen (z.B. Einmalentnahme, Mieterhöhung, "
                "Nebenverdienst) auf Ihren Grenzsteuersatz auswirkt."
            )
            _ww_extra = st.slider(
                "Zusätzliches Jahreseinkommen (€)", 0, 50_000,
                value=0, step=500, key=f"rc{_rc}_dash_ww_extra",
            )
            _zvE_ww = _zvE_ampel + _ww_extra
            _est_vorher = einkommensteuer(_zvE_ampel)
            _soli_vorher = solidaritaetszuschlag(_est_vorher)
            _est_nachher = einkommensteuer(_zvE_ww)
            _soli_nachher = solidaritaetszuschlag(_est_nachher)
            _mehrsteuer = (_est_nachher + _soli_nachher) - (_est_vorher + _soli_vorher)
            if _ww_extra > 0:
                ww1, ww2, ww3, ww4 = st.columns(4)
                ww1.metric("zvE vorher", f"{_de(_zvE_ampel)} €")
                ww2.metric("zvE nachher", f"{_de(_zvE_ww)} €", delta=f"+{_de(_ww_extra)} €")
                ww3.metric("Jahressteuer vorher", f"{_de(_est_vorher + _soli_vorher)} €")
                ww4.metric(
                    "Mehrsteuer (ESt + Soli)", f"{_de(_mehrsteuer)} €",
                    delta=f"{_mehrsteuer / _ww_extra:.1%} Grenzbelastung".replace(".", ","),
                    delta_color="inverse",
                )
                _steuerampel(_zvE_ww, titel="Mit Zusatzeinkommen")

        st.divider()

        with st.expander("🧾 Steuer- & KV-Details", expanded=False):
            steuern.render_section(profil, ergebnis, mieteinnahmen)

        # ── HTML-Export ───────────────────────────────────────────────────────
        with st.expander("📄 Zusammenfassung exportieren", expanded=False):
            _html = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8">
<title>Rentenübersicht – {_sel_j_dash}</title>
<style>body{{font-family:sans-serif;max-width:800px;margin:2em auto}}
table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:.4em .8em}}th{{background:#f0f0f0}}
h2{{color:#1976d2}}</style></head><body>
<h1>Rentenübersicht {_sel_j_dash}</h1>
<p><em>Erstellt: {__import__('datetime').date.today()}</em></p>
<h2>Kennzahlen</h2>
<table>
<tr><th>Kennzahl</th><th>Wert</th></tr>
<tr><td>Bruttorente</td><td>{_de(_d_brutto)} €/Mon.</td></tr>
<tr><td>Nettorente</td><td>{_de(_d_netto)} €/Mon.</td></tr>
<tr><td>Einkommensteuer</td><td>{_de(_d_steuer)} €/Mon.</td></tr>
<tr><td>KV/PV</td><td>{_de(_d_kv)} €/Mon.</td></tr>
<tr><td>zvE (Jahr)</td><td>{_de(_d_zvE)} €/Jahr</td></tr>
<tr><td>Kapital bei Renteneintritt</td><td>{_de(ergebnis.kapital_bei_renteneintritt)} €</td></tr>
<tr><td>Rentenpunkte gesamt</td><td>{ergebnis.gesamtpunkte:.1f}</td></tr>
</table>
<h2>Profil</h2>
<table>
<tr><th>Feld</th><th>Wert</th></tr>
<tr><td>Geburtsjahr</td><td>{profil.geburtsjahr}</td></tr>
<tr><td>Renteneintrittsalter</td><td>{profil.renteneintritt_alter}</td></tr>
<tr><td>Renteneintrittsjahr</td><td>{profil.eintritt_jahr}</td></tr>
<tr><td>Krankenversicherung</td><td>{profil.krankenversicherung}</td></tr>
</table>
<p style="color:#888;font-size:.9em">⚠️ Simulationswerte – keine Steuer- oder Anlageberatung.</p>
</body></html>"""
            st.download_button(
                "⬇️ HTML herunterladen",
                data=_html.encode("utf-8"),
                file_name=f"rente_{_sel_j_dash}.html",
                mime="text/html",
            )
            st.caption("Die HTML-Datei kann im Browser geöffnet und als PDF gedruckt werden (Strg+P).")

        st.caption(
            "⚠️ Alle Angaben sind Simulationswerte auf Basis vereinfachter Annahmen. "
            "Keine Steuer- oder Anlageberatung."
        )
