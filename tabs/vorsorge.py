"""Vorsorge-Bausteine-Tab – bAV, Private RV, Riester, Lebensversicherung.

Pro Vertrag: max. Einmalauszahlung, max. Monatsrente, frühestes/spätestes
Startdatum und Aufschubverzinsung. Steueroptimierung über alle Kombinationen.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    Profil, RentenErgebnis, VorsorgeProdukt,
    vergleiche_produkt, optimiere_auszahlungen, _annuitaet,
    _netto_ueber_horizont,
)


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _opt_hash(produkte_dicts: list, horizon: int, mieteinnahmen: float,
              mietsteigerung: float, profil: Profil, profil2=None,
              ergebnis2=None, veranlagung: str = "Getrennt",
              gehalt: float = 0.0) -> str:
    data = {
        "profil": dataclasses.asdict(profil),
        "prods": sorted(produkte_dicts, key=lambda p: p["id"]),
        "h": horizon,
        "m": round(mieteinnahmen * 100),
        "s": round(mietsteigerung * 10000),
        "v": veranlagung,
        "g": round(gehalt),
        "p2": dataclasses.asdict(profil2) if profil2 else None,
        "e2": dataclasses.asdict(ergebnis2) if ergebnis2 else None,
    }
    return hashlib.md5(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()


def _clear_opt_caches() -> None:
    st.session_state.pop("_vp_opt_cache", None)
    st.session_state.pop("_eo_opt_cache", None)


def _run_optimierung(cache_ns: str, profil: Profil, ergebnis: RentenErgebnis,
                     produkte_obj: list, produkte_dicts: list,
                     horizon: int, miet: float, miet_stg: float,
                     profil2=None, ergebnis2=None,
                     veranlagung: str = "Getrennt",
                     gehalt: float = 0.0,
                     ausgaben_plan: "dict[int, float] | None" = None) -> dict:
    h = _opt_hash(produkte_dicts, horizon, miet, miet_stg, profil,
                  profil2=profil2, ergebnis2=ergebnis2, veranlagung=veranlagung, gehalt=gehalt)
    # Ausgaben-Plan in Hash einbeziehen damit Cache invalidiert wird
    if ausgaben_plan:
        import hashlib, json as _json
        h = hashlib.md5((h + _json.dumps(sorted(ausgaben_plan.items()))).encode()).hexdigest()
    cached = st.session_state.get(f"_{cache_ns}_opt_cache")
    if cached and cached.get("k") == h:
        return cached["r"]
    result = optimiere_auszahlungen(profil, ergebnis, produkte_obj, horizon, miet, miet_stg,
                                     profil2=profil2, ergebnis2=ergebnis2, veranlagung=veranlagung,
                                     gehalt_monatlich=gehalt, ausgaben_plan=ausgaben_plan)
    st.session_state[f"_{cache_ns}_opt_cache"] = {"k": h, "r": result}
    return result

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
    if "erzwungener_anteil" not in p:
        p["erzwungener_anteil"] = None
    if "startjahr_fix" not in p:
        p["startjahr_fix"] = False
    if "laufende_kapitalertraege_mono" not in p:
        p["laufende_kapitalertraege_mono"] = 0.0
    if "einzel_einzahlung" not in p:
        p["einzel_einzahlung"] = p.get("einzahlungen_gesamt", 0.0)
    if "jaehrl_einzahlung" not in p:
        p["jaehrl_einzahlung"] = 0.0
    if "jaehrl_dynamik" not in p:
        p["jaehrl_dynamik"] = 0.0
    if "beitragsbefreiung_jahr" not in p:
        p["beitragsbefreiung_jahr"] = 0
    if "als_kapitalanlage" not in p:
        p["als_kapitalanlage"] = False
    if "kap_rendite_pa" not in p:
        p["kap_rendite_pa"] = -1.0
    if "etf_ausschuettend" not in p:
        p["etf_ausschuettend"] = False
    if "riester_zulage_nutzen" not in p:
        p["riester_zulage_nutzen"] = False
    if "riester_kinder_zulage" not in p:
        p["riester_kinder_zulage"] = 0
    if "riester_kinder_zulage_alt" not in p:
        p["riester_kinder_zulage_alt"] = 0
    if "bav_ag_zuschuss" not in p:
        p["bav_ag_zuschuss"] = False
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
        einzahlungen_gesamt=d.get("einzel_einzahlung", d.get("einzahlungen_gesamt", 0.0)),
        teilfreistellung=d["teilfreistellung"],
        erzwungener_anteil=d.get("erzwungener_anteil"),
        laufende_kapitalertraege_mono=d.get("laufende_kapitalertraege_mono", 0.0),
        einzel_einzahlung=d.get("einzel_einzahlung", 0.0),
        jaehrl_einzahlung=d.get("jaehrl_einzahlung", 0.0),
        jaehrl_dynamik=d.get("jaehrl_dynamik", 0.0),
        beitragsbefreiung_jahr=d.get("beitragsbefreiung_jahr", 0),
        als_kapitalanlage=d.get("als_kapitalanlage", False),
        kap_rendite_pa=d.get("kap_rendite_pa", -1.0),
        etf_ausschuettend=d.get("etf_ausschuettend", False),
        riester_zulage_nutzen=d.get("riester_zulage_nutzen", False),
        riester_kinder_zulage=d.get("riester_kinder_zulage", 0),
        riester_kinder_zulage_alt=d.get("riester_kinder_zulage_alt", 0),
        bav_ag_zuschuss=d.get("bav_ag_zuschuss", False),
    )


def _steuer_hinweis(p: dict) -> str:
    if p["typ"] in ("LV", "PrivateRente"):
        vbeg = p.get("vertragsbeginn", 2010)
        einz = p.get("einzahlungen_gesamt", 0.0)
        if vbeg < 2005:
            return " · Steuerfrei (Altvertrag vor 2005)"
        return f" · Vertrag {vbeg}, Einz. {_de(einz)} €"
    if p["typ"] == "ETF":
        tf = p.get("teilfreistellung", 0.30)
        einz = p.get("einzahlungen_gesamt", 0.0)
        return f" · TF {tf:.0%}, Einz. {_de(einz)} €"
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
            new_tf = float(p.get("teilfreistellung", 0.30))
        elif typ_key == "ETF":
            new_vbeg = int(p.get("vertragsbeginn", _AJ))
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
            new_tf = float(p.get("teilfreistellung", 0.30))

        # ── Einzahlungsfelder ─────────────────────────────────────────────────
        st.markdown("**Einzahlungen**")
        new_einzel_einz = float(st.number_input(
            "Summe Einmaleinzahlungen (€)", 0.0, 2_000_000.0,
            value=float(p.get("einzel_einzahlung", p.get("einzahlungen_gesamt", 0.0))),
            step=500.0, key=f"ve_einzel_{pid}",
            help="Summe aller geleisteten Einmaleinzahlungen (Kostenbasis für Steuerberechnung). "
                 "Ersetzt das frühere Feld 'Gesamte Einzahlungen'.",
        ))
        new_jaehrl_einz = float(st.number_input(
            "Jährl. Einzahlung (€/Jahr)", 0.0, 100_000.0,
            value=float(p.get("jaehrl_einzahlung", 0.0)),
            step=100.0, key=f"ve_jaehrl_{pid}",
            help="Laufender Jahresbeitrag ab heute bis zum Auszahlungsjahr. "
                 "Wird mit Dynamik jährlich gesteigert und zur Kostenbasis addiert.",
        ))
        new_jaehrl_dyn = float(st.number_input(
            "Jährl. Dynamik (%)", 0.0, 10.0,
            value=round(float(p.get("jaehrl_dynamik", 0.0)) * 100, 2),
            step=0.5, key=f"ve_dynamik_{pid}",
            help="Jährliche Beitragssteigerung in %. Typisch: 2–3 % für Inflation.",
        )) / 100
        new_bb_jahr = int(st.number_input(
            "Jahr Beitragsbefreiung (0 = keine)", 0, _AJ + 50,
            value=int(p.get("beitragsbefreiung_jahr", 0)),
            step=1, key=f"ve_bbj_{pid}",
            help="Ab diesem Jahr werden keine laufenden Beiträge mehr gezählt "
                 "(z. B. bei BU-Schutz zahlt die Versicherung). "
                 "Die von der Versicherung übernommenen Beiträge gelten steuerlich "
                 "als weitere Einzahlungen (§ 10 EStG, konservative Betrachtung).",
        ))

        # Berechnete Gesamteinzahlungen als Info anzeigen
        if new_jaehrl_einz > 0:
            _frueh_disp = max(_AJ, int(p.get("fruehestes_startjahr", _AJ)))
            _spaet_disp = max(_frueh_disp, int(p.get("spaetestes_startjahr", _frueh_disp)))

            def _eff_einz(startjahr: int) -> float:
                tot = new_einzel_einz
                bei = new_jaehrl_einz
                for _j in range(_AJ, startjahr):
                    if new_bb_jahr > 0 and _j >= new_bb_jahr:
                        break
                    tot += bei
                    bei *= (1 + new_jaehrl_dyn)
                return tot

            _eff_f = _eff_einz(_frueh_disp)
            _eff_s = _eff_einz(_spaet_disp)
            if _frueh_disp == _spaet_disp:
                st.caption(f"Gesamteinzahlungen bei Start {_frueh_disp}: **{_de(_eff_f)} €**")
            else:
                st.caption(
                    f"Gesamteinzahlungen: **{_de(_eff_f)} €** (Start {_frueh_disp}) "
                    f"– **{_de(_eff_s)} €** (Start {_spaet_disp})"
                )

    with ec3:
        fix_jahr = st.checkbox(
            "Startjahr fixieren", value=bool(p.get("startjahr_fix", False)),
            key=f"ve_fix_{pid}",
            help="Nur ein Startjahr prüfen → weniger Kombinationen, schneller.",
        )
        if fix_jahr:
            new_frueh = int(st.number_input(
                "Startjahr (fix)", _AJ, _AJ + 30,
                value=max(_AJ, int(p["fruehestes_startjahr"])), step=1,
                key=f"ve_frueh_{pid}",
            ))
            new_spaet = new_frueh
        else:
            new_frueh = int(st.number_input(
                "Frühestes Startjahr", _AJ, _AJ + 30,
                value=max(_AJ, int(p["fruehestes_startjahr"])), step=1,
                key=f"ve_frueh_{pid}",
            ))
            new_spaet = int(st.number_input(
                "Spätestes Startjahr", _AJ, _AJ + 35,
                value=max(new_frueh, int(p["spaetestes_startjahr"])), step=1,
                key=f"ve_spaet_{pid}",
            ))

        new_aufschub = st.slider(
            "Aufschubverzinsung p.a. (%)", 0.0, 6.0,
            value=round(float(p["aufschub_rendite"]) * 100, 1),
            step=0.1, key=f"ve_aufschub_{pid}",
        ) / 100

        # Auszahlungsmodus: nur für Produkte mit echtem Wahlrecht
        _MODUS_OPTS = {
            "Optimieren (Optimizer wählt)": None,
            "Nur Monatlich":  0.0,
            "50/50 fixiert":  0.5,
            "Nur Einmal":     1.0,
        }
        if not nur_mono_typ and not nur_einmal_typ:
            cur_anteil = p.get("erzwungener_anteil")
            cur_label = next(
                (k for k, v in _MODUS_OPTS.items() if v == cur_anteil),
                "Optimieren (Optimizer wählt)",
            )
            modus_label = st.selectbox(
                "Auszahlungsmodus",
                list(_MODUS_OPTS.keys()),
                index=list(_MODUS_OPTS.keys()).index(cur_label),
                key=f"ve_modus_{pid}",
                help="Fixiert den Auszahlungsmodus → reduziert Kombinationen, beschleunigt Optimierung.",
            )
            new_anteil = _MODUS_OPTS[modus_label]
        else:
            new_anteil = p.get("erzwungener_anteil")

        new_lfd_kap = float(st.number_input(
            "Laufende Kapitalerträge (€/Mon.)",
            min_value=0.0, max_value=10_000.0,
            value=float(p.get("laufende_kapitalertraege_mono", 0.0)),
            step=10.0, key=f"ve_lfdkap_{pid}",
            help="Laufende Erträge (Zinsen, Dividenden, ETF-Ausschüttungen) aus diesem Produkt. "
                 "Relevant für freiwillig GKV-Versicherte: zählen zur KV-Bemessungsgrundlage.",
        ))

        # Als Kapitalanlage: nur wenn Einmalauszahlung möglich
        if not nur_mono_typ:
            new_als_ka = st.checkbox(
                "Als Kapitalanlage anlegen",
                value=bool(p.get("als_kapitalanlage", False)),
                key=f"ve_alskapanlage_{pid}",
                help="Einmalauszahlung wird nicht sofort als Einkommen ausgezahlt, sondern "
                     "in den internen Kapitalstock investiert. Der Pool wächst mit der "
                     "eingestellten Rendite und wird gleichmäßig als Annuität über den "
                     "Planungshorizont verzehrt. Steuer und KV werden dabei berücksichtigt.",
            )
            if new_als_ka:
                new_kap_r = -1.0  # Pool nutzt immer Profil-Rendite
            else:
                new_als_ka = False
                new_kap_r = -1.0
        else:
            new_als_ka = False
            new_kap_r = -1.0

        # ETF: Ausschüttungstyp
        if typ_key == "ETF":
            new_etf_aus = st.checkbox(
                "Ausschüttender ETF",
                value=bool(p.get("etf_ausschuettend", False)),
                key=f"ve_etfaus_{pid}",
                help="Ausschüttende ETFs erhalten keine Teilfreistellung auf Ausschüttungen "
                     "(§ 20 InvStG, nur thesaurierende Fonds profitieren von TF bei Verkauf). "
                     "Effektive Teilfreistellung = 0 % → voll steuerpflichtige Erträge.",
            )
        else:
            new_etf_aus = False

        # bAV: AG-Pflichtzuschuss
        if typ_key == "bAV":
            new_ag_zuschuss = st.checkbox(
                "AG-Pflichtzuschuss 15 % einbeziehen",
                value=bool(p.get("bav_ag_zuschuss", False)),
                key=f"ve_ag_zus_{pid}",
                help=(
                    "Seit 2022: Arbeitgeber muss mind. 15 % auf Entgeltumwandlungs-bAV "
                    "zuschießen (§ 1a Abs. 1a BetrAVG). "
                    "Wirkt nur während aktiver Beschäftigung (bis Renteneintritt). "
                    "Erhöht die Kostenbasis um +15 % des Jahresbeitrags."
                ),
            )
            if new_ag_zuschuss and new_jaehrl_einz > 0:
                st.caption(
                    f"Inkl. AG-Zuschuss: {_de(new_jaehrl_einz * 1.15)} €/Jahr "
                    f"(AN {_de(new_jaehrl_einz)} € + AG {_de(new_jaehrl_einz * 0.15)} €)"
                )
        else:
            new_ag_zuschuss = False

        # Riester: interaktive Zulagen-Felder
        new_riester_zulage = False
        new_riester_kinder = 0
        new_riester_kinder_alt = 0
        if typ_key == "Riester":
            new_riester_zulage = st.checkbox(
                "Staatliche Zulagen einbeziehen",
                value=bool(p.get("riester_zulage_nutzen", False)),
                key=f"ve_riester_zul_{pid}",
                help=(
                    "Riester-Zulagen (§ 84/85 EStG) werden zur Kostenbasis addiert. "
                    "Gilt nur für aktive Einzahlungsjahre bis Renteneintritt. "
                    "Grundzulage: 175 €/Jahr; Kinderzulage: 300 €/Kind (ab 2008) / 185 €/Kind (vor 2008)."
                ),
            )
            if new_riester_zulage:
                _kc1, _kc2 = st.columns(2)
                with _kc1:
                    new_riester_kinder = int(st.number_input(
                        "Kinder ab 2008 (300 €/Kind)", 0, 5,
                        value=int(p.get("riester_kinder_zulage", 0)),
                        step=1, key=f"ve_riester_kinder_{pid}",
                        help="Kinder, geboren ab 01.01.2008 → 300 €/Kind/Jahr (§ 85 Abs. 1 S. 2 EStG).",
                    ))
                with _kc2:
                    new_riester_kinder_alt = int(st.number_input(
                        "Kinder vor 2008 (185 €/Kind)", 0, 5,
                        value=int(p.get("riester_kinder_zulage_alt", 0)),
                        step=1, key=f"ve_riester_kinder_alt_{pid}",
                        help="Kinder, geboren vor 01.01.2008 → 185 €/Kind/Jahr (§ 85 Abs. 1 S. 1 EStG).",
                    ))
                _jahre_aktiv = max(0, new_frueh - _AJ)
                _zulage_j = 175.0 + 300.0 * new_riester_kinder + 185.0 * new_riester_kinder_alt
                st.caption(
                    f"Zulagen ca. {_de(_zulage_j)} €/Jahr × {_jahre_aktiv} Jahre "
                    f"= **{_de(_zulage_j * _jahre_aktiv)} €** Gesamtzulage bis Renteneintritt"
                )
            st.info(
                "**Riester § 83 EStG:** Mindesteigenbeitrag: 4 % Vorjahresbrutto − Zulagen "
                "(mind. 60 €/Jahr). Auszahlung im Rentenalter voll steuerpflichtig (§ 22 Nr. 5 EStG).",
                icon=None,
            )

        # Beitragsbefreiung > spätestes Startjahr
        if new_bb_jahr > 0 and new_bb_jahr > new_spaet:
            st.warning(
                f"⚠️ Beitragsbefreiung ab {new_bb_jahr} liegt nach dem "
                f"spätesten Startjahr {new_spaet} → hat keinen Effekt auf die Einzahlungsrechnung."
            )

    return {
        **p,
        "name": new_name.strip() or p["name"],
        "person": new_person,
        "max_einmalzahlung": new_einmal,
        "max_monatsrente": new_mono,
        "laufzeit_jahre": new_lz,
        "fruehestes_startjahr": new_frueh,
        "spaetestes_startjahr": new_spaet,
        "startjahr_fix": fix_jahr,
        "aufschub_rendite": new_aufschub,
        "vertragsbeginn": new_vbeg,
        "einzahlungen_gesamt": new_einzel_einz,  # backward compat
        "teilfreistellung": new_tf,
        "erzwungener_anteil": new_anteil,
        "laufende_kapitalertraege_mono": new_lfd_kap,
        "einzel_einzahlung": new_einzel_einz,
        "jaehrl_einzahlung": new_jaehrl_einz,
        "jaehrl_dynamik": new_jaehrl_dyn,
        "beitragsbefreiung_jahr": new_bb_jahr,
        "als_kapitalanlage": new_als_ka,
        "kap_rendite_pa": new_kap_r,
        "etf_ausschuettend": new_etf_aus,
        "bav_ag_zuschuss": new_ag_zuschuss,
        "riester_zulage_nutzen": new_riester_zulage,
        "riester_kinder_zulage": new_riester_kinder,
        "riester_kinder_zulage_alt": new_riester_kinder_alt,
    }


def render(T: dict, profil: Profil, ergebnis: RentenErgebnis, profil2=None,
           mieteinnahmen: float = 0.0, mietsteigerung: float = 0.0,
           ergebnis2=None, veranlagung: str = "Getrennt") -> None:
    _rc = st.session_state.get("_rc", 0)
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
                lfd_kap_add = st.number_input(
                    "Laufende Kapitalerträge (€/Mon.)",
                    min_value=0.0, max_value=10_000.0, value=0.0, step=10.0,
                    key="vp_add_lfdkap",
                    help="Laufende Erträge (Zinsen, Dividenden, Ausschüttungen). "
                         "Relevant für freiwillig GKV-Versicherte.",
                )

            if st.button("Produkt hinzufügen", type="primary", key="vp_add_btn"):
                if not name.strip():
                    st.error("Bitte eine Bezeichnung eingeben.")
                elif max_einmal <= 0 and max_mono <= 0:
                    st.error("Mindestens Einmalbetrag oder Monatsrente muss > 0 sein.")
                elif spaet < frueh:
                    st.error("Spätestes Startjahr darf nicht vor frühestem liegen.")
                else:
                    _clear_opt_caches()
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
                        "laufende_kapitalertraege_mono": float(lfd_kap_add),
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
        m1.metric("Gesamt max. Einmalung", f"{_de(ges_einmal)} €")
        m2.metric("Gesamt max. Monatsrente", f"{_de(ges_mono)} €/Mon.")
        m3.metric("Anzahl Verträge", str(len(produkte_dicts)))

        editing_id = st.session_state.get("vp_edit_id")
        to_delete = None
        edit_result = None  # (idx, updated_dict | None)

        for idx, p in enumerate(produkte_dicts):
            lz = "lebenslang" if p["laufzeit_jahre"] == 0 else f"{p['laufzeit_jahre']} J."
            aufschub_txt = (
                f"{p['aufschub_rendite']:.1%} p.a.".replace(".", ",")
                if p["aufschub_rendite"] > 0 else "–"
            )

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
                            f"Einmal: **{_de(p['max_einmalzahlung'])} €** · "
                            f"Monatl.: **{_de(p['max_monatsrente'])} €/Mon.** · "
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
            _clear_opt_caches()
            st.rerun()
        if to_delete:
            st.session_state.vp_produkte = [
                p for p in produkte_dicts if p["id"] != to_delete
            ]
            _clear_opt_caches()
            st.rerun()

        st.divider()

        # ── Parameter für Vergleich und Optimierung ───────────────────────────
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            horizon = st.slider("Planungshorizont ab Renteneintritt (Jahre)",
                                10, 40, 25, key="vp_horizon")
            from engine import AKTUELLES_JAHR as _AJ_VP
            _pre = max(0, profil.eintritt_jahr - _AJ_VP) if not profil.bereits_rentner else 0
            if _pre > 0:
                st.caption(f"Gesamt: {horizon + _pre} Jahre ({_pre} Arbeits- + {horizon} Rentenjahre)")
        with pc2:
            rendite = st.slider("Rendite auf Einmalauszahlung p.a. (%)",
                                0.0, 8.0, float(profil.rendite_pa * 100),
                                step=0.5, key="vp_rendite") / 100
        with pc3:
            if not profil.bereits_rentner:
                gehalt = float(st.session_state.get("opt_gehalt_mono", 0.0))
                st.metric("Bruttogehalt P1 (€/Mon.)", f"{_de(gehalt)} €")
                st.caption("Einstellbar im Tab ⚙️ Profil.")
            else:
                gehalt = 0.0

        st.divider()

        # ── Steueroptimierung ─────────────────────────────────────────────────
        produkte_obj = [_aus_dict(p) for p in produkte_dicts]
        with st.spinner("Optimierung läuft …"):
            opt = _run_optimierung("vp", profil, ergebnis, produkte_obj, produkte_dicts,
                                   horizon, mieteinnahmen, mietsteigerung,
                                   profil2=profil2, ergebnis2=ergebnis2, veranlagung=veranlagung,
                                   gehalt=gehalt)

        if not opt:
            st.info("Keine Produkte für Optimierung vorhanden.")
            return

        # ── Session state for per-contract strategy selection ─────────────────
        _sels_key = f"rc{_rc}_vp_sels"
        # dict: product_name -> "YYYY_mono"|"YYYY_einmal"|None
        _curr_sels: dict[str, str | None] = dict(st.session_state.get(_sels_key, {}))

        _OLD_SELS_VP = {"fm", "sm", "fe", "se"}

        def _parse_sel_vp(val) -> tuple[int | None, str]:
            if val is None:
                return None, "einmal"
            try:
                _parts = str(val).rsplit("_", 1)
                return int(_parts[0]), _parts[1] if len(_parts) > 1 else "einmal"
            except (ValueError, IndexError):
                return None, "einmal"

        _prod_by_name_vp = {p.name: p for p in produkte_obj}
        _prod_by_id_early = {p.id: p for p in produkte_obj}

        # Migrate: old format values ("fm"/"sm"/"fe"/"se") and/or name-based keys → id-based YYYY_mode
        _vp_sels_is_old = bool(_curr_sels) and (
            any(v in _OLD_SELS_VP for v in _curr_sels.values() if v is not None)
            or any(k in _prod_by_name_vp and k not in _prod_by_id_early for k in _curr_sels)
        )
        if _vp_sels_is_old:
            _migrated: dict[str, str | None] = {}
            for _k_m, _sv_m in _curr_sels.items():
                # Resolve product: prefer id lookup, fall back to name
                _po_m = _prod_by_id_early.get(_k_m) or _prod_by_name_vp.get(_k_m)
                if _po_m is None or _sv_m is None:
                    continue
                if _sv_m in _OLD_SELS_VP:
                    _old_mode_m = "mono" if _sv_m in ("fm", "sm") else "einmal"
                    _old_year_m = _po_m.spaetestes_startjahr if _sv_m in ("sm", "se") else _po_m.fruehestes_startjahr
                    _migrated[_po_m.id] = f"{_old_year_m}_{_old_mode_m}"
                else:
                    _migrated[_po_m.id] = _sv_m
            _curr_sels = _migrated
            st.session_state[_sels_key] = _curr_sels

        # Defaults beim ersten Laden setzen (vor Chart-Rendering), keyed by p.id
        if not _curr_sels:
            for _p_d in produkte_obj:
                _dm_d = "mono" if _p_d.max_monatsrente > 0 else "einmal"
                _curr_sels[_p_d.id] = f"{_p_d.fruehestes_startjahr}_{_dm_d}"
            st.session_state[_sels_key] = _curr_sels

        # ── Netto/Steuer/KV aus Benutzer-Selektion berechnen ─────────────────
        _vp_mono_ids_sel = {
            pid for pid, sv in _curr_sels.items() if sv and str(sv).endswith("_mono")
        }
        _vp_sj_ov_sel: dict[str, int] = {}
        for _pid_sel, _sv_sel in _curr_sels.items():
            _yr_sel, _ = _parse_sel_vp(_sv_sel)
            if _yr_sel is not None:
                _vp_sj_ov_sel[_pid_sel] = _yr_sel
        _vp_eff_entsch = [
            (p, _vp_sj_ov_sel.get(p.id, p.fruehestes_startjahr),
             0.0 if (p.id in _vp_mono_ids_sel or p.max_einmalzahlung == 0
                     or (p.id not in _curr_sels and p.max_monatsrente > 0))
             else 1.0)
            for p in produkte_obj
        ]
        _, _vp_jd_raw = _netto_ueber_horizont(
            profil, ergebnis, _vp_eff_entsch, horizon,
            mieteinnahmen, mietsteigerung,
            profil2=profil2, ergebnis2=ergebnis2, veranlagung=veranlagung,
            gehalt_monatlich=gehalt,
        )
        _df_sel = pd.DataFrame(_vp_jd_raw).set_index("Jahr")

        # ── Optimale Strategie: Netto & Steuer pro Jahr ───────────────────────
        st.subheader("Optimale Strategie – Netto und Steuerbelastung pro Jahr")

        _df_opt = pd.DataFrame(opt["jahresdaten"]).set_index("Jahr")
        _opt_years = list(_df_opt.index)
        _max_yr_opt = max(_opt_years)

        # Hover: aktive Verträge je Jahr aus der optimalen Strategie
        def _opt_hover(yr: int) -> str:
            lines = []
            for _p, _sj, _ant in opt.get("beste_entscheidungen", []):
                _delay = _sj - _p.fruehestes_startjahr
                _aufschub = (1 + _p.aufschub_rendite) ** _delay
                if _ant == 1.0:
                    if yr == _sj:
                        lines.append(f"  {_p.name}: {_de(_p.max_einmalzahlung * _aufschub)} € Einmal")
                elif _ant == 0.0:
                    _ej = (_sj + _p.laufzeit_jahre - 1) if _p.laufzeit_jahre > 0 else _max_yr_opt
                    if _sj <= yr <= _ej:
                        lines.append(f"  {_p.name}: {_de(_p.max_monatsrente * _aufschub)} €/Mon.")
                else:
                    _ej = (_sj + _p.laufzeit_jahre - 1) if _p.laufzeit_jahre > 0 else _max_yr_opt
                    if yr == _sj:
                        lines.append(f"  {_p.name}: {_de(_p.max_einmalzahlung * _aufschub * _ant)} € Einmal (Anteil)")
                    if _sj <= yr <= _ej:
                        lines.append(f"  {_p.name}: {_de(_p.max_monatsrente * _aufschub * (1 - _ant))} €/Mon. (Anteil)")
            return ("<b>Aktive Verträge:</b><br>" + "<br>".join(lines)) if lines else "–"

        _hover_opt = [_opt_hover(yr) for yr in _opt_years]

        # Kennzahlen
        _avg_netto_mon = _df_sel["Netto"].mean() / 12
        _total_steuer  = _df_sel["Steuer"].sum()
        _total_kv      = _df_sel["KV_PV"].sum()
        _total_netto   = _df_sel["Netto"].sum()
        _overhead_pct  = (_total_steuer + _total_kv) / max(1, _total_steuer + _total_kv + _total_netto) * 100
        _km1, _km2, _km3, _km4 = st.columns(4)
        _km1.metric("Ø Netto/Mon. (optimal)", f"{_de(_avg_netto_mon)} €")
        _km2.metric(f"Steuer gesamt ({horizon} J.)", f"{_de(_total_steuer)} €")
        _km3.metric("Steuer+KV-Anteil am Brutto", f"{_overhead_pct:.1f} %")
        _km4.metric(f"Steuer+KV gesamt ({horizon} J.)", f"{_de(_total_steuer + _total_kv)} €",
                    help="Summe aller Steuern und KV/PV-Beiträge über den Planungshorizont "
                         "(durch Einmal- und Monatsauszahlungen der Vorsorgeprodukte).")

        # Stacked bars: Netto → ausgewählte Monatsverträge → Steuer → KV/PV
        # (barmode=stack; Steuer/KV werden immer auf den Gesamtbetrag berechnet)
        _SEL_COLORS = ["#1565C0","#B71C1C","#6A1B9A","#004D40","#E65100",
                       "#880E4F","#006064","#1B5E20","#F57F17","#4E342E"]
        fig_opt = go.Figure()
        fig_opt.add_trace(go.Bar(
            name="Netto", x=_df_sel.index, y=_df_sel["Netto"],
            marker_color="#4CAF50", customdata=_hover_opt,
            hovertemplate="<b>%{x}</b>: %{y:,.0f} € Netto<br>%{customdata}<extra>Netto</extra>",
        ))

        # Alle Verträge als EIN kombinierter Balkensegment mit Hover-Breakdown
        _vp_yr_vals: dict[int, float] = {yr: 0.0 for yr in _opt_years}
        _vp_yr_lines: dict[int, list[str]] = {yr: [] for yr in _opt_years}

        for _sp in produkte_obj:
            _sel_raw = _curr_sels.get(_sp.id)
            if _sel_raw:
                _sj_s, _mode_s = _parse_sel_vp(_sel_raw)
            else:
                # Produkt ohne gespeicherte Selektion: Defaults verwenden
                _sj_s = _sp.fruehestes_startjahr
                _mode_s = "mono" if (_sp.max_monatsrente > 0 and not _sp.ist_lebensversicherung and _sp.typ != "ETF") else "einmal"
            if _sj_s is None:
                continue
            _d_s  = max(0, _sj_s - _sp.fruehestes_startjahr)
            _af_s = (1 + _sp.aufschub_rendite) ** _d_s
            if _sj_s <= _sp.fruehestes_startjahr:
                _timing_lbl = "frühest"
            elif _sj_s >= _sp.spaetestes_startjahr:
                _timing_lbl = "spätest"
            else:
                _timing_lbl = f"ab {_sj_s}"
            if _mode_s == "mono":
                _lz_s = _sp.laufzeit_jahre if _sp.laufzeit_jahre > 0 else horizon
                _ej_s = min(_sj_s + _lz_s - 1, _max_yr_opt)
                _val_pa = _sp.max_monatsrente * _af_s * 12
                for _yr in _opt_years:
                    if _sj_s <= _yr <= _ej_s:
                        _vp_yr_vals[_yr] += _val_pa
                        _vp_yr_lines[_yr].append(
                            f"  {_sp.name}: {_de(_val_pa)} €/Jahr "
                            f"({_de(_sp.max_monatsrente * _af_s)} €/Mon., {_timing_lbl})"
                        )
            else:
                _val_e = _sp.max_einmalzahlung * _af_s
                if _sj_s in _vp_yr_vals:
                    _vp_yr_vals[_sj_s] += _val_e
                    _vp_yr_lines[_sj_s].append(
                        f"  {_sp.name}: {_de(_val_e)} € Einmal ({_timing_lbl})"
                    )

        _vp_combined_y = [_vp_yr_vals[yr] for yr in _opt_years]
        _vp_combined_hover = [
            "<b>Vorsorgeprodukte:</b><br>" + "<br>".join(_vp_yr_lines[yr])
            if _vp_yr_lines[yr] else "–"
            for yr in _opt_years
        ]
        if any(v > 0 for v in _vp_combined_y):
            fig_opt.add_trace(go.Bar(
                name="Vorsorgeprodukte",
                x=_opt_years, y=_vp_combined_y,
                marker_color="#7B1FA2",
                customdata=_vp_combined_hover,
                hovertemplate="<b>%{x}</b>: %{y:,.0f} €<br>%{customdata}<extra>Vorsorgeprodukte</extra>",
            ))

        # Steuer und KV/PV oben auf dem kompletten Betrag
        fig_opt.add_trace(go.Bar(
            name="Steuer", x=_df_sel.index, y=_df_sel["Steuer"],
            marker_color="#EF9A9A",
            hovertemplate="<b>%{x}</b>: %{y:,.0f} € Steuer<extra>Steuer</extra>",
        ))
        fig_opt.add_trace(go.Bar(
            name="KV/PV", x=_df_sel.index, y=_df_sel["KV_PV"],
            marker_color="#FFF176",
            hovertemplate="<b>%{x}</b>: %{y:,.0f} € KV/PV<extra>KV/PV</extra>",
        ))

        fig_opt.add_hline(
            y=_df_sel["Netto"].mean(), line_dash="dot", line_color="#2E7D32", line_width=1.5,
            annotation_text=f"Ø {_de(_df_sel['Netto'].mean() / 12)} €/Mon.",
            annotation_position="top right",
        )
        if not profil.bereits_rentner:
            fig_opt.add_vline(
                x=profil.eintritt_jahr, line_width=2, line_dash="dash", line_color="#5C6BC0",
            )
            fig_opt.add_annotation(
                x=profil.eintritt_jahr, y=1.04, yref="paper",
                text="Renteneintritt", showarrow=False,
                xanchor="left", yanchor="bottom",
                font=dict(color="#5C6BC0", size=11),
            )
        fig_opt.update_layout(
            barmode="stack", template="plotly_white", height=580,
            xaxis=dict(title="Jahr", dtick=2),
            yaxis=dict(title="€ / Jahr", tickformat=",.0f"),
            legend=dict(orientation="h", yanchor="bottom", y=1.1, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=200, b=10),
            separators=",.",
        )
        st.plotly_chart(fig_opt, use_container_width=True)
        st.caption(
            "Balken = optimale Strategie (Netto/farbige Vertragsanteile/Steuer/KV). "
            "Monatliche Verträge = Segment über alle Auszahlungsjahre; "
            "Einmalauszahlungen = Segment nur im Auszahlungsjahr. "
            "Steuer+KV immer auf Gesamtbetrag. Ø-Linie = Durchschnittsnetto."
        )

        st.divider()

        # ── Einzelvergleich mit Checkboxen ────────────────────────────────────
        _opt_timing: dict[str, int] = {
            prod.name: startjahr
            for prod, startjahr, _ in opt.get("beste_entscheidungen", [])
        }

        st.subheader("Einzelvergleich je Vertrag")
        _table_rows = []
        _avail_map: dict[str, set[str]] = {}      # keyed by name (legacy compat)
        _avail_id_map: dict[str, set[str]] = {}   # keyed by id
        for pd_dict in produkte_dicts:
            p = _aus_dict(pd_dict)
            ist_lv = p.ist_lebensversicherung
            hat_mono = p.max_monatsrente > 0 and not ist_lv and p.typ != "ETF"
            hat_einz = p.max_einmalzahlung > 0 and not p.ist_nur_monatsrente
            hat_spaet_p = p.spaetestes_startjahr > p.fruehestes_startjahr
            avail: set[str] = set()
            if hat_mono:                 avail.add("fm")
            if hat_mono and hat_spaet_p: avail.add("sm")
            if hat_einz:                 avail.add("fe")
            if hat_einz and hat_spaet_p: avail.add("se")
            _avail_map[p.name] = avail
            _avail_id_map[p.id] = avail

            v = vergleiche_produkt(p, rendite, horizon)
            bestes = v["bestes"]
            opt_j = _opt_timing.get(p.name, p.fruehestes_startjahr)
            if p.fruehestes_startjahr == p.spaetestes_startjahr:
                zeitpunkt = f"fixes Jahr ({p.fruehestes_startjahr})"
            elif opt_j <= p.fruehestes_startjahr:
                zeitpunkt = "frühestmöglich"
            elif opt_j >= p.spaetestes_startjahr:
                zeitpunkt = "spätestmöglich"
            else:
                zeitpunkt = f"ab {opt_j} (+{opt_j - p.fruehestes_startjahr} J. Aufschub)"
            empfehlung = f"{_LABELS[bestes]}, {zeitpunkt}"

            _table_rows.append({
                "Vertrag":     p.name,
                "Typ":         pd_dict["typ_label"],
                "Person":      p.person,
                "Einmal (Total / Mon.)": f"{_de(v['einmal']['total'])} € / {_de(v['einmal']['monatlich'])} €" if hat_einz else "–",
                "Monatlich (Total)":     f"{_de(v['monatlich']['total'])} €" if hat_mono else "–",
                "Kombiniert (Total)":    f"{_de(v['kombiniert']['total'])} €" if (hat_mono and hat_einz) else "–",
                "Einfach-Empfehlung ✅": empfehlung,
                "_hat_mono":   hat_mono,
                "_hat_einz":   hat_einz,
                "_hat_spaet":  hat_spaet_p,
                "_prod_obj":   p,
            })

        # Default: früheste Mono wenn verfügbar, sonst früheste Einmal; keyed by p.id
        if not _curr_sels and _avail_map:
            _curr_sels = {}
            for _id_d, _av_d in _avail_id_map.items():
                _po_d = _prod_by_id_early.get(_id_d)
                if _po_d is None:
                    continue
                _dm_d = "mono" if "fm" in _av_d else "einmal" if "fe" in _av_d else None
                if _dm_d:
                    _curr_sels[_id_d] = f"{_po_d.fruehestes_startjahr}_{_dm_d}"
            st.session_state[_sels_key] = _curr_sels
        else:
            # Neu hinzugefügte Produkte mit Standardwerten einsetzen
            _sels_updated = False
            for _id_n, _av_n in _avail_id_map.items():
                if _id_n not in _curr_sels:
                    _po_n = _prod_by_id_early.get(_id_n)
                    if _po_n:
                        _dm_n = "mono" if "fm" in _av_n else "einmal" if "fe" in _av_n else None
                        if _dm_n:
                            _curr_sels[_id_n] = f"{_po_n.fruehestes_startjahr}_{_dm_n}"
                            _sels_updated = True
            if _sels_updated:
                st.session_state[_sels_key] = _curr_sels

        _INFO_COLS = ["Typ", "Person", "Einmal (Total / Mon.)", "Monatlich (Total)",
                      "Kombiniert (Total)", "Einfach-Empfehlung ✅"]

        # Build unified table rows; split by whether product supports BOTH mono+einmal
        _prod_by_id_vp = {p.id: p for p in produkte_obj}
        _rows_both: list[dict] = []   # mono AND einmal → show Montl. checkbox
        _rows_single: list[dict] = [] # only one option → no checkbox

        for r in _table_rows:
            prod_name   = r["Vertrag"]
            _po_r       = r["_prod_obj"]
            _hat_mono_r = r["_hat_mono"]
            _hat_einz_r = r["_hat_einz"]
            _hat_spaet_r2 = r["_hat_spaet"]
            # Nur anzeigen wenn Auszahlungsjahr wählbar ODER beide Auszahlungsarten möglich
            if not _hat_spaet_r2 and not (_hat_mono_r and _hat_einz_r):
                continue
            sel         = _curr_sels.get(_po_r.id)
            _sel_yr, _sel_mode = _parse_sel_vp(sel)
            _yr_val = _sel_yr if _sel_yr is not None else _po_r.fruehestes_startjahr
            entry = {"Vertrag": prod_name, "_prod_id": _po_r.id}
            for c in _INFO_COLS:
                entry[c] = r[c]
            entry["Früh"]            = _po_r.fruehestes_startjahr
            entry["Spät"]            = _po_r.spaetestes_startjahr
            entry["Auszahlungsjahr"] = int(_yr_val)
            if _hat_mono_r and _hat_einz_r:
                entry["Montl. Auszahlung"] = bool(_sel_mode == "mono")
                _rows_both.append(entry)
            else:
                _rows_single.append(entry)

        _sels_tag = "_".join(
            f"{i}{str(v or 'n')[:4]}" for i, (_, v) in enumerate(sorted(_curr_sels.items()))
        ) or "0"
        _col_cfg_base: dict = {c: st.column_config.TextColumn(c) for c in _INFO_COLS}
        _col_cfg_base["Früh"] = st.column_config.NumberColumn("Früh", format="%d",
            help="Frühestmögliches Auszahlungsjahr.")
        _col_cfg_base["Spät"] = st.column_config.NumberColumn("Spät", format="%d",
            help="Spätestmögliches Auszahlungsjahr.")
        _col_cfg_base["Auszahlungsjahr"] = st.column_config.NumberColumn(
            "Auszahlungsjahr", min_value=2020, max_value=2099, step=1, format="%d",
            help="Auszahlungsjahr – muss zwischen Früh und Spät liegen.",
        )
        _disabled_base = ["Vertrag"] + _INFO_COLS + ["Früh", "Spät"]

        _col_cfg_both = dict(_col_cfg_base)
        _col_cfg_both["Montl. Auszahlung"] = st.column_config.CheckboxColumn(
            "Montl. Auszahlung",
            help="Monatliche Rente (☑) oder Einmalauszahlung (☐).",
        )

        _edited_both   = None
        _edited_single = None

        if _rows_both:
            _df_both = pd.DataFrame(_rows_both).set_index("_prod_id")
            _df_both.index.name = None
            _edited_both = st.data_editor(
                _df_both, column_config=_col_cfg_both, disabled=_disabled_base,
                key=f"rc{_rc}_vp_edit_both_{_sels_tag}", use_container_width=True,
                hide_index=True,
            )
        if _rows_single:
            if _rows_both:
                st.caption("Verträge mit fester Auszahlungsart (kein Monatliche/Einmal-Wechsel):")
            _df_single = pd.DataFrame(_rows_single).set_index("_prod_id")
            _df_single.index.name = None
            _edited_single = st.data_editor(
                _df_single, column_config=_col_cfg_base, disabled=_disabled_base,
                key=f"rc{_rc}_vp_edit_single_{_sels_tag}", use_container_width=True,
                hide_index=True,
            )

        st.caption("Auszahlungsjahr und Modus wählen. Montl.-Checkbox nur bei Verträgen "
                   "mit beiden Auszahlungsoptionen. Standard: früheste Monatsrente bzw. Einmalauszahlung.")

        # ── Enforcement: validate + update state ────────────────────────────
        def _process_vp_editor(edited_df, has_checkbox: bool) -> None:
            if edited_df is None:
                return
            for _pid_e, _row in edited_df.iterrows():
                _pid_e = str(_pid_e)
                _po_e = _prod_by_id_vp.get(_pid_e)
                if _po_e is None:
                    continue
                _hp_frueh_e = _po_e.fruehestes_startjahr
                _hp_spaet_e = _po_e.spaetestes_startjahr
                _disp_name  = _row.get("Vertrag", _pid_e)
                _raw_yr = _row.get("Auszahlungsjahr")
                new_year = int(_raw_yr) if _raw_yr is not None else _hp_frueh_e
                if new_year < _hp_frueh_e or new_year > _hp_spaet_e:
                    st.warning(
                        f"Auszahlungsjahr {new_year} für «{_disp_name}» liegt außerhalb "
                        f"[{_hp_frueh_e}, {_hp_spaet_e}] – auf {_hp_frueh_e} gesetzt."
                    )
                    new_year = max(_hp_frueh_e, min(_hp_spaet_e, new_year))
                if has_checkbox:
                    new_montl = bool(_row.get("Montl. Auszahlung", False))
                else:
                    new_montl = _po_e.max_monatsrente > 0
                mode = "mono" if new_montl else "einmal"
                _new_sels[_pid_e] = f"{new_year}_{mode}"

        _new_sels: dict[str, str | None] = {}
        _process_vp_editor(_edited_both, has_checkbox=True)
        _process_vp_editor(_edited_single, has_checkbox=False)
        # Produkte ohne Auswahlmöglichkeit (fixes Jahr + feste Auszahlungsart) beibehalten
        for _pid_fix, _sv_fix in _curr_sels.items():
            if _pid_fix not in _new_sels:
                _new_sels[_pid_fix] = _sv_fix

        if _new_sels != _curr_sels:
            st.session_state[_sels_key] = _new_sels
            st.rerun()

        st.caption(
            "⚠️ Steuerliche Simulation auf Basis der aktuellen Rechtslage (2024). "
            "Keine individuelle Steuer- oder Rechtsberatung. Komplexe Sonderfälle "
            "(z. B. Riester-Zulagen, LV-Todesfallschutznachweis, Soli) werden vereinfacht. "
            "Steuerberatung empfohlen."
        )
