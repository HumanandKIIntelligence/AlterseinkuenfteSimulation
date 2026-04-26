"""Haushalt-Tab – Gemeinsame Einkommensübersicht für Ehepaare."""

from dataclasses import replace as _dc_replace

import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from engine import (
    AKTUELLES_JAHR, Profil, RentenErgebnis,
    berechne_haushalt, berechne_rente, einkommensteuer_splitting,
    simuliere_szenarien, _netto_ueber_horizont,
)


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


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
    _rc = st.session_state.get("_rc", 0)
    with T["Haushalt"]:
        st.header("👥 Haushalts-Übersicht")

        veranlagung_label = "Zusammenveranlagung (Splitting)" if veranlagung == "Zusammen" \
            else "Getrennte Veranlagung"

        def _status(p: Profil) -> str:
            if p.bereits_rentner:
                return f"Im Ruhestand seit {p.rentenbeginn_jahr}"
            return f"Renteneintritt {p.eintritt_jahr}"

        st.info(
            f"**Steuerliche Veranlagung:** {veranlagung_label}  |  "
            f"**Person 1:** {_status(p1)}  |  "
            f"**Person 2:** {_status(p2)}"
        )

        # ── Jahres- und Personenfilter ─────────────────────────────────────────
        fil1, fil2 = st.columns([2, 3])
        with fil1:
            ansicht = st.radio(
                "Ansicht",
                ["Haushalt gesamt", "Person 1", "Person 2"],
                horizontal=True, key=f"rc{_rc}_hh_ansicht",
            )
        with fil2:
            # Arbeits- und Renteneinkommen pro Person
            _gehalt_p1 = 0.0 if p1.ist_pensionaer or p1.bereits_rentner else p1.aktuelles_brutto_monatlich
            _gehalt_p2 = 0.0 if p2.ist_pensionaer or p2.bereits_rentner else p2.aktuelles_brutto_monatlich

            # Simulationshorizont: frühester Renteneintritt bis +30 Jahre
            _start_p1 = p1.rentenbeginn_jahr if p1.bereits_rentner else p1.eintritt_jahr
            _start_p2 = p2.rentenbeginn_jahr if p2.bereits_rentner else p2.eintritt_jahr
            _start_j_ret = min(_start_p1, _start_p2)
            _end_j = _start_j_ret + 30

            # Slider beginnt ab AKTUELLES_JAHR wenn jemand noch berufstätig ist
            _start_j = AKTUELLES_JAHR if (_gehalt_p1 > 0 or _gehalt_p2 > 0) else _start_j_ret
            _default_j = min(_end_j, max(_start_j, AKTUELLES_JAHR))
            betrachtungsjahr = st.slider(
                "Betrachtungsjahr", _start_j, _end_j, _default_j,
                key=f"rc{_rc}_hh_jahr",
                help="Zeigt projizierte Einkommenswerte für das gewählte Jahr (mit Rentenanpassung).",
            )

        # Jahresverlauf berechnen (keine Produkte); individuelle Horizonte je Person
        _horizont_hh = _end_j - _start_j_ret + 1
        _horizont_p1 = max(1, _end_j - _start_p1 + 1)
        _horizont_p2 = max(1, _end_j - _start_p2 + 1)
        _, _jd_zus = _netto_ueber_horizont(
            p1, e1, [], _horizont_hh, mieteinnahmen, mietsteigerung,
            profil2=p2, ergebnis2=e2, veranlagung="Zusammen",
        )
        _, _jd_get = _netto_ueber_horizont(
            p1, e1, [], _horizont_hh, mieteinnahmen, mietsteigerung,
            profil2=p2, ergebnis2=e2, veranlagung="Getrennt",
        )
        _jd_hh = _jd_zus if veranlagung == "Zusammen" else _jd_get
        _, _jd_p1 = _netto_ueber_horizont(p1, e1, [], _horizont_p1, 0.0, 0.0,
                                           gehalt_monatlich=_gehalt_p1)
        _, _jd_p2 = _netto_ueber_horizont(p2, e2, [], _horizont_p2, 0.0, 0.0,
                                           gehalt_monatlich=_gehalt_p2)

        def _row_for_year(jd: list[dict], jahr: int) -> dict | None:
            for r in jd:
                if r["Jahr"] == jahr:
                    return r
            return None

        # _jd_hh startet erst ab P1's Renteneintritt – für frühere Jahre (z.B. wenn P2
        # früher in Rente geht) werden P1- und P2-Einzeldaten addiert.
        _hh_by_y = {r["Jahr"]: r for r in _jd_hh}
        _p1_by_y = {r["Jahr"]: r for r in _jd_p1}
        _p2_by_y = {r["Jahr"]: r for r in _jd_p2}
        _all_jahre = sorted(set(_hh_by_y) | set(_p1_by_y) | set(_p2_by_y))
        _jd_combined: list[dict] = []
        for _j in _all_jahre:
            if _j in _hh_by_y:
                _jd_combined.append(_hh_by_y[_j])
            else:
                _r1 = _p1_by_y.get(_j)
                _r2 = _p2_by_y.get(_j)
                _jd_combined.append({
                    "Jahr":   _j,
                    "Brutto": (_r1["Brutto"] if _r1 else 0) + (_r2["Brutto"] if _r2 else 0),
                    "Netto":  (_r1["Netto"]  if _r1 else 0) + (_r2["Netto"]  if _r2 else 0),
                    "Steuer": (_r1["Steuer"] if _r1 else 0) + (_r2["Steuer"] if _r2 else 0),
                    "KV_PV":  (_r1["KV_PV"]  if _r1 else 0) + (_r2["KV_PV"]  if _r2 else 0),
                })

        _row_comb = _row_for_year(_jd_combined, betrachtungsjahr)
        _row_p1   = _row_for_year(_jd_p1,       betrachtungsjahr)
        _row_p2   = _row_for_year(_jd_p2,        betrachtungsjahr)

        # ── Kennzahlen für gewähltes Jahr ─────────────────────────────────────
        st.subheader(f"Monatseinkommen {betrachtungsjahr}")
        c1, c2, c3, c4 = st.columns(4)

        _no_data = False
        if ansicht == "Haushalt gesamt" and _row_comb:
            _b = _row_comb["Brutto"] / 12
            _n = _row_comb["Netto"] / 12
            _s = _row_comb["Steuer"] / 12
            _k = _row_comb["KV_PV"] / 12
            _label = "Haushalt gesamt"
        elif ansicht == "Haushalt gesamt":
            _b = hh["brutto_gesamt"]
            _n = hh["netto_gesamt"]
            _s = hh["steuer_gesamt"]
            _k = hh["kv_gesamt"]
            _label = "Haushalt (Eintrittsmonat)"
        elif ansicht == "Person 1" and _row_p1:
            _b = _row_p1["Brutto"] / 12
            _n = _row_p1["Netto"] / 12
            _s = _row_p1["Steuer"] / 12
            _k = _row_p1["KV_PV"] / 12
            _label = "Person 1"
        elif ansicht == "Person 2" and _row_p2:
            _b = _row_p2["Brutto"] / 12
            _n = _row_p2["Netto"] / 12
            _s = _row_p2["Steuer"] / 12
            _k = _row_p2["KV_PV"] / 12
            _label = "Person 2"
        else:
            _no_data = True
            _start_sel = _start_p1 if ansicht == "Person 1" else _start_p2
            st.info(
                f"Für **{ansicht}** liegen für {betrachtungsjahr} noch keine Daten vor "
                f"(Renteneintritt: {_start_sel}). "
                f"Bruttogehalt im Profil eingeben, um Berufsjahre zu simulieren."
            )

        if not _no_data:
            c1.metric("Brutto", f"{_de(_b)} €",
                      help=f"{_label}: Bruttoeinkommen inkl. Mieteinnahmen")
            c2.metric("Netto", f"{_de(_n)} €")
            c3.metric("Steuer", f"{_de(_s)} €/Mon.")
            c4.metric("KV / PV", f"{_de(_k)} €/Mon.")

        if ansicht == "Haushalt gesamt" and hh["steuerersparnis_splitting"] > 0:
            st.caption(
                f"Splitting-Vorteil (laufend): **{_de(hh['steuerersparnis_splitting'])} €/Mon.** "
                f"| **{_de(hh['steuerersparnis_splitting'] * 12)} €/Jahr**"
            )

        st.divider()

        # ── Seite-an-Seite Vergleich ──────────────────────────────────────────
        if ansicht != "Haushalt gesamt":
            # Einzelpersonen-Ansicht – Slider-Jahr oder Eintrittsmonat als Fallback
            _e   = e1 if ansicht == "Person 1" else e2
            _p   = p1 if ansicht == "Person 1" else p2
            _row = _row_p1 if ansicht == "Person 1" else _row_p2
            _b_d = _row["Brutto"] / 12 if _row else _e.brutto_monatlich
            _n_d = _row["Netto"]  / 12 if _row else _e.netto_monatlich
            _s_d = _row["Steuer"] / 12 if _row else _e.steuer_monatlich
            _k_d = _row["KV_PV"]  / 12 if _row else _e.kv_monatlich
            _note = "" if _row else " (Eintrittsmonat)"
            st.subheader(f"{ansicht} – {betrachtungsjahr}{_note}")
            cv1, cv2 = st.columns(2)
            with cv1:
                for label, wert in [
                    ("Bruttoeinkommen", f"{_de(_b_d)} €"),
                    ("− Steuer", f"{_de(_s_d)} €"),
                    ("− KV / PV", f"{_de(_k_d)} €"),
                    ("**= Netto**", f"**{_de(_n_d)} €**"),
                    ("Rentenpunkte", f"{_e.gesamtpunkte:.1f}".replace(".", ",")),
                    ("Renteneintritt",
                     str(_p.rentenbeginn_jahr if _p.bereits_rentner else _p.eintritt_jahr)),
                ]:
                    a, b = st.columns([2, 1])
                    a.markdown(label)
                    b.markdown(wert)
        else:
            # Jahr-spezifische Werte aus Slider; Fallback auf Eintrittsmonat
            _p1_b = _row_p1["Brutto"] / 12 if _row_p1 else e1.brutto_monatlich
            _p1_n = _row_p1["Netto"]  / 12 if _row_p1 else e1.netto_monatlich
            _p1_s = _row_p1["Steuer"] / 12 if _row_p1 else e1.steuer_monatlich
            _p1_k = _row_p1["KV_PV"]  / 12 if _row_p1 else e1.kv_monatlich
            _p2_b = _row_p2["Brutto"] / 12 if _row_p2 else e2.brutto_monatlich
            _p2_n = _row_p2["Netto"]  / 12 if _row_p2 else e2.netto_monatlich
            _p2_s = _row_p2["Steuer"] / 12 if _row_p2 else e2.steuer_monatlich
            _p2_k = _row_p2["KV_PV"]  / 12 if _row_p2 else e2.kv_monatlich
            _note = "" if (_row_p1 and _row_p2) else " (Eintrittsmonat)"

            st.subheader(f"Person 1 vs. Person 2 – {betrachtungsjahr}{_note}")
            col1, col2, col3 = st.columns([2, 2, 3])

            with col1:
                st.markdown("**Person 1**")
                for label, wert in [
                    ("Bruttoeinkommen", f"{_de(_p1_b)} €"),
                    ("− Steuer", f"{_de(_p1_s)} €"),
                    ("− KV / PV", f"{_de(_p1_k)} €"),
                    ("**= Netto**", f"**{_de(_p1_n)} €**"),
                    ("Rentenpunkte", f"{e1.gesamtpunkte:.1f}".replace(".", ",")),
                    ("Ruhestand seit" if p1.bereits_rentner else "Renteneintritt",
                     str(p1.rentenbeginn_jahr if p1.bereits_rentner else p1.eintritt_jahr)),
                ]:
                    a, b = st.columns([2, 1])
                    a.markdown(label)
                    b.markdown(wert)

            with col2:
                st.markdown("**Person 2**")
                for label, wert in [
                    ("Bruttoeinkommen", f"{_de(_p2_b)} €"),
                    ("− Steuer", f"{_de(_p2_s)} €"),
                    ("− KV / PV", f"{_de(_p2_k)} €"),
                    ("**= Netto**", f"**{_de(_p2_n)} €**"),
                    ("Rentenpunkte", f"{e2.gesamtpunkte:.1f}".replace(".", ",")),
                    ("Ruhestand seit" if p2.bereits_rentner else "Renteneintritt",
                     str(p2.rentenbeginn_jahr if p2.bereits_rentner else p2.eintritt_jahr)),
                ]:
                    a, b = st.columns([2, 1])
                    a.markdown(label)
                    b.markdown(wert)

            with col3:
                # Stacked bar: Netto + Steuer + KV = Brutto (Total-Höhe)
                personen = ["Person 1", "Person 2"]
                fig = go.Figure()
                fig.add_trace(go.Bar(
                    name="Netto", x=personen, y=[_p1_n, _p2_n],
                    marker_color="#A5D6A7",
                    text=[f"{_de(_p1_n)} €", f"{_de(_p2_n)} €"],
                    textposition="inside",
                ))
                fig.add_trace(go.Bar(
                    name="− Steuer", x=personen, y=[_p1_s, _p2_s],
                    marker_color="#EF9A9A",
                    text=[f"{_de(_p1_s)} €", f"{_de(_p2_s)} €"],
                    textposition="inside",
                ))
                fig.add_trace(go.Bar(
                    name="− KV/PV", x=personen, y=[_p1_k, _p2_k],
                    marker_color="#FFF176",
                    text=[f"{_de(_p1_k)} €", f"{_de(_p2_k)} €"],
                    textposition="inside",
                ))
                fig.update_layout(
                    barmode="stack",
                    template="plotly_white",
                    height=320,
                    yaxis=dict(title="€ / Monat (Brutto = Gesamthöhe)"),
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    margin=dict(l=0, r=0, t=30, b=0),
                    separators=",.",
                )
                st.plotly_chart(fig, use_container_width=True)

        if mieteinnahmen > 0:
            st.info(
                f"🏠 **Mieteinnahmen:** {_de(mieteinnahmen)} €/Monat "
                f"(+{mietsteigerung:.1%}".replace(".", ",") +
                " p.a.) – in Steuerberechnung enthalten, keine KV-Pflicht."
            )

        st.divider()

        # ── Jahresverlauf (Haushalt) ──────────────────────────────────────────
        st.subheader("Jahresverlauf")
        if ansicht == "Haushalt gesamt":
            _jd_display = _jd_combined
            _label_netto = "Netto Haushalt"
        elif ansicht == "Person 1":
            _jd_display = _jd_p1
            _label_netto = "Netto Person 1"
        else:
            _jd_display = _jd_p2
            _label_netto = "Netto Person 2"

        if _jd_display:
            _df = pd.DataFrame(_jd_display).set_index("Jahr")
            fig_jv = go.Figure()
            fig_jv.add_trace(go.Bar(
                name="Brutto", x=_df.index, y=_df["Brutto"] / 12,
                marker_color="#90CAF9",
                hovertemplate="%{x}: %{y:,.0f} €/Mon.<extra>Brutto</extra>",
            ))
            fig_jv.add_trace(go.Scatter(
                name=_label_netto, x=_df.index, y=_df["Netto"] / 12,
                mode="lines+markers", line=dict(color="#4CAF50", width=2),
                hovertemplate="%{x}: %{y:,.0f} €/Mon.<extra>Netto</extra>",
            ))
            fig_jv.add_vline(
                x=betrachtungsjahr, line_width=1, line_dash="dash", line_color="#FF9800",
                annotation_text=str(betrachtungsjahr), annotation_position="top right",
            )
            fig_jv.update_layout(
                template="plotly_white", height=340,
                xaxis=dict(title="Jahr", dtick=2),
                yaxis=dict(title="€ / Monat", tickformat=",.0f"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02),
                margin=dict(l=10, r=10, t=40, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_jv, use_container_width=True)

        st.divider()

        # ── Steuervergleich: Zusammen vs. Getrennt ────────────────────────────
        st.subheader(f"Steuervergleich {betrachtungsjahr}: Zusammen- vs. Getrennte Veranlagung")

        _row_zus = _row_for_year(_jd_zus, betrachtungsjahr)
        _row_get = _row_for_year(_jd_get, betrachtungsjahr)

        # Fallback auf Eintrittsmonat wenn kein Jahreseintrag verfügbar
        hh_zusammen = berechne_haushalt(e1, e2, "Zusammen", mieteinnahmen, p1, p2)
        hh_getrennt  = berechne_haushalt(e1, e2, "Getrennt",  mieteinnahmen, p1, p2)
        _st_zus = _row_zus["Steuer"] / 12 if _row_zus else hh_zusammen["steuer_gesamt"]
        _st_get = _row_get["Steuer"] / 12 if _row_get else hh_getrennt["steuer_gesamt"]
        _nt_zus = _row_zus["Netto"]  / 12 if _row_zus else hh_zusammen["netto_gesamt"]
        _nt_get = _row_get["Netto"]  / 12 if _row_get else hh_getrennt["netto_gesamt"]
        _kv_zus = _row_zus["KV_PV"]  / 12 if _row_zus else hh_zusammen["kv_gesamt"]
        _kv_get = _row_get["KV_PV"]  / 12 if _row_get else hh_getrennt["kv_gesamt"]

        # Individuelle P1/P2 Werte (aus Einzelsimulationen)
        _st_p1 = _row_p1["Steuer"] / 12 if _row_p1 else e1.steuer_monatlich
        _nt_p1 = _row_p1["Netto"]  / 12 if _row_p1 else e1.netto_monatlich
        _kv_p1 = _row_p1["KV_PV"]  / 12 if _row_p1 else e1.kv_monatlich
        _st_p2 = _row_p2["Steuer"] / 12 if _row_p2 else e2.steuer_monatlich
        _nt_p2 = _row_p2["Netto"]  / 12 if _row_p2 else e2.netto_monatlich
        _kv_p2 = _row_p2["KV_PV"]  / 12 if _row_p2 else e2.kv_monatlich

        # Zeile 1: Steuer
        sv1, sv2, sv3, sv4 = st.columns(4)
        sv1.metric("Steuer Zusammen (Mon.)", f"{_de(_st_zus)} €")
        sv2.metric("Steuer Getrennt (Mon.)", f"{_de(_st_get)} €")
        sv3.metric("Steuer P1 (Mon.)", f"{_de(_st_p1)} €")
        sv4.metric("Steuer P2 (Mon.)", f"{_de(_st_p2)} €")

        # Zeile 2: Netto
        sv5, sv6, sv7, sv8 = st.columns(4)
        sv5.metric("Netto Zusammen (Mon.)", f"{_de(_nt_zus)} €")
        sv6.metric("Netto Getrennt (Mon.)", f"{_de(_nt_get)} €")
        sv7.metric("Netto P1 (Mon.)", f"{_de(_nt_p1)} €")
        sv8.metric("Netto P2 (Mon.)", f"{_de(_nt_p2)} €")

        ersparnis_monatlich = _nt_zus - _nt_get
        if ersparnis_monatlich > 1:
            st.success(
                f"**Zusammenveranlagung spart {_de(ersparnis_monatlich)} €/Monat "
                f"({_de(ersparnis_monatlich * 12)} €/Jahr)** gegenüber getrennter Veranlagung."
            )
        else:
            st.info("In diesem Fall ergibt sich kein Splitting-Vorteil "
                    "(ähnlich hohe Einkommen beider Partner).")

        # Stacked bar: Netto + Steuer + KV für Zusammen, Getrennt, P1, P2
        _szv_x = ["Zusammen\n(Splitting)", "Getrennt", "Person 1\n(allein)", "Person 2\n(allein)"]
        fig_st = go.Figure()
        fig_st.add_trace(go.Bar(
            name="Netto", x=_szv_x, y=[_nt_zus, _nt_get, _nt_p1, _nt_p2],
            marker_color="#A5D6A7",
            text=[f"{_de(v)} €" for v in [_nt_zus, _nt_get, _nt_p1, _nt_p2]],
            textposition="inside",
        ))
        fig_st.add_trace(go.Bar(
            name="− Steuer", x=_szv_x, y=[_st_zus, _st_get, _st_p1, _st_p2],
            marker_color="#EF9A9A",
            text=[f"{_de(v)} €" for v in [_st_zus, _st_get, _st_p1, _st_p2]],
            textposition="inside",
        ))
        fig_st.add_trace(go.Bar(
            name="− KV/PV", x=_szv_x, y=[_kv_zus, _kv_get, _kv_p1, _kv_p2],
            marker_color="#FFF176",
            text=[f"{_de(v)} €" for v in [_kv_zus, _kv_get, _kv_p1, _kv_p2]],
            textposition="inside",
        ))
        fig_st.update_layout(
            barmode="stack",
            template="plotly_white", height=340,
            yaxis=dict(title=f"€ / Monat {betrachtungsjahr} (Brutto = Gesamthöhe)", tickformat=",.0f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(l=10, r=10, t=40, b=10),
            separators=",.",
        )
        st.caption("Zusammen/Getrennt = Haushalt gesamt (beide Personen); P1/P2 = Einzelwerte je Person.")
        st.plotly_chart(fig_st, use_container_width=True)

        st.divider()

        # ── Szenarien-Vergleich Haushalt ──────────────────────────────────────
        st.subheader(f"Haushalt-Szenarien {betrachtungsjahr} (pessimistisch / neutral / optimistisch)")

        sz1 = simuliere_szenarien(p1)
        sz2 = simuliere_szenarien(p2)
        _sz_params = {
            "Pessimistisch": (0.01, 0.03),
            "Neutral":       (p1.rentenanpassung_pa, p1.rendite_pa),
            "Optimistisch":  (0.03, 0.07),
        }
        # Genaue Jahressimulation je Szenario (korrekte Steuerprogression)
        _hh_sz_jd: dict[str, dict[int, dict]] = {}
        _p1_sz_jd: dict[str, dict[int, dict]] = {}
        _p2_sz_jd: dict[str, dict[int, dict]] = {}
        for _nm, (_rpa, _kpa) in _sz_params.items():
            _p1_n = _dc_replace(p1, rentenanpassung_pa=_rpa, rendite_pa=_kpa)
            _e1_n = berechne_rente(_p1_n)
            _p2_n = _dc_replace(p2, rentenanpassung_pa=_rpa, rendite_pa=_kpa)
            _e2_n = berechne_rente(_p2_n)
            _, _jd_hh = _netto_ueber_horizont(
                _p1_n, _e1_n, [], _horizont_hh, mieteinnahmen, mietsteigerung,
                profil2=_p2_n, ergebnis2=_e2_n, veranlagung=veranlagung,
            )
            _, _jd_p1 = _netto_ueber_horizont(_p1_n, _e1_n, [], _horizont_p1, 0.0, 0.0)
            _, _jd_p2 = _netto_ueber_horizont(_p2_n, _e2_n, [], _horizont_p2, 0.0, 0.0)
            _hh_sz_jd[_nm] = {r["Jahr"]: r for r in _jd_hh}
            _p1_sz_jd[_nm] = {r["Jahr"]: r for r in _jd_p1}
            _p2_sz_jd[_nm] = {r["Jahr"]: r for r in _jd_p2}

        rows = []
        for name in ["Pessimistisch", "Neutral", "Optimistisch"]:
            _row_hh = _hh_sz_jd[name].get(betrachtungsjahr)
            _row_p1 = _p1_sz_jd[name].get(betrachtungsjahr)
            _row_p2 = _p2_sz_jd[name].get(betrachtungsjahr)
            rows.append({
                "Szenario": name,
                "Brutto gesamt (€/Mon.)": _de(_row_hh["Brutto"] / 12 if _row_hh else (sz1[name].brutto_monatlich + sz2[name].brutto_monatlich)),
                "Netto gesamt (€/Mon.)":  _de(_row_hh["Netto"]  / 12 if _row_hh else (sz1[name].netto_monatlich  + sz2[name].netto_monatlich)),
                "Netto Person 1":         _de(_row_p1["Netto"]  / 12 if _row_p1 else sz1[name].netto_monatlich),
                "Netto Person 2":         _de(_row_p2["Netto"]  / 12 if _row_p2 else sz2[name].netto_monatlich),
            })
        st.dataframe(pd.DataFrame(rows).set_index("Szenario"), use_container_width=True)
        st.caption("Vollständige Jahressimulation mit korrekter Steuerprogression (keine Näherung).")

        st.divider()

        # ── Ruhestandsstatus und Übergangszeitraum ────────────────────────────
        st.subheader("Ruhestandsstatus und Übergangszeitraum")
        if p1.bereits_rentner and not p2.bereits_rentner:
            diff = p2.eintritt_jahr - AKTUELLES_JAHR
            diff_txt = f"in {diff} Jahren" if diff > 0 else "in diesem Jahr"
            st.info(
                f"**Person 1** befindet sich bereits im Ruhestand (seit {p1.rentenbeginn_jahr}). "
                f"**Person 2** tritt voraussichtlich **{p2.eintritt_jahr}** in Rente ({diff_txt}). "
                f"Bis dahin trägt Person 1 allein zum Renteneinkommen bei: "
                f"**{_de(e1.netto_monatlich)} €/Monat netto**."
            )
        elif p2.bereits_rentner and not p1.bereits_rentner:
            diff = p1.eintritt_jahr - AKTUELLES_JAHR
            diff_txt = f"in {diff} Jahren" if diff > 0 else "in diesem Jahr"
            st.info(
                f"**Person 2** befindet sich bereits im Ruhestand (seit {p2.rentenbeginn_jahr}). "
                f"**Person 1** tritt voraussichtlich **{p1.eintritt_jahr}** in Rente ({diff_txt}). "
                f"Bis dahin trägt Person 2 allein zum Renteneinkommen bei: "
                f"**{_de(e2.netto_monatlich)} €/Monat netto**."
            )
        elif p1.bereits_rentner and p2.bereits_rentner:
            st.info(
                f"Beide Partner befinden sich bereits im Ruhestand "
                f"(Person 1 seit {p1.rentenbeginn_jahr}, Person 2 seit {p2.rentenbeginn_jahr})."
            )
        else:
            years_diff = abs(p1.eintritt_jahr - p2.eintritt_jahr)
            if years_diff > 0:
                erster = "Person 1" if p1.eintritt_jahr <= p2.eintritt_jahr else "Person 2"
                zweiter = "Person 2" if erster == "Person 1" else "Person 1"
                e_erst = e1 if erster == "Person 1" else e2
                st.info(
                    f"**{erster}** geht {years_diff} Jahr(e) früher in Rente als **{zweiter}**. "
                    f"In dieser Zeit steht nur die Rente von {erster} zur Verfügung: "
                    f"**{_de(e_erst.netto_monatlich)} €/Monat netto**."
                )
            else:
                st.info("Beide Partner gehen voraussichtlich im gleichen Jahr in Rente.")

        st.caption(
            "⚠️ Vereinfachte Berechnung. Splitting-Vorteil basiert auf Renteneinnahmen. "
            "Weitere Einkünfte (Mieten, Kapitalerträge) können das Ergebnis erheblich verändern. "
            "Steuerberatung empfohlen."
        )
