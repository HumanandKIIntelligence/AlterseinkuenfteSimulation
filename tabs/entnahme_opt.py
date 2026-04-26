"""Entnahme-Optimierung – steueroptimierte Auszahlungsstrategie für bekannte Verträge.

Zeigt den Steuer-Steckbrief je Produkt und ermittelt die optimale Kombination
aus Startjahr und Auszahlungsart (Einmal/Rente) unter Berücksichtigung von
Einkommensteuer, Abgeltungsteuer und KVdR-Beiträgen.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    Profil, RentenErgebnis, VorsorgeProdukt,
    optimiere_auszahlungen, besteuerungsanteil, ertragsanteil,
)
from tabs import auszahlung
from tabs.vorsorge import _run_optimierung


def _aus_dict(d: dict) -> VorsorgeProdukt:
    """Importiert _aus_dict aus vorsorge ohne zirkulären Import."""
    from tabs.vorsorge import _aus_dict as _vp_aus_dict
    return _vp_aus_dict(d)


def _steuer_steckbrief(prod_dicts: list[dict], profil: Profil) -> pd.DataFrame:
    rows = []
    for p in prod_dicts:
        typ  = p.get("typ", "bAV")
        vbeg = p.get("vertragsbeginn", 2010)
        tf   = p.get("teilfreistellung", 0.30)

        if typ == "bAV":
            einmal_regel = "100 % progressiv (§ 19 EStG)"
            mono_regel   = "100 % progressiv (§ 19 EStG)"
            kvdr         = "Ja – FB 187 €/Mon. (§ 226 SGB V)"
        elif typ == "Riester":
            einmal_regel = "100 % progressiv (§ 22 Nr. 5 EStG)"
            mono_regel   = "100 % progressiv (§ 22 Nr. 5 EStG)"
            kvdr         = "Nein"
        elif typ == "Rürup":
            einmal_regel = "Nicht möglich (Basisrente)"
            ba = besteuerungsanteil(profil.eintritt_jahr)
            mono_regel   = f"Besteuerungsanteil {ba:.0%} (§ 22 Nr. 1 EStG)"
            kvdr         = "Nein"
        elif typ == "LV":
            if vbeg < 2005:
                einmal_regel = "Steuerfrei (Altvertrag vor 2005)"
            else:
                einmal_regel = "Halbeinkünfte (≥ 12 J. + ≥ 60/62 J.) oder 25 % Abgeltungsteuer"
            mono_regel = "–"
            kvdr       = "–"
        elif typ == "PrivateRente":
            if vbeg < 2005:
                einmal_regel = "Steuerfrei (Altvertrag vor 2005)"
            else:
                einmal_regel = "Halbeinkünfte (≥ 12 J. + ≥ 60/62 J.) oder 25 % Abgeltungsteuer"
            ea = ertragsanteil(profil.renteneintritt_alter)
            mono_regel = f"Ertragsanteil {ea:.0%} (§ 22 Nr. 1 S. 3a bb EStG)"
            kvdr       = "Nein"
        elif typ == "ETF":
            einmal_regel = f"25 % Abgelt. auf {(1 - tf):.0%} des Gewinns (TF {tf:.0%}, § 20 InvStG)"
            mono_regel   = "–"
            kvdr         = "Nein"
        else:
            einmal_regel = "–"
            mono_regel   = "–"
            kvdr         = "–"

        rows.append({
            "Produkt":           p["name"],
            "Typ":               p["typ_label"],
            "Person":            p.get("person", "Person 1"),
            "Einmalauszahlung":  einmal_regel,
            "Monatsrente":       mono_regel,
            "KVdR-pflichtig":    kvdr,
        })
    return pd.DataFrame(rows)


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis, profil2=None,
           mieteinnahmen: float = 0.0, mietsteigerung: float = 0.0,
           ergebnis2=None, veranlagung: str = "Getrennt") -> None:
    with T["Entnahme"]:
        st.header("💡 Entnahme-Optimierung")
        st.caption(
            "Steueroptimale Auszahlungsstrategie für alle erfassten Verträge unter "
            "Berücksichtigung von Einkommensteuer (progressiv + Abgeltungsteuer), "
            "KVdR-Beiträgen und Sparerpauschbetrag. "
            "Produkte werden im Tab **Vorsorge-Bausteine** erfasst."
        )

        # ── Personenfilter ────────────────────────────────────────────────────
        _rc = st.session_state.get("_rc", 0)
        hat_partner = profil2 is not None and ergebnis2 is not None
        eo_person = "Zusammen"
        if hat_partner:
            eo_person = st.radio(
                "Optimierung für", ["Person 1", "Person 2", "Zusammen"],
                horizontal=True, key=f"rc{_rc}_eo_person", index=2,
                help="Person 1/2: nur deren Produkte + einzelne Steuerberechnung. "
                     "Zusammen: alle Produkte, gemeinsame Steuer (Splitting falls aktiv).",
            )

        # Richtiges Profil + Ergebnis je Auswahl
        if eo_person == "Person 2" and hat_partner:
            _profil_eo  = profil2
            _ergebnis_eo = ergebnis2
            _profil2_eo  = None
            _ergebnis2_eo = None
            _ver_eo = "Getrennt"
        elif eo_person == "Zusammen" and hat_partner:
            _profil_eo   = profil
            _ergebnis_eo = ergebnis
            _profil2_eo  = profil2
            _ergebnis2_eo = ergebnis2
            _ver_eo = veranlagung
        else:
            _profil_eo   = profil
            _ergebnis_eo = ergebnis
            _profil2_eo  = None
            _ergebnis2_eo = None
            _ver_eo = "Getrennt"

        produkte_dicts = [
            p for p in st.session_state.get("vp_produkte", [])
        ]
        from tabs.vorsorge import _migriere
        produkte_dicts = [_migriere(p) for p in produkte_dicts]

        # Produkte nach Personenfilter einschränken
        if eo_person == "Person 1":
            produkte_dicts = [p for p in produkte_dicts
                              if p.get("person", "Person 1") == "Person 1"]
        elif eo_person == "Person 2":
            produkte_dicts = [p for p in produkte_dicts
                              if p.get("person") == "Person 2"]

        if not produkte_dicts:
            st.info("Noch keine Verträge erfasst. Bitte zuerst im Tab **Vorsorge-Bausteine** Produkte anlegen.")
            return

        # ── Steuer-Steckbrief ─────────────────────────────────────────────────
        st.subheader("📋 Steuer-Steckbrief")
        st.caption("Steuerliche und KVdR-Behandlung je Produkt auf einen Blick.")
        df_stb = _steuer_steckbrief(produkte_dicts, _profil_eo)
        st.dataframe(df_stb.set_index("Produkt"), use_container_width=True)

        st.divider()

        # ── Optimierungsparameter ─────────────────────────────────────────────
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            horizon = st.slider("Planungshorizont ab Renteneintritt (Jahre)",
                                10, 40, 25, key=f"rc{_rc}_eo_horizon")
            from engine import AKTUELLES_JAHR as _AJ_EO
            _pre_eo = max(0, _profil_eo.eintritt_jahr - _AJ_EO) if not _profil_eo.bereits_rentner else 0
            if _pre_eo > 0:
                st.caption(f"Gesamt: {horizon + _pre_eo} Jahre ({_pre_eo} Arbeits- + {horizon} Rentenjahre)")
        with oc2:
            if mieteinnahmen > 0:
                st.metric("Mieteinnahmen (Basis)",
                          f"{_de(mieteinnahmen)} €/Mon.",
                          help=f"Steigen um {mietsteigerung:.1%}".replace(".", ",") +
                               " p.a. und erhöhen die Steuerprogression.")
        with oc3:
            if not _profil_eo.bereits_rentner:
                gehalt = float(st.session_state.get("opt_gehalt_mono", 0.0))
                if eo_person == "Person 2":
                    gehalt = 0.0
                st.metric("Bruttogehalt (aktiv)",
                          f"{_de(gehalt)} €/Mon." if gehalt > 0 else "–",
                          help="Im Tab ⚙️ Profil einstellbar. "
                               "Wird für Steuerprogression in Arbeitsjahren verwendet.")
            else:
                gehalt = 0.0

        # ── Optimierung ausführen ─────────────────────────────────────────────
        st.subheader("🔍 Optimale Auszahlungsstrategie")
        produkte_obj = [_aus_dict(p) for p in produkte_dicts]
        with st.spinner("Optimierung läuft …"):
            opt = _run_optimierung("eo", _profil_eo, _ergebnis_eo, produkte_obj, produkte_dicts,
                                   horizon, mieteinnahmen, mietsteigerung,
                                   profil2=_profil2_eo, ergebnis2=_ergebnis2_eo,
                                   veranlagung=_ver_eo, gehalt=gehalt)

        if not opt:
            st.info("Keine Produkte für Optimierung vorhanden.")
            return

        # Jahresdaten für Sidebar-Vertragsanzeige speichern
        st.session_state["_sb_eo_jd"] = opt["jahresdaten"]

        # Kennzahlen
        _df_kc = pd.DataFrame(opt["jahresdaten"])
        _netto_arbeit = _df_kc.loc[_df_kc.get("Src_Gehalt", pd.Series(0, index=_df_kc.index)) > 0, "Netto"].sum() if "Src_Gehalt" in _df_kc.columns else 0
        _netto_rente  = _df_kc.loc[_df_kc.get("Src_Gehalt", pd.Series(0, index=_df_kc.index)) == 0, "Netto"].sum() if "Src_Gehalt" in _df_kc.columns else opt["bestes_netto"]

        if _netto_arbeit > 0:
            kc1, kc2, kc3, kc4 = st.columns(4)
            kc1.metric("Netto Arbeitsphase", f"{_de(_netto_arbeit)} €",
                       help="Summe Netto-Jahreseinkommen in aktiven Berufsjahren.")
            kc2.metric("Netto Rentenphase", f"{_de(_netto_rente)} €",
                       help=f"Summe Netto-Jahreseinkommen in {horizon} Rentenjahren.")
            delta_mono = opt["bestes_netto"] - opt["netto_alle_monatlich"]
            kc3.metric("Vorteil vs. alles monatlich",
                       f"{'+' if delta_mono >= 0 else ''}{_de(delta_mono)} €", delta_color="normal")
            delta_einmal = opt["bestes_netto"] - opt["netto_alle_einmal"]
            kc4.metric("Vorteil vs. alles Einmal",
                       f"{'+' if delta_einmal >= 0 else ''}{_de(delta_einmal)} €", delta_color="normal")
        else:
            kc1, kc2, kc3, kc4 = st.columns(4)
            kc1.metric("Netto optimal (gesamt)", f"{_de(opt['bestes_netto'])} €",
                       help=f"Summe aller Netto-Jahreseinkommen über {horizon} Jahre.")
            delta_mono = opt["bestes_netto"] - opt["netto_alle_monatlich"]
            kc2.metric("Vorteil vs. alles monatlich",
                       f"{'+' if delta_mono >= 0 else ''}{_de(delta_mono)} €", delta_color="normal")
            delta_einmal = opt["bestes_netto"] - opt["netto_alle_einmal"]
            kc3.metric("Vorteil vs. alles Einmal",
                       f"{'+' if delta_einmal >= 0 else ''}{_de(delta_einmal)} €", delta_color="normal")
            kc4.metric("Kombinationen geprüft", f"{opt['anzahl_kombinationen']:,}")
        st.caption(f"Kombinationen geprüft: {opt['anzahl_kombinationen']:,}")

        st.success("**Optimale Strategie:**")
        for prod, startjahr, anteil in opt["beste_entscheidungen"]:
            einmal_wert = prod.max_einmalzahlung * (1 + prod.aufschub_rendite) ** max(
                0, startjahr - prod.fruehestes_startjahr)
            mono_wert = prod.max_monatsrente * (1 + prod.aufschub_rendite) ** max(
                0, startjahr - prod.fruehestes_startjahr)
            if anteil == 1.0:
                modus = f"Einmalauszahlung **{_de(einmal_wert)} €**"
            elif anteil == 0.0:
                modus = f"Monatliche Rente **{_de(mono_wert)} €/Mon.**"
            else:
                modus = (f"Kombiniert: **{_de(einmal_wert * anteil)} €** Einmal + "
                         f"**{_de(mono_wert * (1 - anteil))} €/Mon.**")
            aufschub = startjahr - prod.fruehestes_startjahr
            note = f" (+{aufschub} J. Aufschub)" if aufschub > 0 else ""
            st.markdown(f"- **{prod.name}** ({prod.typ}): {modus} ab **{startjahr}**{note}")

        st.divider()

        # ── Strategievergleich ────────────────────────────────────────────────
        st.subheader("Strategievergleich")
        fig_vgl = go.Figure(go.Bar(
            x=["Optimal", "Alles Monatlich\n(frühest möglich)", "Alles Einmal\n(frühest möglich)"],
            y=[opt["bestes_netto"], opt["netto_alle_monatlich"], opt["netto_alle_einmal"]],
            marker_color=["#4CAF50", "#2196F3", "#FF9800"],
            text=[f"{_de(v)} €" for v in [
                opt["bestes_netto"], opt["netto_alle_monatlich"], opt["netto_alle_einmal"]]],
            textposition="outside",
        ))
        fig_vgl.update_layout(
            template="plotly_white", height=340,
            yaxis=dict(title=f"Gesamt-Netto über {horizon} Jahre (€)", tickformat=",.0f"),
            margin=dict(l=10, r=10, t=20, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_vgl, use_container_width=True)

        st.divider()

        # ── Jahresverlauf nach Einkommensquelle ───────────────────────────────
        st.subheader("Jahresverlauf nach Einkommensquelle")
        df_jd = pd.DataFrame(opt["jahresdaten"]).set_index("Jahr")

        # Vertragsnamen pro Jahr für Einmal- und Versorgungsbalken
        _jahre = list(df_jd.index)
        _VERSORGUNG_TYPEN = {"bAV", "Riester", "Rürup", "PrivateRente"}
        _einmal_info  = {j: [] for j in _jahre}
        _versorg_info = {j: [] for j in _jahre}
        for _prod, _startjahr, _anteil in opt["beste_entscheidungen"]:
            _aufschub = max(0, _startjahr - _prod.fruehestes_startjahr)
            _fak = (1 + _prod.aufschub_rendite) ** _aufschub
            # Einmalauszahlung: nur im Startjahr
            if _anteil > 0 and _startjahr in _einmal_info:
                _betrag = _prod.max_einmalzahlung * _fak * _anteil
                _einmal_info[_startjahr].append(f"{_prod.name}: {_de(_betrag)} €")
            # Laufende Versorgung: ab Startjahr für die Laufzeit
            if _anteil < 1.0 and _prod.typ in _VERSORGUNG_TYPEN:
                _mono = _prod.max_monatsrente * _fak * (1 - _anteil)
                _lz = _prod.laufzeit_jahre  # 0 = lebenslang
                for _j in _jahre:
                    if _j < _startjahr:
                        continue
                    if _lz > 0 and _j >= _startjahr + _lz:
                        break
                    _versorg_info[_j].append(f"{_prod.name}: {_de(_mono)} €/Mon.")

        def _hover_lines(info_dict: dict, jahre: list) -> list[str]:
            return [
                "<br>".join(info_dict[j]) if info_dict[j] else ""
                for j in jahre
            ]

        _cd_einmal  = _hover_lines(_einmal_info,  _jahre)
        _cd_versorg = _hover_lines(_versorg_info, _jahre)

        fig_src = go.Figure()
        src_cols = [
            ("Src_Gehalt",     "Bruttogehalt (aktiv)",    "#78909C", None),
            ("Src_GesRente",   "Gesetzl. Rente P1",       "#4CAF50", None),
            ("Src_P2_Rente",   "Gesetzl. Rente P2",       "#81C784", None),
            ("Src_Versorgung", "Betriebliche Versorgung", "#2196F3", _cd_versorg),
            ("Src_Einmal",     "Einmalauszahlungen",      "#FF9800", _cd_einmal),
            ("Src_Miete",      "Mieteinnahmen",           "#9C27B0", None),
        ]
        for col, label, color, customdata in src_cols:
            if col in df_jd.columns and df_jd[col].sum() > 0:
                if customdata is not None:
                    _non_empty = [s for s in customdata if s]
                    _has_detail = len(_non_empty) > 0
                else:
                    _has_detail = False
                if _has_detail:
                    fig_src.add_trace(go.Bar(
                        name=label, x=df_jd.index, y=df_jd[col],
                        marker_color=color,
                        customdata=customdata,
                        hovertemplate=(
                            "%{x}: %{y:,.0f} €"
                            "<br><i>%{customdata}</i>"
                            "<extra>" + label + "</extra>"
                        ),
                    ))
                else:
                    fig_src.add_trace(go.Bar(
                        name=label, x=df_jd.index, y=df_jd[col],
                        marker_color=color,
                        hovertemplate="%{x}: %{y:,.0f} €<extra>" + label + "</extra>",
                    ))
        fig_src.add_trace(go.Scatter(
            name="Netto", x=df_jd.index, y=df_jd["Netto"],
            mode="lines+markers",
            line=dict(color="black", width=2),
            hovertemplate="%{x}: %{y:,.0f} € Netto<extra></extra>",
        ))
        if not _profil_eo.bereits_rentner:
            _vline_label_src = "P1 Renteneintritt" if _profil2_eo else "Renteneintritt"
            fig_src.add_vline(
                x=_profil_eo.eintritt_jahr, line_width=2, line_dash="dash", line_color="#5C6BC0",
                annotation_text=_vline_label_src, annotation_position="top right",
            )
        if _profil2_eo and not _profil2_eo.bereits_rentner:
            fig_src.add_vline(
                x=_profil2_eo.eintritt_jahr, line_width=2, line_dash="dash", line_color="#E91E63",
                annotation_text="P2 Renteneintritt", annotation_position="top left",
            )
        fig_src.update_layout(
            barmode="stack", template="plotly_white", height=400,
            xaxis=dict(title="Jahr", dtick=2),
            yaxis=dict(title="€ / Jahr (brutto)", tickformat=",.0f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=50, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_src, use_container_width=True)

        # ── Jahresdetails ─────────────────────────────────────────────────────
        st.subheader("Jahresdetails")
        _min_j_jd = int(df_jd.index.min())
        _max_j_jd = int(df_jd.index.max())
        _def_j_jd = min(_max_j_jd, max(_min_j_jd, _profil_eo.eintritt_jahr))
        _sel_j = st.slider(
            "Betrachtungsjahr", _min_j_jd, _max_j_jd, _def_j_jd, key=f"rc{_rc}_eo_sel_jahr",
            help="Zeigt Monatswerte aus dem optimalen Auszahlungsplan für das gewählte Jahr.",
        )
        if _sel_j in df_jd.index:
            _jrow = df_jd.loc[_sel_j]
            jm1, jm2, jm3, jm4 = st.columns(4)
            jm1.metric(f"Brutto {_sel_j}", f"{_de(_jrow['Brutto'] / 12)} €/Mon.")
            jm2.metric(f"Netto {_sel_j}", f"{_de(_jrow['Netto'] / 12)} €/Mon.")
            jm3.metric(f"Steuer {_sel_j}", f"{_de(_jrow['Steuer'] / 12)} €/Mon.")
            jm4.metric(f"KV/PV {_sel_j}", f"{_de(_jrow['KV_PV'] / 12)} €/Mon.")
            if "KV_P2" in df_jd.columns and _jrow["KV_P2"] > 0:
                st.caption(
                    f"KV-Aufteilung: P1 {_de(_jrow['KV_P1'] / 12)} €/Mon. "
                    f"| P2 {_de(_jrow['KV_P2'] / 12)} €/Mon."
                )

        st.divider()

        # ── Steuer- und KV-Verlauf ────────────────────────────────────────────
        st.subheader("Steuer- und KV-Verlauf")
        fig_tax = go.Figure()
        fig_tax.add_trace(go.Bar(
            name="Progressivsteuer", x=df_jd.index, y=df_jd["Steuer_Progressiv"],
            marker_color="#EF9A9A",
            hovertemplate="%{x}: %{y:,.0f} €<extra>Progressivsteuer</extra>",
        ))
        if "Steuer_Abgeltung" in df_jd.columns:
            fig_tax.add_trace(go.Bar(
                name="Abgeltungsteuer", x=df_jd.index, y=df_jd["Steuer_Abgeltung"],
                marker_color="#FFCDD2",
                hovertemplate="%{x}: %{y:,.0f} €<extra>Abgeltungsteuer</extra>",
            ))
        _hat_p2_kv = "KV_P2" in df_jd.columns and df_jd["KV_P2"].sum() > 0
        if _hat_p2_kv:
            _kv_custom = [
                f"P1: {_de(r['KV_P1'])} €<br>P2: {_de(r['KV_P2'])} €"
                for _, r in df_jd.iterrows()
            ]
            fig_tax.add_trace(go.Bar(
                name="KV/PV", x=df_jd.index, y=df_jd["KV_PV"],
                marker_color="#FFF176",
                customdata=_kv_custom,
                hovertemplate="%{x}: %{y:,.0f} €<br><i>%{customdata}</i><extra>KV/PV</extra>",
            ))
        else:
            fig_tax.add_trace(go.Bar(
                name="KV/PV", x=df_jd.index, y=df_jd["KV_PV"],
                marker_color="#FFF176",
                hovertemplate="%{x}: %{y:,.0f} €<extra>KV/PV</extra>",
            ))
        fig_tax.add_trace(go.Scatter(
            name="zvE", x=df_jd.index, y=df_jd["zvE"],
            mode="lines", line=dict(color="#5C6BC0", width=2, dash="dot"),
            yaxis="y2",
            hovertemplate="%{x}: %{y:,.0f} € zvE<extra></extra>",
        ))
        if not _profil_eo.bereits_rentner:
            _vline_label_tax = "P1 Renteneintritt" if _profil2_eo else "Renteneintritt"
            fig_tax.add_vline(
                x=_profil_eo.eintritt_jahr, line_width=2, line_dash="dash", line_color="#5C6BC0",
                annotation_text=_vline_label_tax, annotation_position="top right",
            )
        if _profil2_eo and not _profil2_eo.bereits_rentner:
            fig_tax.add_vline(
                x=_profil2_eo.eintritt_jahr, line_width=2, line_dash="dash", line_color="#E91E63",
                annotation_text="P2 Renteneintritt", annotation_position="top left",
            )
        fig_tax.update_layout(
            barmode="stack", template="plotly_white", height=380,
            xaxis=dict(title="Jahr", dtick=2),
            yaxis=dict(title="€ / Jahr", tickformat=",.0f"),
            yaxis2=dict(title="zvE (€)", tickformat=",.0f", overlaying="y",
                        side="right", showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=50, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_tax, use_container_width=True)

        # ── Gesamtbelastung Steuer + KV über Planungshorizont ─────────────────
        st.subheader(f"Gesamtbelastung über {horizon} Rentenjahre")
        _steuer_ges = df_jd["Steuer"].sum()
        _kv_ges     = df_jd["KV_PV"].sum()

        _ist_splitting = _ver_eo == "Zusammen"
        _steuer_p1_ges = _steuer_ges / 2 if (_ist_splitting and _profil2_eo) else _steuer_ges
        _steuer_p2_ges = _steuer_ges / 2 if (_ist_splitting and _profil2_eo) else 0.0

        if "KV_P1" in df_jd.columns and df_jd["KV_P1"].sum() > 0:
            _kv_p1_ges = df_jd["KV_P1"].sum()
            _kv_p2_ges = df_jd["KV_P2"].sum() if "KV_P2" in df_jd.columns else 0.0
        elif _profil2_eo:
            _kv_p1_ges = _kv_ges / 2
            _kv_p2_ges = _kv_ges / 2
        else:
            _kv_p1_ges = _kv_ges
            _kv_p2_ges = 0.0

        gb1, gb2, gb3 = st.columns(3)
        gb1.metric("Steuer P1 gesamt", f"{_de(_steuer_p1_ges)} €",
                   help="Progressiv- + Abgeltungsteuer Person 1 über den Planungshorizont.")
        gb2.metric("Steuer P2 gesamt", f"{_de(_steuer_p2_ges)} €",
                   help="Progressiv- + Abgeltungsteuer Person 2 über den Planungshorizont.")
        gb3.metric("Steuer gesamt", f"{_de(_steuer_ges)} €",
                   help="Progressiv- + Abgeltungsteuer gesamt über den Planungshorizont.")
        gb4, gb5, gb6 = st.columns(3)
        gb4.metric("KV/PV P1 gesamt", f"{_de(_kv_p1_ges)} €",
                   help="Kranken- + Pflegeversicherung Person 1 über den Planungshorizont.")
        gb5.metric("KV/PV P2 gesamt", f"{_de(_kv_p2_ges)} €",
                   help="Kranken- + Pflegeversicherung Person 2 über den Planungshorizont.")
        gb6.metric("KV/PV gesamt", f"{_de(_kv_ges)} €",
                   help="Kranken- + Pflegeversicherung gesamt über den Planungshorizont.")
        if _ist_splitting and _profil2_eo:
            st.caption("Steueraufteilung P1/P2: halbiert (Splitting; Steuerprogression nicht neu berechnet).")

        st.divider()

        # ── Top-10 Kombinationen ──────────────────────────────────────────────
        st.subheader("Top-10 Kombinationen")
        df_top = pd.DataFrame(opt["top10"]).set_index("Kombination")
        st.dataframe(df_top, use_container_width=True)

        with st.expander("Rohdaten – Jahresverlauf"):
            st.dataframe(df_jd, use_container_width=True)

        st.caption(
            "⚠️ Simulation auf Basis der Rechtslage 2024. Sparerpauschbetrag 1.000 €/Person "
            "berücksichtigt. Soli, Kirchensteuer und individuelle Freibeträge werden nicht "
            "modelliert. Steuerberatung empfohlen."
        )

        st.divider()

        # ── O3c: Kapitalverzehr-Kalkulator ────────────────────────────────────
        with st.expander("💰 Kapitalverzehr-Kalkulator", expanded=False):
            auszahlung.render_section(_profil_eo, _ergebnis_eo)
