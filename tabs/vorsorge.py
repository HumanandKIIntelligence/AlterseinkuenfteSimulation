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

_TYPEN = ["bAV", "Private Rentenversicherung", "Riester-Rente", "Rürup-Rente",
          "ETF-Depot", "Lebensversicherung"]
_TYP_KEYS = {
    "bAV": "bAV",
    "Private Rentenversicherung": "PrivateRente",
    "Riester-Rente": "Riester",
    "Rürup-Rente": "Rürup",
    "ETF-Depot": "ETF",
    "Lebensversicherung": "LV",
}
_LABELS = {"einmal": "Einmalauszahlung", "monatlich": "Monatliche Rente",
           "kombiniert": "Kombiniert (Kapital + Rente)"}
_FARBEN = {"Einmal": "#2196F3", "Monatlich": "#4CAF50", "50/50": "#FF9800"}
_TF_OPTS = {"30 % (Aktien-ETF)": 0.30, "15 % (Misch-ETF)": 0.15,
            "60 % (Immobilien-ETF)": 0.60, "0 % (Anleihen-ETF)": 0.0}


def _init_state() -> None:
    if "vp_produkte" not in st.session_state:
        st.session_state.vp_produkte = []


def _migriere(p: dict) -> dict:
    """Altes Format auf neues Format bringen; fehlende Felder mit Defaults ergänzen."""
    if "max_einmalzahlung" not in p:
        p["max_einmalzahlung"] = p.pop("kapital", 0.0)
        p["max_monatsrente"] = p.pop("monatsrente", 0.0)
        from engine import AKTUELLES_JAHR
        p["fruehestes_startjahr"] = AKTUELLES_JAHR + 5
        p["spaetestes_startjahr"] = AKTUELLES_JAHR + 8
        p["aufschub_rendite"] = 0.02
    if "person" not in p:
        p["person"] = "Person 1"
    if "vertragsbeginn" not in p:
        p["vertragsbeginn"] = 2010
    if "einzahlungen_gesamt" not in p:
        p["einzahlungen_gesamt"] = 0.0
    if "teilfreistellung" not in p:
        p["teilfreistellung"] = 0.30
    if "typ_label" not in p:
        _tl = {"bAV": "bAV", "PrivateRente": "Private Rentenversicherung",
               "Riester": "Riester-Rente", "Rürup": "Rürup-Rente",
               "ETF": "ETF-Depot", "LV": "Lebensversicherung"}
        p["typ_label"] = _tl.get(p.get("typ", "bAV"), p.get("typ", "bAV"))
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
        vertragsbeginn=d["vertragsbeginn"],
        einzahlungen_gesamt=d["einzahlungen_gesamt"],
        teilfreistellung=d["teilfreistellung"],
    )


def _steuer_hinweis(p: dict) -> str:
    if p["typ"] in ("LV", "PrivateRente"):
        vbeg = p.get("vertragsbeginn", 2010)
        einz = p.get("einzahlungen_gesamt", 0.0)
        if vbeg < 2005:
            return " · Steuerfrei (Altvertrag vor 2005)"
        return f" · Vertrag {vbeg}, Einz. {einz:,.0f} €"
    if p["typ"] == "ETF":
        tf = p.get("teilfreistellung", 0.30)
        einz = p.get("einzahlungen_gesamt", 0.0)
        return f" · TF {tf:.0%}, Einz. {einz:,.0f} €"
    if p["typ"] == "Rürup":
        return " · Nur Monatsrente (Basisrente)"
    return ""


def _render_edit_felder(p: dict, profil2, profil: Profil) -> dict:
    """Rendert die Bearbeitungsfelder für ein Produkt. Gibt das aktualisierte Dict zurück."""
    from engine import AKTUELLES_JAHR as _AJ
    pid = p["id"]
    typ_key = p["typ"]
    nur_einmal_typ = typ_key in ("LV", "ETF")
    nur_mono_typ = typ_key == "Rürup"

    ec1, ec2, ec3 = st.columns(3)

    with ec1:
        new_name = st.text_input("Bezeichnung", value=p["name"], key=f"ve_name_{pid}")
        person_opts = ["Person 1"] + (["Person 2"] if profil2 else [])
        p_idx = person_opts.index(p["person"]) if p["person"] in person_opts else 0
        new_person = st.selectbox("Zugeordnet zu", person_opts, index=p_idx,
                                  key=f"ve_person_{pid}")

    with ec2:
        if not nur_mono_typ:
            new_einmal = st.number_input(
                "Max. Einmalauszahlung (€)", 0.0, 2_000_000.0,
                value=float(p["max_einmalzahlung"]), step=1_000.0,
                key=f"ve_einmal_{pid}",
            )
        else:
            new_einmal = 0.0
            st.info("Rürup/Basisrente → kein Kapitalwahlrecht, nur Monatsrente.")

        if not nur_einmal_typ:
            new_mono = st.number_input(
                "Max. Monatsrente (€/Mon.)", 0.0, 10_000.0,
                value=float(p["max_monatsrente"]), step=10.0,
                key=f"ve_mono_{pid}",
            )
            lz_idx = 1 if p["laufzeit_jahre"] > 0 else 0
            lz_opt = st.radio("Rentenlaufzeit", ["Lebenslang", "Befristet"],
                              index=lz_idx, horizontal=True, key=f"ve_lz_{pid}")
            if lz_opt == "Befristet":
                new_lz = int(st.number_input(
                    "Laufzeit (Jahre)", 1, 40,
                    value=max(1, int(p["laufzeit_jahre"])),
                    key=f"ve_lz_j_{pid}",
                ))
            else:
                new_lz = 0
        else:
            new_mono = 0.0
            new_lz = 0
            if typ_key == "LV":
                st.info("Lebensversicherung → immer Einmalauszahlung.")
            else:
                st.info("ETF-Depot → immer Einmalauszahlung (Kapitalentnahme).")

        if typ_key in ("LV", "PrivateRente"):
            new_vbeg = int(st.number_input(
                "Vertragsbeginn (Jahr)", 1950, _AJ,
                value=int(p.get("vertragsbeginn", 2010)), step=1,
                key=f"ve_vbeg_{pid}",
                help="Vor 2005 = Altvertrag (steuerfrei); ab 2005 = § 20 Abs. 1 Nr. 6 EStG.",
            ))
            new_einz = float(st.number_input(
                "Gesamte Einzahlungen (€)", 0.0, 2_000_000.0,
                value=float(p.get("einzahlungen_gesamt", 0.0)), step=500.0,
                key=f"ve_einz_{pid}",
                help="Summe aller eingezahlten Beiträge.",
            ))
            new_tf = float(p.get("teilfreistellung", 0.30))
        elif typ_key == "ETF":
            new_vbeg = int(p.get("vertragsbeginn", _AJ))
            new_einz = float(st.number_input(
                "Eingezahltes Kapital (€)", 0.0, 2_000_000.0,
                value=float(p.get("einzahlungen_gesamt", 0.0)), step=500.0,
                key=f"ve_einz_{pid}",
                help="Kaufkostenanteil; nur Kursgewinn ist steuerpflichtig.",
            ))
            cur_tf = float(p.get("teilfreistellung", 0.30))
            tf_default = min(_TF_OPTS, key=lambda k: abs(_TF_OPTS[k] - cur_tf))
            tf_label = st.selectbox(
                "Teilfreistellung (§ 20 InvStG)", list(_TF_OPTS.keys()),
                index=list(_TF_OPTS.keys()).index(tf_default),
                key=f"ve_tf_{pid}",
            )
            new_tf = _TF_OPTS[tf_label]
        else:
            new_vbeg = int(p.get("vertragsbeginn", 2010))
            new_einz = float(p.get("einzahlungen_gesamt", 0.0))
            new_tf = float(p.get("teilfreistellung", 0.30))

    with ec3:
        new_frueh = int(st.number_input(
            "Frühestes Startjahr", _AJ, _AJ + 30,
            value=max(_AJ, int(p["fruehestes_startjahr"])), step=1,
            key=f"ve_frueh_{pid}",
        ))
        new_spaet = int(st.number_input(
            "Spätestes Startjahr", _AJ, _AJ + 35,
            value=max(_AJ, int(p["spaetestes_startjahr"])), step=1,
            key=f"ve_spaet_{pid}",
        ))
        new_aufschub = st.slider(
            "Aufschubverzinsung p.a. (%)", 0.0, 6.0,
            value=round(float(p["aufschub_rendite"]) * 100, 1),
            step=0.1, key=f"ve_aufschub_{pid}",
        ) / 100

    return {
        **p,
        "name": new_name.strip() or p["name"],
        "person": new_person,
        "max_einmalzahlung": new_einmal,
        "max_monatsrente": new_mono,
        "laufzeit_jahre": new_lz,
        "fruehestes_startjahr": new_frueh,
        "spaetestes_startjahr": new_spaet,
        "aufschub_rendite": new_aufschub,
        "vertragsbeginn": new_vbeg,
        "einzahlungen_gesamt": new_einz,
        "teilfreistellung": new_tf,
    }


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis, profil2=None,
           mieteinnahmen: float = 0.0, mietsteigerung: float = 0.0) -> None:
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
                nur_einmal_typ = typ_key in ("LV", "ETF")
                nur_mono_typ   = typ_key == "Rürup"

                if not nur_mono_typ:
                    max_einmal = st.number_input(
                        "Max. Einmalauszahlung (€)",
                        min_value=0.0, max_value=2_000_000.0, value=50_000.0, step=1_000.0,
                        key="vp_add_einmal",
                        help="Maximaler Betrag bei vollständiger Einmalauszahlung "
                             "ab dem frühesten Startdatum.",
                    )
                else:
                    max_einmal = 0.0
                    st.info("Rürup/Basisrente → kein Kapitalwahlrecht, nur Monatsrente.")

                if not nur_einmal_typ:
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
                    if typ_key == "LV":
                        st.info("Lebensversicherung → immer Einmalauszahlung.")
                    else:
                        st.info("ETF-Depot → immer Einmalauszahlung (Kapitalentnahme).")

            # Felder für Steuerberechnung (LV, PrivateRente, ETF)
            vertragsbeginn = 2010
            einzahlungen_gesamt = 0.0
            teilfreistellung = 0.30
            if typ_key in ("LV", "PrivateRente"):
                with c2:
                    from engine import AKTUELLES_JAHR as _AJ
                    vertragsbeginn = st.number_input(
                        "Vertragsbeginn (Jahr)",
                        min_value=1950, max_value=_AJ,
                        value=st.session_state.get("vp_add_vbeg", 2010),
                        step=1, key="vp_add_vbeg",
                        help="Jahr des Vertragsabschlusses. Entscheidend für Steuerregelung: "
                             "vor 2005 = steuerfrei (Altvertrag); ab 2005 = § 20 Abs. 1 Nr. 6 EStG.",
                    )
                    einzahlungen_gesamt = st.number_input(
                        "Gesamte Einzahlungen (€)",
                        min_value=0.0, max_value=2_000_000.0,
                        value=st.session_state.get("vp_add_einz", 0.0),
                        step=500.0, key="vp_add_einz",
                        help="Summe aller eingezahlten Beiträge. Nur der Ertrag "
                             "(Auszahlung − Einzahlungen) ist ggf. steuerpflichtig.",
                    )
            elif typ_key == "ETF":
                with c2:
                    einzahlungen_gesamt = st.number_input(
                        "Eingezahltes Kapital (€)",
                        min_value=0.0, max_value=2_000_000.0,
                        value=st.session_state.get("vp_add_einz", 0.0),
                        step=500.0, key="vp_add_einz",
                        help="Summe aller Einzahlungen (Kaufkostenanteil). "
                             "Nur der Kursgewinn ist nach Teilfreistellung steuerpflichtig.",
                    )
                    _tf_label = st.selectbox(
                        "Teilfreistellung (§ 20 InvStG)",
                        list(_TF_OPTS.keys()),
                        key="vp_add_tf",
                        help="Aktien-ETF: 30 %; Misch-ETF: 15 %; Immobilien-ETF: 60 %.",
                    )
                    teilfreistellung = _TF_OPTS[_tf_label]

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
                        "vertragsbeginn": int(vertragsbeginn),
                        "einzahlungen_gesamt": float(einzahlungen_gesamt),
                        "teilfreistellung": float(teilfreistellung),
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

        editing_id = st.session_state.get("vp_edit_id")
        to_delete = None
        edit_result = None  # (idx, updated_dict | None)

        for idx, p in enumerate(produkte_dicts):
            lz = "lebenslang" if p["laufzeit_jahre"] == 0 else f"{p['laufzeit_jahre']} J."
            aufschub_txt = f"{p['aufschub_rendite']:.1%} p.a." if p["aufschub_rendite"] > 0 else "–"

            with st.container(border=True):
                if editing_id == p["id"]:
                    st.markdown(f"**✏️ {p['name']}** · {p['typ_label']} · 👤 {p['person']} – Bearbeiten")
                    updated = _render_edit_felder(p, profil2, profil)
                    col_ok, col_cancel = st.columns(2)
                    if col_ok.button("✅ Übernehmen", key=f"vp_ok_{p['id']}",
                                     type="primary", use_container_width=True):
                        edit_result = (idx, updated)
                    if col_cancel.button("❌ Abbrechen", key=f"vp_cancel_{p['id']}",
                                         use_container_width=True):
                        edit_result = (idx, None)
                else:
                    ci, ce, cd = st.columns([9, 1, 1])
                    with ci:
                        st.markdown(
                            f"**{p['name']}** · {p['typ_label']} · 👤 {p['person']}  \n"
                            f"Einmal: **{p['max_einmalzahlung']:,.0f} €** · "
                            f"Monatl.: **{p['max_monatsrente']:,.0f} €/Mon.** · "
                            f"Laufzeit: {lz} · "
                            f"Start: {p['fruehestes_startjahr']}–{p['spaetestes_startjahr']} · "
                            f"Aufschub: {aufschub_txt}"
                            + _steuer_hinweis(p)
                        )
                    with ce:
                        if st.button("✏️", key=f"vp_edit_{p['id']}", help="Bearbeiten"):
                            st.session_state["vp_edit_id"] = p["id"]
                            st.rerun()
                    with cd:
                        if st.button("🗑", key=f"vp_del_{p['id']}", help="Löschen"):
                            to_delete = p["id"]

        if edit_result is not None:
            idx, updated = edit_result
            if updated is not None:
                st.session_state.vp_produkte[idx] = updated
            st.session_state.pop("vp_edit_id", None)
            st.rerun()
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
        miete_hinweis = (
            f" Mieteinnahmen ({mieteinnahmen:,.0f} €/Mon., +{mietsteigerung:.1%} p.a.) "
            "erhöhen die Steuerprogression und beeinflussen die optimale Auszahlungsstrategie."
        ) if mieteinnahmen > 0 else ""
        st.caption(
            "Das System berechnet alle Kombinationen aus Startjahr und Auszahlungsart "
            "für jeden Vertrag und sucht die Kombination mit dem höchsten Netto-Gesamteinkommen "
            f"über {horizon} Jahre (Steuer + KV berücksichtigt, Jahr für Jahr).{miete_hinweis}"
        )

        produkte_obj = [_aus_dict(p) for p in produkte_dicts]
        with st.spinner("Optimierung läuft …"):
            opt = optimiere_auszahlungen(profil, ergebnis, produkte_obj, horizon,
                                         mieteinnahmen, mietsteigerung)

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
            name="Netto (€)", x=df_jd.index, y=df_jd["Netto"],
            marker_color="#4CAF50",
            hovertemplate="%{x}: %{y:,.0f} €<extra>Netto</extra>",
        ))
        fig_jv.add_trace(go.Bar(
            name="Steuer (€)", x=df_jd.index, y=df_jd["Steuer"],
            marker_color="#EF9A9A",
            hovertemplate="%{x}: %{y:,.0f} €<extra>Steuer</extra>",
        ))
        fig_jv.add_trace(go.Bar(
            name="KV/PV (€)", x=df_jd.index, y=df_jd["KV_PV"],
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
            "⚠️ Steuerliche Simulation auf Basis der aktuellen Rechtslage (2024). "
            "Keine individuelle Steuer- oder Rechtsberatung. Komplexe Sonderfälle "
            "(z. B. Riester-Zulagen, LV-Todesfallschutznachweis, Soli) werden vereinfacht. "
            "Steuerberatung empfohlen."
        )
