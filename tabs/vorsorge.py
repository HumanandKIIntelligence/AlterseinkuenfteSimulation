"""Vorsorge-Bausteine-Tab – bAV, Private RV, Riester, Lebensversicherung.

Pro Vertrag: max. Einmalauszahlung, max. Monatsrente, frühestes/spätestes
Startdatum und Aufschubverzinsung. Steueroptimierung über alle Kombinationen.
"""

from __future__ import annotations

import uuid
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    Profil, RentenErgebnis, VorsorgeProdukt,
    vergleiche_produkt, optimiere_auszahlungen, _annuitaet,
)

_TYPEN = ["bAV", "Private Rentenversicherung", "Riester-Rente", "Lebensversicherung"]
_TYP_KEYS = {
    "bAV": "bAV",
    "Private Rentenversicherung": "PrivateRente",
    "Riester-Rente": "Riester",
    "Lebensversicherung": "LV",
}
_LABELS = {"einmal": "Einmalauszahlung", "monatlich": "Monatliche Rente",
           "kombiniert": "Kombiniert (Kapital + Rente)"}
_FARBEN = {"Einmal": "#2196F3", "Monatlich": "#4CAF50", "50/50": "#FF9800"}


def _init_state() -> None:
    if "vp_produkte" not in st.session_state:
        st.session_state.vp_produkte = []


def _migriere(p: dict) -> dict:
    """Altes Format (kapital/monatsrente) auf neues Format bringen."""
    if "max_einmalzahlung" not in p:
        p["max_einmalzahlung"] = p.pop("kapital", 0.0)
        p["max_monatsrente"] = p.pop("monatsrente", 0.0)
        from engine import AKTUELLES_JAHR
        p["fruehestes_startjahr"] = AKTUELLES_JAHR + 5
        p["spaetestes_startjahr"] = AKTUELLES_JAHR + 8
        p["aufschub_rendite"] = 0.02
    if "person" not in p:
        p["person"] = "Person 1"
    return p


def _aus_dict(d: dict) -> VorsorgeProdukt:
    d = _migriere(d)
    return VorsorgeProdukt(
        id=d["id"], typ=d["typ"], name=d["name"], person=d["person"],
        max_einmalzahlung=d["max_einmalzahlung"],
        max_monatsrente=d["max_monatsrente"],
        laufzeit_jahre=d["laufzeit_jahre"],
        fruehestes_startjahr=d["fruehestes_startjahr"],
        spaetestes_startjahr=d["spaetestes_startjahr"],
        aufschub_rendite=d["aufschub_rendite"],
    )


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis, profil2=None) -> None:
    _init_state()
    st.session_state.vp_produkte = [_migriere(p) for p in st.session_state.vp_produkte]

    with T["Vorsorge"]:
        st.header("🏦 Vorsorge-Bausteine")

        # ── Produkt hinzufügen ────────────────────────────────────────────────
        with st.expander("➕ Neues Produkt hinzufügen",
                         expanded=not st.session_state.vp_produkte):
            from engine import AKTUELLES_JAHR
            c1, c2, c3 = st.columns(3)

            with c1:
                typ_label = st.selectbox("Produkttyp", _TYPEN, key="vp_add_typ")
                typ_key = _TYP_KEYS[typ_label]
                name = st.text_input("Bezeichnung", placeholder="z.B. bAV Firma Müller",
                                     key="vp_add_name")
                person_opts = ["Person 1"] + (["Person 2"] if profil2 else [])
                person = st.selectbox("Zugeordnet zu", person_opts, key="vp_add_person")

            with c2:
                max_einmal = st.number_input(
                    "Max. Einmalauszahlung (€)",
                    min_value=0.0, max_value=2_000_000.0, value=50_000.0, step=1_000.0,
                    key="vp_add_einmal",
                    help="Maximaler Betrag bei vollständiger Einmalauszahlung "
                         "ab dem frühesten Startdatum.",
                )
                if typ_key != "LV":
                    max_mono = st.number_input(
                        "Max. Monatsrente (€/Mon.)",
                        min_value=0.0, max_value=10_000.0, value=200.0, step=10.0,
                        key="vp_add_mono",
                        help="Maximale monatliche Rente bei vollständiger Verrentung "
                             "ab dem frühesten Startdatum.",
                    )
                    laufzeit_opt = st.radio("Rentenlaufzeit",
                                            ["Lebenslang", "Befristet"],
                                            horizontal=True, key="vp_add_lz_opt")
                    laufzeit_jahre = 0
                    if laufzeit_opt == "Befristet":
                        laufzeit_jahre = st.number_input(
                            "Laufzeit (Jahre)", 1, 40, 20, key="vp_add_lz_j")
                else:
                    max_mono = 0.0
                    laufzeit_jahre = 0
                    st.info("Lebensversicherung → immer Einmalauszahlung.")

            with c3:
                frueh = st.number_input(
                    "Frühestes Startjahr",
                    min_value=AKTUELLES_JAHR, max_value=AKTUELLES_JAHR + 30,
                    value=profil.eintritt_jahr - 2,
                    step=1, key="vp_add_frueh",
                    help="Frühestes Jahr, in dem Auszahlung möglich ist.",
                )
                spaet = st.number_input(
                    "Spätestes Startjahr",
                    min_value=AKTUELLES_JAHR, max_value=AKTUELLES_JAHR + 35,
                    value=profil.eintritt_jahr + 3,
                    step=1, key="vp_add_spaet",
                    help="Spätestes Jahr, bis zu dem die Auszahlung gestartet sein muss.",
                )
                aufschub = st.slider(
                    "Aufschubverzinsung p.a. (%)", 0.0, 6.0, 2.0, step=0.1,
                    key="vp_add_aufschub",
                    help="Jährliche Wertsteigerung von Einmalbetrag und Monatsrente "
                         "für jedes Jahr, das die Auszahlung hinausgezögert wird.",
                ) / 100

            if st.button("Produkt hinzufügen", type="primary", key="vp_add_btn"):
                if not name.strip():
                    st.error("Bitte eine Bezeichnung eingeben.")
                elif max_einmal <= 0 and max_mono <= 0:
                    st.error("Mindestens Einmalbetrag oder Monatsrente muss > 0 sein.")
                elif spaet < frueh:
                    st.error("Spätestes Startjahr darf nicht vor frühestem liegen.")
                else:
                    st.session_state.vp_produkte.append({
                        "id": str(uuid.uuid4()),
                        "typ": typ_key, "typ_label": typ_label,
                        "name": name.strip(), "person": person,
                        "max_einmalzahlung": max_einmal,
                        "max_monatsrente": max_mono,
                        "laufzeit_jahre": laufzeit_jahre,
                        "fruehestes_startjahr": int(frueh),
                        "spaetestes_startjahr": int(spaet),
                        "aufschub_rendite": aufschub,
                    })
                    st.rerun()

        # ── Produktliste ──────────────────────────────────────────────────────
        produkte_dicts = st.session_state.vp_produkte
        if not produkte_dicts:
            st.info("Noch keine Produkte erfasst.")
            return

        st.subheader(f"Erfasste Verträge ({len(produkte_dicts)})")
        ges_einmal = sum(p["max_einmalzahlung"] for p in produkte_dicts)
        ges_mono = sum(p["max_monatsrente"] for p in produkte_dicts)
        m1, m2, m3 = st.columns(3)
        m1.metric("Gesamt max. Einmalung", f"{ges_einmal:,.0f} €")
        m2.metric("Gesamt max. Monatsrente", f"{ges_mono:,.0f} €/Mon.")
        m3.metric("Anzahl Verträge", str(len(produkte_dicts)))

        to_delete = None
        for p in produkte_dicts:
            lz = "lebenslang" if p["laufzeit_jahre"] == 0 else f"{p['laufzeit_jahre']} J."
            aufschub_txt = f"{p['aufschub_rendite']:.1%} p.a." if p["aufschub_rendite"] > 0 else "–"
            with st.container(border=True):
                ci, cd = st.columns([11, 1])
                with ci:
                    st.markdown(
                        f"**{p['name']}** · {p['typ_label']} · 👤 {p['person']}  \n"
                        f"Einmal: **{p['max_einmalzahlung']:,.0f} €** · "
                        f"Monatl.: **{p['max_monatsrente']:,.0f} €/Mon.** · "
                        f"Laufzeit: {lz} · "
                        f"Start: {p['fruehestes_startjahr']}–{p['spaetestes_startjahr']} · "
                        f"Aufschub: {aufschub_txt}"
                    )
                with cd:
                    if st.button("🗑", key=f"vp_del_{p['id']}"):
                        to_delete = p["id"]
        if to_delete:
            st.session_state.vp_produkte = [
                p for p in produkte_dicts if p["id"] != to_delete
            ]
            st.rerun()

        st.divider()

        # ── Parameter für Vergleich und Optimierung ───────────────────────────
        pc1, pc2 = st.columns(2)
        with pc1:
            horizon = st.slider("Lebenserwartung ab Renteneintritt (Jahre)",
                                10, 40, 25, key="vp_horizon")
        with pc2:
            rendite = st.slider("Rendite auf Einmalauszahlung p.a. (%)",
                                0.0, 8.0, float(profil.rendite_pa * 100),
                                step=0.5, key="vp_rendite") / 100

        st.divider()

        # ── Steueroptimierung ─────────────────────────────────────────────────
        st.subheader("🔍 Steueroptimierung – beste Kombination")
        st.caption(
            "Das System berechnet alle Kombinationen aus Startjahr und Auszahlungsart "
            "für jeden Vertrag und sucht die Kombination mit dem höchsten Netto-Gesamteinkommen "
            f"über {horizon} Jahre (Steuer + KV berücksichtigt, Jahr für Jahr)."
        )

        produkte_obj = [_aus_dict(p) for p in produkte_dicts]
        with st.spinner("Optimierung läuft …"):
            opt = optimiere_auszahlungen(profil, ergebnis, produkte_obj, horizon)

        if not opt:
            st.info("Keine Produkte für Optimierung vorhanden.")
            return

        # Kennzahlen
        oc1, oc2, oc3, oc4 = st.columns(4)
        oc1.metric(
            "Netto optimal (gesamt)", f"{opt['bestes_netto']:,.0f} €",
            help=f"Summe aller Netto-Jahreseinkommen über {horizon} Jahre.",
        )
        gewinn_vs_mono = opt["bestes_netto"] - opt["netto_alle_monatlich"]
        oc2.metric(
            "Vorteil vs. alles monatlich",
            f"{gewinn_vs_mono:+,.0f} €",
            delta_color="normal",
        )
        gewinn_vs_einmal = opt["bestes_netto"] - opt["netto_alle_einmal"]
        oc3.metric(
            "Vorteil vs. alles Einmal",
            f"{gewinn_vs_einmal:+,.0f} €",
            delta_color="normal",
        )
        oc4.metric("Kombinationen geprüft", f"{opt['anzahl_kombinationen']:,}")

        # Beste Kombination anzeigen
        st.success("**Optimale Strategie:**")
        for prod, startjahr, anteil in opt["beste_entscheidungen"]:
            einmal_wert = prod.max_einmalzahlung * (1 + prod.aufschub_rendite) ** max(
                0, startjahr - prod.fruehestes_startjahr
            )
            mono_wert = prod.max_monatsrente * (1 + prod.aufschub_rendite) ** max(
                0, startjahr - prod.fruehestes_startjahr
            )
            if anteil == 1.0:
                modus_txt = f"Einmalauszahlung **{einmal_wert:,.0f} €**"
            elif anteil == 0.0:
                modus_txt = f"Monatliche Rente **{mono_wert:,.0f} €/Mon.**"
            else:
                modus_txt = (
                    f"Kombiniert: **{einmal_wert * anteil:,.0f} €** Einmal + "
                    f"**{mono_wert * (1 - anteil):,.0f} €/Mon.**"
                )
            aufschub_jahre = startjahr - prod.fruehestes_startjahr
            aufschub_note = f" (+{aufschub_jahre} J. Aufschub)" if aufschub_jahre > 0 else ""
            st.markdown(f"- **{prod.name}**: {modus_txt} ab **{startjahr}**{aufschub_note}")

        st.divider()

        # Top-10-Vergleich
        st.subheader("Top-10 Kombinationen")
        df_top = pd.DataFrame(opt["top10"]).set_index("Kombination")
        st.dataframe(df_top, use_container_width=True)

        st.divider()

        # Balkenvergleich: optimal vs. alles monatlich vs. alles einmal
        st.subheader("Strategievergleich: Gesamtnetto über Laufzeit")
        fig_vgl = go.Figure(go.Bar(
            x=["Optimal", "Alles Monatlich\n(frühest möglich)",
               "Alles Einmal\n(frühest möglich)"],
            y=[opt["bestes_netto"], opt["netto_alle_monatlich"], opt["netto_alle_einmal"]],
            marker_color=["#4CAF50", "#2196F3", "#FF9800"],
            text=[f"{v:,.0f} €" for v in [
                opt["bestes_netto"], opt["netto_alle_monatlich"], opt["netto_alle_einmal"]
            ]],
            textposition="outside",
        ))
        fig_vgl.update_layout(
            template="plotly_white", height=360,
            yaxis=dict(title=f"Gesamt-Netto über {horizon} Jahre (€)", tickformat=",.0f"),
            margin=dict(l=10, r=10, t=10, b=10),
        )
        st.plotly_chart(fig_vgl, use_container_width=True)

        st.divider()

        # Jahresverlauf für optimale Strategie
        st.subheader("Jahresverlauf der optimalen Strategie")
        df_jd = pd.DataFrame(opt["jahresdaten"]).set_index("Jahr")
        fig_jv = go.Figure()
        fig_jv.add_trace(go.Bar(
            name="Netto (€)", x=df_jd.index, y=df_jd["Netto (€)"],
            marker_color="#4CAF50",
            hovertemplate="%{x}: %{y:,.0f} €<extra>Netto</extra>",
        ))
        fig_jv.add_trace(go.Bar(
            name="Steuer (€)", x=df_jd.index, y=df_jd["Steuer (€)"],
            marker_color="#EF9A9A",
            hovertemplate="%{x}: %{y:,.0f} €<extra>Steuer</extra>",
        ))
        fig_jv.add_trace(go.Bar(
            name="KV/PV (€)", x=df_jd.index, y=df_jd["KV/PV (€)"],
            marker_color="#FFF176",
            hovertemplate="%{x}: %{y:,.0f} €<extra>KV/PV</extra>",
        ))
        fig_jv.update_layout(
            barmode="stack", template="plotly_white", height=380,
            xaxis=dict(title="Jahr", dtick=2),
            yaxis=dict(title="€ / Jahr", tickformat=",.0f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig_jv, use_container_width=True)

        with st.expander("Rohdaten – Jahresverlauf"):
            st.dataframe(df_jd, use_container_width=True)

        st.divider()

        # ── Einzelvergleich je Produkt ────────────────────────────────────────
        st.subheader("Einzelvergleich je Vertrag (am frühesten Startdatum)")
        rows = []
        for pd_dict in produkte_dicts:
            p = _aus_dict(pd_dict)
            v = vergleiche_produkt(p, rendite, horizon)
            ist_lv = p.ist_lebensversicherung
            bestes = v["bestes"]
            rows.append({
                "Vertrag": p.name,
                "Typ": pd_dict["typ_label"],
                "Person": p.person,
                "Einmal (Total / Mon.)": f"{v['einmal']['total']:,.0f} € / {v['einmal']['monatlich']:,.0f} €",
                "Monatlich (Total)": "–" if ist_lv else f"{v['monatlich']['total']:,.0f} €",
                "Kombiniert (Total)": "–" if ist_lv else f"{v['kombiniert']['total']:,.0f} €",
                "Einfach-Empfehlung ✅": _LABELS[bestes],
            })
        st.dataframe(
            pd.DataFrame(rows).set_index("Vertrag"),
            use_container_width=True,
        )
        st.caption(
            "Die Einfach-Empfehlung vergleicht nur Gesamteinnahmen ohne Steuereffekte. "
            "Die Steueroptimierung oben liefert das präzisere Ergebnis."
        )

        st.caption(
            "⚠️ Alle Vertragseinnahmen werden vereinfacht voll besteuert (konservativ, "
            "korrekt für bAV). Lebensversicherungen mit Halbeinkünfteverfahren oder "
            "Riester-Zulagen sind nicht gesondert modelliert. Steuerberatung empfohlen."
        )
