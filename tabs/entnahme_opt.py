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


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis, profil2=None,
           mieteinnahmen: float = 0.0, mietsteigerung: float = 0.0) -> None:
    with T["Entnahme"]:
        st.header("💡 Entnahme-Optimierung")
        st.caption(
            "Steueroptimale Auszahlungsstrategie für alle erfassten Verträge unter "
            "Berücksichtigung von Einkommensteuer (progressiv + Abgeltungsteuer), "
            "KVdR-Beiträgen und Sparerpauschbetrag. "
            "Produkte werden im Tab **Vorsorge-Bausteine** erfasst."
        )

        produkte_dicts = [
            p for p in st.session_state.get("vp_produkte", [])
        ]
        from tabs.vorsorge import _migriere
        produkte_dicts = [_migriere(p) for p in produkte_dicts]

        if not produkte_dicts:
            st.info("Noch keine Verträge erfasst. Bitte zuerst im Tab **Vorsorge-Bausteine** Produkte anlegen.")
            return

        # ── Steuer-Steckbrief ─────────────────────────────────────────────────
        st.subheader("📋 Steuer-Steckbrief")
        st.caption("Steuerliche und KVdR-Behandlung je Produkt auf einen Blick.")
        df_stb = _steuer_steckbrief(produkte_dicts, profil)
        st.dataframe(df_stb.set_index("Produkt"), use_container_width=True)

        st.divider()

        # ── Optimierungsparameter ─────────────────────────────────────────────
        oc1, oc2 = st.columns(2)
        with oc1:
            horizon = st.slider("Planungshorizont ab Renteneintritt (Jahre)",
                                10, 40, 25, key="eo_horizon")
        with oc2:
            if mieteinnahmen > 0:
                st.metric("Mieteinnahmen (Basis)",
                          f"{mieteinnahmen:,.0f} €/Mon.",
                          help=f"Steigen um {mietsteigerung:.1%} p.a. und erhöhen die Steuerprogression.")

        # ── Optimierung ausführen ─────────────────────────────────────────────
        st.subheader("🔍 Optimale Auszahlungsstrategie")
        produkte_obj = [_aus_dict(p) for p in produkte_dicts]
        with st.spinner("Optimierung läuft …"):
            opt = optimiere_auszahlungen(profil, ergebnis, produkte_obj, horizon,
                                         mieteinnahmen, mietsteigerung)

        if not opt:
            st.info("Keine Produkte für Optimierung vorhanden.")
            return

        # Kennzahlen
        kc1, kc2, kc3, kc4 = st.columns(4)
        kc1.metric("Netto optimal (gesamt)", f"{opt['bestes_netto']:,.0f} €",
                   help=f"Summe aller Netto-Jahreseinkommen über {horizon} Jahre.")
        delta_mono = opt["bestes_netto"] - opt["netto_alle_monatlich"]
        kc2.metric("Vorteil vs. alles monatlich", f"{delta_mono:+,.0f} €", delta_color="normal")
        delta_einmal = opt["bestes_netto"] - opt["netto_alle_einmal"]
        kc3.metric("Vorteil vs. alles Einmal", f"{delta_einmal:+,.0f} €", delta_color="normal")
        kc4.metric("Kombinationen geprüft", f"{opt['anzahl_kombinationen']:,}")

        st.success("**Optimale Strategie:**")
        for prod, startjahr, anteil in opt["beste_entscheidungen"]:
            einmal_wert = prod.max_einmalzahlung * (1 + prod.aufschub_rendite) ** max(
                0, startjahr - prod.fruehestes_startjahr)
            mono_wert = prod.max_monatsrente * (1 + prod.aufschub_rendite) ** max(
                0, startjahr - prod.fruehestes_startjahr)
            if anteil == 1.0:
                modus = f"Einmalauszahlung **{einmal_wert:,.0f} €**"
            elif anteil == 0.0:
                modus = f"Monatliche Rente **{mono_wert:,.0f} €/Mon.**"
            else:
                modus = (f"Kombiniert: **{einmal_wert * anteil:,.0f} €** Einmal + "
                         f"**{mono_wert * (1 - anteil):,.0f} €/Mon.**")
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
            text=[f"{v:,.0f} €" for v in [
                opt["bestes_netto"], opt["netto_alle_monatlich"], opt["netto_alle_einmal"]]],
            textposition="outside",
        ))
        fig_vgl.update_layout(
            template="plotly_white", height=340,
            yaxis=dict(title=f"Gesamt-Netto über {horizon} Jahre (€)", tickformat=",.0f"),
            margin=dict(l=10, r=10, t=20, b=10),
        )
        st.plotly_chart(fig_vgl, use_container_width=True)

        st.divider()

        # ── Jahresverlauf nach Einkommensquelle ───────────────────────────────
        st.subheader("Jahresverlauf nach Einkommensquelle")
        df_jd = pd.DataFrame(opt["jahresdaten"]).set_index("Jahr")

        fig_src = go.Figure()
        src_cols = [
            ("Src_GesRente",   "Gesetzl. Rente",         "#4CAF50"),
            ("Src_Versorgung", "Betriebliche Versorgung", "#2196F3"),
            ("Src_Einmal",     "Einmalauszahlungen",      "#FF9800"),
            ("Src_Miete",      "Mieteinnahmen",           "#9C27B0"),
        ]
        for col, label, color in src_cols:
            if col in df_jd.columns and df_jd[col].sum() > 0:
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
        fig_src.update_layout(
            barmode="stack", template="plotly_white", height=400,
            xaxis=dict(title="Jahr", dtick=2),
            yaxis=dict(title="€ / Jahr (brutto)", tickformat=",.0f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(fig_src, use_container_width=True)

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
        fig_tax.update_layout(
            barmode="stack", template="plotly_white", height=380,
            xaxis=dict(title="Jahr", dtick=2),
            yaxis=dict(title="€ / Jahr", tickformat=",.0f"),
            yaxis2=dict(title="zvE (€)", tickformat=",.0f", overlaying="y",
                        side="right", showgrid=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=50, b=10),
        )
        st.plotly_chart(fig_tax, use_container_width=True)

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
            auszahlung.render_section(profil, ergebnis)
