"""Simulation-Tab – Szenarien-Vergleich und Kapitalentwicklung."""

from dataclasses import replace as _dc_replace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    AKTUELLES_JAHR, Profil, RentenErgebnis,
    berechne_haushalt, berechne_rente, kapitalwachstum,
    simuliere_szenarien, _netto_ueber_horizont,
)
from tabs.utils import render_zeitstrahl

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
    _rc = st.session_state.get("_rc", 0)
    with T["Simulation"]:
        st.header("🔮 Szenarien-Simulation")

        hat_partner = profil2 is not None and ergebnis2 is not None
        wahl = "Person 1"
        if hat_partner:
            wahl = st.radio("Ansicht", ["Person 1", "Person 2", "Zusammen"],
                            horizontal=True, key=f"rc{_rc}_sim_person")

        zusammen_modus = wahl == "Zusammen"

        _profil1_kap = profil  # P1 vor potenziellem Swap – für Gesamtkapital-Anzeige

        if wahl == "Person 2":
            profil, ergebnis = profil2, ergebnis2

        if zusammen_modus:
            sz1 = simuliere_szenarien(profil)
            sz2 = simuliere_szenarien(profil2)
            szenarien = sz1
        elif hat_partner:
            sz1 = simuliere_szenarien(_profil1_kap)
            sz2 = simuliere_szenarien(profil2)
            szenarien = simuliere_szenarien(profil)
        else:
            szenarien = simuliere_szenarien(profil)

        # ── Jahresslider ─────────────────────────────────────────────────────
        _start_p1_ret = profil.rentenbeginn_jahr if profil.bereits_rentner else profil.eintritt_jahr
        if zusammen_modus:
            _start_p2_ret = profil2.rentenbeginn_jahr if profil2.bereits_rentner else profil2.eintritt_jahr
            _start_ret = min(_start_p1_ret, _start_p2_ret)
        else:
            _start_p2_ret = _start_p1_ret
            _start_ret = _start_p1_ret
        _end_sim = _start_ret + 30
        _g_sim = 0.0 if profil.ist_pensionaer or profil.bereits_rentner else profil.aktuelles_brutto_monatlich
        _start_slider_sim = AKTUELLES_JAHR if _g_sim > 0 else _start_ret
        betrachtungsjahr = render_zeitstrahl(
            _rc, _start_slider_sim, _end_sim,
            min(_end_sim, max(_start_slider_sim, _start_ret)), "_sim",
            help_text="Zeigt projizierte Werte mit Rentenanpassung für das gewählte Jahr.",
        )

        # ── Genaue Jahressimulation je Szenario ──────────────────────────────
        # Ersetzt die bisherige Näherung netto_eintritt × (1+anp)^n durch
        # vollständige Jahressimulation mit korrekter Steuerprogression.
        # gehalt_monatlich wird mitgegeben, damit Vorjahre (vor Renteneintritt) abgedeckt sind.
        def _sim_laufende_entsch(person: str | None = None) -> list:
            try:
                from tabs.vorsorge import _aus_dict as _vd, _migriere as _vm
            except ImportError:
                return []
            _entsch = []
            for d in st.session_state.get("vp_produkte", []):
                d = _vm(d)
                if person is not None and d.get("person", "Person 1") != person:
                    continue
                if d.get("als_kapitalanlage", False):
                    if float(d.get("max_einmalzahlung", 0.0)) > 0:
                        try:
                            _entsch.append((_vd(d), int(d.get("fruehestes_startjahr", AKTUELLES_JAHR + 5)), 1.0))
                        except Exception:
                            pass
                    continue
                if float(d.get("max_monatsrente", 0.0)) <= 0:
                    continue
                try:
                    _entsch.append((_vd(d), int(d.get("fruehestes_startjahr", AKTUELLES_JAHR + 5)), 0.0))
                except Exception:
                    pass
            return _entsch

        _entsch_sim_all = _sim_laufende_entsch(None)
        _entsch_sim_p1  = _sim_laufende_entsch("Person 1") if not zusammen_modus else []
        _person_label_sim = "Person 2" if wahl == "Person 2" else "Person 1"
        _entsch_sim_ep  = _sim_laufende_entsch(_person_label_sim)

        _sz_jd: dict[str, dict[int, dict]] = {}
        for _nm in ["Pessimistisch", "Neutral", "Optimistisch"]:
            _rpa, _kpa = _PARAMS[_nm]
            if _rpa is None:
                _rpa = profil.rentenanpassung_pa
                _kpa = profil.rendite_pa
            if zusammen_modus and profil2 is not None:
                _p1_n = _dc_replace(profil, rentenanpassung_pa=_rpa, rendite_pa=_kpa)
                _e1_n = berechne_rente(_p1_n)
                _p2_n = _dc_replace(profil2, rentenanpassung_pa=_rpa, rendite_pa=_kpa)
                _e2_n = berechne_rente(_p2_n)
                _, _jd_n = _netto_ueber_horizont(
                    _p1_n, _e1_n, _entsch_sim_all, 32, mieteinnahmen, 0.0,
                    profil2=_p2_n, ergebnis2=_e2_n, veranlagung=veranlagung,
                    gehalt_monatlich=_g_sim,
                )
            else:
                _p_n = _dc_replace(profil, rentenanpassung_pa=_rpa, rendite_pa=_kpa)
                _e_n = berechne_rente(_p_n)
                _, _jd_n = _netto_ueber_horizont(_p_n, _e_n, _entsch_sim_ep, 32, 0.0, 0.0,
                                                  gehalt_monatlich=_g_sim)
            _sz_jd[_nm] = {r["Jahr"]: r for r in _jd_n}

        _vor_rente = betrachtungsjahr < _start_ret

        # ── Szenario-Vergleich Tabelle ────────────────────────────────────────
        _phase_label = " (Erwerbsphase)" if _vor_rente else ""
        st.subheader(f"Vergleich der drei Szenarien – {betrachtungsjahr}{_phase_label}")
        rows = []
        namen = ["Pessimistisch", "Neutral", "Optimistisch"]
        for name in namen:
            ren_pa, kap_pa = _PARAMS[name]
            if ren_pa is None:
                ren_pa = profil.rentenanpassung_pa
                kap_pa = profil.rendite_pa
            _row_n = _sz_jd[name].get(betrachtungsjahr)
            if zusammen_modus:
                kapital = (sz1[name].kapital_bei_renteneintritt
                           + sz2[name].kapital_bei_renteneintritt)
                _brutto_hh = _row_n["Brutto"] / 12 if _row_n else 0.0
                _netto_hh  = _row_n["Netto"]  / 12 if _row_n else 0.0
                _bav_hh    = (_row_n.get("Src_bAV_P1", 0) + _row_n.get("Src_bAV_P2", 0)) / 12 if _row_n else 0.0
                _rie_hh    = (_row_n.get("Src_Riester_P1", 0) + _row_n.get("Src_Riester_P2", 0)) / 12 if _row_n else 0.0
                _row_dict = {
                    "Szenario": name,
                    "Rentenanpassung p.a.": f"{ren_pa:.1%}".replace(".", ","),
                    "Kapitalrendite p.a.": f"{kap_pa:.1%}".replace(".", ","),
                    "Brutto Haushalt (€/Mon.)": _de(_brutto_hh),
                    "Netto Haushalt (€/Mon.)": _de(_netto_hh),
                    "Kapital gesamt (€)": _de(kapital),
                }
                if _bav_hh > 0: _row_dict["davon bAV (€/Mon.)"] = _de(_bav_hh)
                if _rie_hh > 0: _row_dict["davon Riester (€/Mon.)"] = _de(_rie_hh)
                rows.append(_row_dict)
            else:
                erg = szenarien[name]
                _brutto_val = _row_n["Brutto"] / 12 if _row_n else 0.0
                _netto_val  = _row_n["Netto"]  / 12 if _row_n else 0.0
                _bav_val    = _row_n.get("Src_bAV_P1", 0) / 12 if _row_n else 0.0
                _rie_val    = _row_n.get("Src_Riester_P1", 0) / 12 if _row_n else 0.0
                _kap_gesamt = (sz1[name].kapital_bei_renteneintritt + sz2[name].kapital_bei_renteneintritt
                               if hat_partner else erg.kapital_bei_renteneintritt)
                _row_dict = {
                    "Szenario": name,
                    "Rentenanpassung p.a.": f"{ren_pa:.1%}".replace(".", ","),
                    "Kapitalrendite p.a.": f"{kap_pa:.1%}".replace(".", ","),
                    "Brutto (€/Mon.)": _de(_brutto_val),
                    "Netto (€/Mon.)": _de(_netto_val),
                    "Kapital gesamt (€)": _de(_kap_gesamt),
                    "Rentenpunkte": f"{erg.gesamtpunkte:.1f}".replace(".", ","),
                }
                if _bav_val > 0: _row_dict["davon bAV (€/Mon.)"] = _de(_bav_val)
                if _rie_val > 0: _row_dict["davon Riester (€/Mon.)"] = _de(_rie_val)
                rows.append(_row_dict)
        st.dataframe(
            pd.DataFrame(rows).set_index("Szenario"),
            use_container_width=True,
        )
        st.caption("Brutto/Netto: vollständige Jahressimulation mit korrekter Steuerprogression.")

        st.divider()

        # ── Nettorente / Haushalt Szenarien ───────────────────────────────────
        col_l, col_r = st.columns(2)

        with col_l:
            if zusammen_modus:
                _hh_titel = "Netto Haushalt" if not _vor_rente else "Netto Haushalt (Erwerbsphase)"
                st.subheader(f"{_hh_titel} {betrachtungsjahr}")
                y_title = "Netto Haushalt (€/Monat)"
            else:
                _ep_titel = "Nettorente" if not _vor_rente else "Nettoeinkommen (Erwerbsphase)"
                st.subheader(f"{_ep_titel} {betrachtungsjahr}")
                y_title = "Netto (€/Monat)"
            netto_vals = []
            for n in namen:
                _row_n = _sz_jd[n].get(betrachtungsjahr)
                netto_vals.append(_row_n["Netto"] / 12 if _row_n else 0.0)
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
            st.subheader("Kapital bei Renteneintritt (Haushalt gesamt)")
            if hat_partner:
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
        st.subheader("Kapitalentwicklung bis Renteneintritt (Haushalt gesamt)" if hat_partner
                     else "Kapitalentwicklung bis Renteneintritt")
        _kap_profil = _profil1_kap  # immer P1-Kapital als Basis (Haushaltsvermögen)
        jahre_range = list(range(_kap_profil.jahre_bis_rente + 1))
        jahre_labels = [AKTUELLES_JAHR + j for j in jahre_range]

        renditen = {
            "Pessimistisch": 0.03,
            "Neutral":       _kap_profil.rendite_pa,
            "Optimistisch":  0.07,
        }

        fig_k = go.Figure()
        for name, r in renditen.items():
            werte = [kapitalwachstum(_kap_profil.sparkapital, _kap_profil.sparrate, r, j)
                     for j in jahre_range]
            if hat_partner and profil2 is not None:
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
        if jahre_labels and AKTUELLES_JAHR <= betrachtungsjahr <= _start_p1_ret:
            fig_k.add_vline(
                x=betrachtungsjahr, line_width=1, line_dash="dot", line_color="#FF9800",
                annotation_text=str(betrachtungsjahr), annotation_position="top right",
            )
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
        if not zusammen_modus and not profil.ist_pensionaer:
            _person_label = wahl if hat_partner else ""
            st.subheader(
                f"Nettorente nach Renteneintrittsalter"
                + (f" – {_person_label}" if _person_label else "")
            )
            st.caption("Wie stark beeinflusst das Renteneintrittsalter die Nettorente?")

            alter_range = list(range(60, 71))
            netto_alter = []
            for a in alter_range:
                p_var = _dc_replace(profil, renteneintritt_alter=a)
                netto_alter.append(berechne_rente(p_var).netto_monatlich)

            fig_alter = go.Figure(go.Scatter(
                x=alter_range,
                y=netto_alter,
                mode="lines+markers",
                line=dict(color="#2196F3", width=2),
                marker=dict(size=8),
                hovertemplate="Alter %{x}: %{y:,.0f} €/Mon.<extra></extra>",
            ))
            _vline_label = (
                f"{wahl}: Alter {profil.renteneintritt_alter}"
                if hat_partner
                else f"Ihr Alter: {profil.renteneintritt_alter}"
            )
            fig_alter.add_vline(
                x=profil.renteneintritt_alter,
                line_dash="dash",
                line_color="#FF9800",
                annotation_text=_vline_label,
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
