"""Haushalt-Tab – Gemeinsame Einkommensübersicht für Ehepaare."""

import plotly.graph_objects as go
import pandas as pd
import streamlit as st

from engine import (
    AKTUELLES_JAHR, Profil, RentenErgebnis,
    berechne_haushalt, einkommensteuer_splitting,
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
                horizontal=True, key="hh_ansicht",
            )
        with fil2:
            # Simulationshorizont: frühester Renteneintritt bis +30 Jahre
            _start_j = min(
                p1.rentenbeginn_jahr if p1.bereits_rentner else p1.eintritt_jahr,
                p2.rentenbeginn_jahr if p2.bereits_rentner else p2.eintritt_jahr,
            )
            _end_j = _start_j + 30
            _default_j = max(_start_j, AKTUELLES_JAHR)
            betrachtungsjahr = st.slider(
                "Betrachtungsjahr", _start_j, _end_j, _default_j,
                key="hh_jahr",
                help="Zeigt projizierte Einkommenswerte für das gewählte Jahr (mit Rentenanpassung).",
            )

        # Jahresverlauf berechnen (kein Produkde-Einfluss)
        _horizont = _end_j - _start_j + 1
        _, _jd_hh = _netto_ueber_horizont(
            p1, e1, [], _horizont, mieteinnahmen, mietsteigerung,
            profil2=p2, ergebnis2=e2, veranlagung=veranlagung,
        )
        _, _jd_p1 = _netto_ueber_horizont(p1, e1, [], _horizont, 0.0, 0.0)
        _, _jd_p2 = _netto_ueber_horizont(p2, e2, [], _horizont, 0.0, 0.0)

        def _row_for_year(jd: list[dict], jahr: int) -> dict | None:
            for r in jd:
                if r["Jahr"] == jahr:
                    return r
            return None

        _row_hh = _row_for_year(_jd_hh, betrachtungsjahr)
        _row_p1 = _row_for_year(_jd_p1, betrachtungsjahr)
        _row_p2 = _row_for_year(_jd_p2, betrachtungsjahr)

        # ── Kennzahlen für gewähltes Jahr ─────────────────────────────────────
        st.subheader(f"Monatseinkommen {betrachtungsjahr}")
        c1, c2, c3, c4 = st.columns(4)

        if ansicht == "Haushalt gesamt" and _row_hh:
            _b = _row_hh["Brutto"] / 12
            _n = _row_hh["Netto"] / 12
            _s = _row_hh["Steuer"] / 12
            _k = _row_hh["KV_PV"] / 12
            _label = "Haushalt gesamt"
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
            # Fallback auf aktuelle Werte
            _b = hh["brutto_gesamt"]
            _n = hh["netto_gesamt"]
            _s = hh["steuer_gesamt"]
            _k = hh["kv_gesamt"]
            _label = "Haushalt"

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
            # Einzelpersonen-Ansicht
            _e = e1 if ansicht == "Person 1" else e2
            _p = p1 if ansicht == "Person 1" else p2
            st.subheader(f"{ansicht} – Eintrittsmonat")
            cv1, cv2 = st.columns(2)
            with cv1:
                for label, wert in [
                    ("Bruttorente", f"{_de(_e.brutto_monatlich)} €"),
                    ("− Steuer", f"{_de(_e.steuer_monatlich)} €"),
                    ("− KV / PV", f"{_de(_e.kv_monatlich)} €"),
                    ("**= Netto**", f"**{_de(_e.netto_monatlich)} €**"),
                    ("Rentenpunkte", f"{_e.gesamtpunkte:.1f}".replace(".", ",")),
                    ("Renteneintritt",
                     str(_p.rentenbeginn_jahr if _p.bereits_rentner else _p.eintritt_jahr)),
                ]:
                    a, b = st.columns([2, 1])
                    a.markdown(label)
                    b.markdown(wert)
        else:
            st.subheader("Person 1 vs. Person 2 – Eintrittsmonat")
            col1, col2, col3 = st.columns([2, 2, 3])

            with col1:
                st.markdown("**Person 1**")
                for label, wert in [
                    ("Bruttorente", f"{_de(e1.brutto_monatlich)} €"),
                    ("− Steuer", f"{_de(e1.steuer_monatlich)} €"),
                    ("− KV / PV", f"{_de(e1.kv_monatlich)} €"),
                    ("**= Netto**", f"**{_de(e1.netto_monatlich)} €**"),
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
                    ("Bruttorente", f"{_de(e2.brutto_monatlich)} €"),
                    ("− Steuer", f"{_de(e2.steuer_monatlich)} €"),
                    ("− KV / PV", f"{_de(e2.kv_monatlich)} €"),
                    ("**= Netto**", f"**{_de(e2.netto_monatlich)} €**"),
                    ("Rentenpunkte", f"{e2.gesamtpunkte:.1f}".replace(".", ",")),
                    ("Ruhestand seit" if p2.bereits_rentner else "Renteneintritt",
                     str(p2.rentenbeginn_jahr if p2.bereits_rentner else p2.eintritt_jahr)),
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
                        text=[f"{_de(abs(v))} €" for v in werte],
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
            _jd_display = _jd_hh
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
        st.subheader("Steuervergleich: Zusammen- vs. Getrennte Veranlagung")

        hh_zusammen = berechne_haushalt(e1, e2, "Zusammen", mieteinnahmen)
        hh_getrennt = berechne_haushalt(e1, e2, "Getrennt", mieteinnahmen)

        sv1, sv2, sv3, sv4 = st.columns(4)
        sv1.metric("Steuer Zusammen (Mon.)", f"{_de(hh_zusammen['steuer_gesamt'])} €")
        sv2.metric("Steuer Getrennt (Mon.)", f"{_de(hh_getrennt['steuer_gesamt'])} €")
        sv3.metric("Netto Zusammen (Mon.)", f"{_de(hh_zusammen['netto_gesamt'])} €")
        sv4.metric("Netto Getrennt (Mon.)", f"{_de(hh_getrennt['netto_gesamt'])} €")

        ersparnis_monatlich = hh_zusammen["steuerersparnis_splitting"]
        if ersparnis_monatlich > 0:
            st.success(
                f"**Zusammenveranlagung spart {_de(ersparnis_monatlich)} €/Monat "
                f"({_de(ersparnis_monatlich * 12)} €/Jahr)** gegenüber getrennter Veranlagung."
            )
        else:
            st.info("In diesem Fall ergibt sich kein Splitting-Vorteil "
                    "(ähnlich hohe Einkommen beider Partner).")

        fig_st = go.Figure(go.Bar(
            x=["Zusammenveranlagung\n(Splitting)", "Getrennte\nVeranlagung"],
            y=[hh_zusammen["steuer_gesamt"] * 12, hh_getrennt["steuer_gesamt"] * 12],
            marker_color=["#A5D6A7", "#EF9A9A"],
            text=[f"{_de(v)} €/Jahr" for v in [
                hh_zusammen["steuer_gesamt"] * 12,
                hh_getrennt["steuer_gesamt"] * 12,
            ]],
            textposition="outside",
        ))
        fig_st.update_layout(
            template="plotly_white", height=300,
            yaxis=dict(title="Jahressteuer (€)", tickformat=",.0f"),
            margin=dict(l=10, r=10, t=10, b=10),
            separators=",.",
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
                "Brutto gesamt (€/Mon.)": _de(hh_sz["brutto_gesamt"]),
                "Netto gesamt (€/Mon.)": _de(hh_sz["netto_gesamt"]),
                "Netto Person 1": _de(sz1[name].netto_monatlich),
                "Netto Person 2": _de(sz2[name].netto_monatlich),
            })
        st.dataframe(pd.DataFrame(rows).set_index("Szenario"), use_container_width=True)

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
