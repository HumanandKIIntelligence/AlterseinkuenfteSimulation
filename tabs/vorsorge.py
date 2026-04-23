"""Vorsorge-Bausteine-Tab – bAV, Private RV, Riester, Lebensversicherung.

Jedes Produkt kann als Einmalauszahlung, monatliche Rente oder Kombination
ausgezahlt werden. Der Tab zeigt, welches Szenario je nach Lebenserwartung
das meiste Gesamteinkommen liefert.
"""

from __future__ import annotations

import uuid
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import Profil, RentenErgebnis, VorsorgeProdukt, vergleiche_produkt, _annuitaet

_TYPEN = ["bAV", "Private Rentenversicherung", "Riester-Rente", "Lebensversicherung"]
_TYP_KEYS = {"bAV": "bAV", "Private Rentenversicherung": "PrivateRente",
             "Riester-Rente": "Riester", "Lebensversicherung": "LV"}
_FARBEN = {"einmal": "#2196F3", "monatlich": "#4CAF50", "kombiniert": "#FF9800"}
_LABELS = {"einmal": "Einmalauszahlung", "monatlich": "Monatliche Rente",
           "kombiniert": "Kombiniert (Kapital + Rente)"}


def _init_state() -> None:
    if "vp_produkte" not in st.session_state:
        st.session_state.vp_produkte = []


def _produkt_aus_state(d: dict) -> VorsorgeProdukt:
    return VorsorgeProdukt(
        id=d["id"], typ=d["typ"], name=d["name"],
        kapital=d["kapital"], monatsrente=d["monatsrente"],
        laufzeit_jahre=d["laufzeit_jahre"],
    )


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis) -> None:
    _init_state()

    with T["Vorsorge"]:
        st.header("🏦 Vorsorge-Bausteine")
        st.caption(
            "Erfasse deine betriebliche und private Altersvorsorge. "
            "Für jedes Produkt wird berechnet, welche Auszahlungsform – "
            "Einmal, monatlich oder gemischt – über verschiedene Laufzeiten "
            "das höchste Gesamteinkommen ergibt."
        )

        # ── Produkt hinzufügen ────────────────────────────────────────────────
        with st.expander("➕ Neues Produkt hinzufügen", expanded=not st.session_state.vp_produkte):
            c1, c2 = st.columns(2)
            with c1:
                typ_label = st.selectbox("Produkttyp", _TYPEN, key="vp_add_typ")
                typ_key = _TYP_KEYS[typ_label]
                name = st.text_input("Bezeichnung (z.B. bAV Firma Müller)", key="vp_add_name")
                kapital = st.number_input(
                    "Kapitalwert bei Renteneintritt (€)",
                    min_value=0.0, max_value=2_000_000.0, value=50_000.0, step=1_000.0,
                    key="vp_add_kapital",
                    help="Einmalauszahlung laut Vertrag / Hochrechnung zum Renteneintritt.",
                )
            with c2:
                if typ_key != "LV":
                    monatsrente = st.number_input(
                        "Monatliche Rente laut Angebot (€) – optional",
                        min_value=0.0, max_value=10_000.0, value=0.0, step=10.0,
                        key="vp_add_monatsrente",
                        help="Monatliche Rente laut Versicherungsangebot. "
                             "Wenn 0, wird sie aus dem Kapital berechnet.",
                    )
                    laufzeit_opt = st.radio(
                        "Rentenlaufzeit", ["Lebenslang", "Befristet"],
                        horizontal=True, key="vp_add_lz_opt",
                    )
                    laufzeit_jahre = 0
                    if laufzeit_opt == "Befristet":
                        laufzeit_jahre = st.number_input(
                            "Laufzeit (Jahre)", min_value=1, max_value=40, value=20,
                            key="vp_add_lz_jahre",
                        )
                else:
                    monatsrente = 0.0
                    laufzeit_jahre = 0
                    st.info("Lebensversicherungen werden immer als Einmalauszahlung behandelt.")

            if st.button("Produkt hinzufügen", type="primary", key="vp_add_btn"):
                if not name.strip():
                    st.error("Bitte eine Bezeichnung eingeben.")
                elif kapital <= 0:
                    st.error("Kapital muss größer als 0 sein.")
                else:
                    st.session_state.vp_produkte.append({
                        "id": str(uuid.uuid4()),
                        "typ": typ_key,
                        "typ_label": typ_label,
                        "name": name.strip(),
                        "kapital": kapital,
                        "monatsrente": monatsrente,
                        "laufzeit_jahre": laufzeit_jahre,
                    })
                    st.rerun()

        # ── Produktliste ──────────────────────────────────────────────────────
        produkte = st.session_state.vp_produkte
        if not produkte:
            st.info("Noch keine Produkte erfasst. Füge oben dein erstes Produkt hinzu.")
            return

        st.subheader(f"Meine Vorsorge-Bausteine ({len(produkte)})")
        total_kapital = sum(p["kapital"] for p in produkte)
        total_rente = sum(p["monatsrente"] for p in produkte)
        m1, m2, m3 = st.columns(3)
        m1.metric("Gesamtkapital (alle Produkte)", f"{total_kapital:,.0f} €")
        m2.metric("Summe monatl. Rentenangebote", f"{total_rente:,.0f} €/Mon.")
        m3.metric("Anzahl Produkte", str(len(produkte)))

        to_delete = None
        for p in produkte:
            lz_text = "lebenslang" if p["laufzeit_jahre"] == 0 else f"{p['laufzeit_jahre']} Jahre"
            rente_text = f"{p['monatsrente']:,.0f} €/Mon." if p["monatsrente"] > 0 else "aus Kapital berechnet"
            lv_hint = " · nur Einmalzahlung" if p["typ"] == "LV" else f" · Rente: {rente_text} · Laufzeit: {lz_text}"
            with st.container(border=True):
                col_info, col_del = st.columns([10, 1])
                with col_info:
                    st.markdown(
                        f"**{p['name']}** &nbsp;·&nbsp; {p['typ_label']} &nbsp;·&nbsp; "
                        f"Kapital: **{p['kapital']:,.0f} €**{lv_hint}"
                    )
                with col_del:
                    if st.button("🗑", key=f"vp_del_{p['id']}", help="Produkt löschen"):
                        to_delete = p["id"]
        if to_delete:
            st.session_state.vp_produkte = [p for p in produkte if p["id"] != to_delete]
            st.rerun()

        st.divider()

        # ── Horizont & Rendite ────────────────────────────────────────────────
        st.subheader("Vergleichsparameter")
        hc1, hc2 = st.columns(2)
        with hc1:
            horizon = st.slider(
                "Lebenserwartung ab Renteneintritt (Jahre)",
                min_value=10, max_value=40, value=25,
                help="Statistik: 67-jährige Männer ~18 J., Frauen ~21 J. "
                     "25–30 J. = konservative Planung.",
            )
        with hc2:
            rendite = st.slider(
                "Rendite auf Einmalauszahlung p.a. (%)",
                min_value=0.0, max_value=8.0, value=float(profil.rendite_pa * 100),
                step=0.5,
                help="Rendite, die du auf eine Einmalauszahlung erzielen könntest.",
            ) / 100

        st.divider()

        # ── Szenario-Vergleich je Produkt ─────────────────────────────────────
        st.subheader("Szenarien je Produkt")
        st.caption(
            f"Vergleich bei **{horizon} Jahren** Laufzeit ab Renteneintritt "
            f"und **{rendite:.1%} p.a.** Eigenrendite."
        )

        vergleiche = {}
        for pd_dict in produkte:
            p = _produkt_aus_state(pd_dict)
            vergleiche[p.id] = (pd_dict, vergleiche_produkt(p, rendite, horizon))

        rows = []
        for pid, (pd_dict, v) in vergleiche.items():
            ist_lv = pd_dict["typ"] == "LV"
            laufzeit_jahre = pd_dict["laufzeit_jahre"]
            lz_text = "lebenslang" if laufzeit_jahre == 0 else f"{laufzeit_jahre} J."
            bestes = v["bestes"]

            def fmt(key: str) -> str:
                if key == "monatlich" and pd_dict["monatsrente"] <= 0 and not ist_lv:
                    return "(aus Kapital)"
                t = v[key]["total"]
                m = v[key]["monatlich"]
                marker = " ✅" if key == bestes else ""
                return f"{t:,.0f} € / {m:,.0f} €/Mon.{marker}"

            row = {
                "Produkt": pd_dict["name"],
                "Typ": pd_dict["typ_label"],
                "Kapital": f"{pd_dict['kapital']:,.0f} €",
                "Laufzeit": "–" if ist_lv else lz_text,
                "Einmalauszahlung": fmt("einmal"),
                "Monatl. Rente": "–" if ist_lv else fmt("monatlich"),
                "Kombiniert": "–" if ist_lv else fmt("kombiniert"),
                "Empfehlung": _LABELS[bestes],
            }
            rows.append(row)

        df = pd.DataFrame(rows).set_index("Produkt")
        st.dataframe(df, use_container_width=True)
        st.caption("Format: Gesamteinnahmen / Monatlicher Betrag · ✅ = bestes Szenario für diese Laufzeit")

        st.divider()

        # ── Balkendiagramm: Gesamteinnahmen ───────────────────────────────────
        st.subheader("Gesamteinnahmen je Szenario und Produkt")

        fig_bar = go.Figure()
        produkt_namen = [pd_dict["name"] for pd_dict, _ in vergleiche.values()]
        for szenario, farbe, label in [
            ("einmal", "#2196F3", "Einmalauszahlung"),
            ("monatlich", "#4CAF50", "Monatliche Rente"),
            ("kombiniert", "#FF9800", "Kombiniert"),
        ]:
            werte = []
            for pd_dict, v in vergleiche.values():
                if pd_dict["typ"] == "LV" and szenario != "einmal":
                    werte.append(0)
                elif pd_dict["monatsrente"] <= 0 and szenario == "monatlich":
                    werte.append(v["monatlich"]["total"])
                else:
                    werte.append(v[szenario]["total"])
            fig_bar.add_trace(go.Bar(
                name=label,
                x=produkt_namen,
                y=werte,
                marker_color=farbe,
                text=[f"{v:,.0f} €" if v > 0 else "" for v in werte],
                textposition="outside",
            ))
        fig_bar.update_layout(
            barmode="group",
            template="plotly_white",
            height=400,
            yaxis=dict(title="Gesamteinnahmen (€)", tickformat=",.0f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=40, b=10),
        )
        st.plotly_chart(fig_bar, use_container_width=True)

        st.divider()

        # ── Break-Even: Ab wann lohnt monatliche Rente? ───────────────────────
        st.subheader("Break-Even: Monatliche Rente vs. Einmalauszahlung")
        st.caption("Ab wie vielen Jahren übersteigen die monatlichen Rentenzahlungen die Einmalauszahlung?")

        fig_be = go.Figure()
        horizonte = list(range(5, 41))
        for pd_dict, _ in vergleiche.values():
            if pd_dict["typ"] == "LV" or pd_dict["monatsrente"] <= 0:
                continue
            p = _produkt_aus_state(pd_dict)
            M = pd_dict["monatsrente"]
            lz = pd_dict["laufzeit_jahre"] if pd_dict["laufzeit_jahre"] > 0 else max(horizonte)
            kum_rente = [M * 12 * min(lz, h) for h in horizonte]
            kum_einmal = [vergleiche_produkt(p, rendite, h)["einmal"]["total"] for h in horizonte]
            fig_be.add_trace(go.Scatter(
                x=horizonte, y=kum_rente,
                name=f"{pd_dict['name']} – Monatl.", line=dict(width=2),
                hovertemplate=f"{pd_dict['name']}: %{{y:,.0f}} €<extra>Monatl.</extra>",
            ))
            fig_be.add_trace(go.Scatter(
                x=horizonte, y=kum_einmal,
                name=f"{pd_dict['name']} – Einmal", line=dict(width=2, dash="dash"),
                hovertemplate=f"{pd_dict['name']}: %{{y:,.0f}} €<extra>Einmal</extra>",
            ))
        if fig_be.data:
            fig_be.add_vline(
                x=horizon, line_dash="dot", line_color="#888",
                annotation_text=f"Gewählter Horizont ({horizon} J.)",
            )
            fig_be.update_layout(
                template="plotly_white", height=380,
                xaxis=dict(title="Jahre ab Renteneintritt", dtick=5),
                yaxis=dict(title="Kumulierte Einnahmen (€)", tickformat=",.0f"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=10, r=10, t=40, b=10),
            )
            st.plotly_chart(fig_be, use_container_width=True)
        else:
            st.info("Break-Even-Analyse nur für Produkte mit monatlichem Rentenangebot verfügbar.")

        st.divider()

        # ── Gesamteinkommen-Rechner ───────────────────────────────────────────
        st.subheader("Monatliches Gesamteinkommen – Szenario-Rechner")
        st.caption(
            "Wähle für jedes Produkt individuell die Auszahlungsart. "
            "Das Ergebnis zeigt dein monatliches Einkommen zusätzlich zur gesetzlichen Rente."
        )

        auswahl: dict[str, str] = {}
        for pd_dict, v in vergleiche.items():
            ist_lv = vergleiche[pd_dict][0]["typ"] == "LV"
            pd_data = vergleiche[pd_dict][0]
            bestes = v["bestes"]
            if ist_lv:
                optionen = ["Einmalauszahlung"]
            elif pd_data["monatsrente"] <= 0:
                optionen = ["Einmalauszahlung", "Monatliche Rente (berechnet)"]
            else:
                optionen = ["Einmalauszahlung", "Monatliche Rente", "Kombiniert"]
            empfehlung_idx = {
                "einmal": 0, "monatlich": 1, "kombiniert": 2 if len(optionen) > 2 else 1,
            }.get(bestes, 0)
            auswahl[pd_dict] = st.selectbox(
                pd_data["name"],
                optionen,
                index=min(empfehlung_idx, len(optionen) - 1),
                key=f"vp_sel_{pd_dict}",
                help=f"✅ Empfehlung bei {horizon} Jahren: {_LABELS[bestes]}",
            )

        # Monatliches Einkommen berechnen
        monatlich_gesamt = ergebnis.netto_monatlich
        details = [("Gesetzliche Rente (netto)", ergebnis.netto_monatlich)]

        for pd_dict, wahl in auswahl.items():
            pd_data, v = vergleiche[pd_dict]
            if "Kombiniert" in wahl:
                m = v["kombiniert"]["monatlich"]
                anteil = v["kombiniert"]["anteil"]
                label = f"{pd_data['name']} ({anteil:.0%} Kapital + {1-anteil:.0%} Rente)"
            elif "Einmal" in wahl:
                m = v["einmal"]["monatlich"]
                label = f"{pd_data['name']} (Einmal, als Annuität)"
            else:
                m = v["monatlich"]["monatlich"]
                label = f"{pd_data['name']} (monatliche Rente)"
            monatlich_gesamt += m
            details.append((label, m))

        st.markdown("---")
        st.markdown("**Monatliches Gesamteinkommen:**")
        for label, betrag in details:
            ca, cb = st.columns([3, 1])
            ca.markdown(f"+ {label}")
            cb.markdown(f"**{betrag:,.0f} €**")
        st.markdown(f"### = **{monatlich_gesamt:,.0f} € / Monat**")

        # Jahresgesamteinkommen
        c1, c2, c3 = st.columns(3)
        c1.metric("Monatlich gesamt", f"{monatlich_gesamt:,.0f} €")
        c2.metric("Jährlich gesamt", f"{monatlich_gesamt * 12:,.0f} €")
        gesamteinnahmen = monatlich_gesamt * 12 * horizon
        c3.metric(f"Gesamteinnahmen ({horizon} Jahre)", f"{gesamteinnahmen:,.0f} €")

        # Donut: Einkommensquellen
        donut_labels = [d[0] for d in details]
        donut_values = [max(0.0, d[1]) for d in details]
        if any(v > 0 for v in donut_values):
            fig_donut = go.Figure(go.Pie(
                labels=donut_labels,
                values=donut_values,
                hole=0.45,
                textinfo="percent+label",
                hovertemplate="%{label}<br>%{value:,.0f} €/Mon.<extra></extra>",
            ))
            fig_donut.update_layout(
                height=340,
                margin=dict(l=0, r=0, t=20, b=0),
                showlegend=False,
                title=dict(text="Einkommensquellen", x=0.5),
            )
            st.plotly_chart(fig_donut, use_container_width=True)

        st.caption(
            "⚠️ Monatliche Einmalauszahlungen werden als Annuität (Kapitalverzehr + Zinsen) "
            f"über {horizon} Jahre berechnet. Steuerliche Aspekte der Kapitalentnahme "
            "sind nicht berücksichtigt."
        )
