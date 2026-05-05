"""Entnahme-Optimierung – steueroptimierte Auszahlungsstrategie für bekannte Verträge.

Zeigt den Steuer-Steckbrief je Produkt und ermittelt die optimale Kombination
aus Startjahr und Auszahlungsart (Einmal/Rente) unter Berücksichtigung von
Einkommensteuer, Abgeltungsteuer und KVdR-Beiträgen.
"""

from __future__ import annotations

import math
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import (
    Profil, RentenErgebnis, VorsorgeProdukt,
    optimiere_auszahlungen, besteuerungsanteil, ertragsanteil,
    BAV_FREIBETRAG_MONATLICH, BBG_KV_MONATLICH, _pv_satz, AKTUELLES_JAHR,
    _netto_ueber_horizont, kapitalwachstum, vergleiche_produkt,
)
from tabs import auszahlung
from tabs.utils import _de, _vorsorge_ausz_breakdown, render_zeitstrahl
try:
    from tabs.hypothek import (
        get_ausgaben_plan, get_restschuld_end,
        get_hyp_info, get_ausgaben_plan_optimierung, get_hyp_schedule,
        get_anschluss_schedule, _annuitaet_rate,
    )
except ImportError:
    def get_ausgaben_plan() -> dict:
        return {}
    def get_restschuld_end() -> float:
        return 0.0
    def get_hyp_info():
        return None
    def get_ausgaben_plan_optimierung() -> dict:
        return {}
    def get_hyp_schedule() -> list:
        return []
    def get_anschluss_schedule() -> list:
        return []




_MON_KURZ = ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
             "Jul", "Aug", "Sep", "Okt", "Nov", "Dez")


def _aus_dict(d: dict) -> VorsorgeProdukt:
    """Importiert _aus_dict aus vorsorge ohne zirkulären Import."""
    from tabs.vorsorge import _aus_dict as _vp_aus_dict
    return _vp_aus_dict(d)


def _kv_label_und_wert(typ: str, vbeg: int, tf: float, profil_p: Profil) -> tuple[str, str]:
    """Gibt (Spaltentitel, Zellwert) für die KV-Spalte zurück, abhängig vom KV-Status der Person."""
    is_pkv  = profil_p.krankenversicherung == "PKV"
    is_kvdr = profil_p.kvdr_pflicht  # nur relevant wenn GKV

    if is_pkv:
        return "KV", "–"

    if is_kvdr:
        col = "KVdR-pflichtig"
        kv_map = {
            "bAV":         "Ja – FB 187 €/Mon. (§ 226 SGB V)",
            "Riester":     "Nein",
            "Rürup":       "Nein",
            "LV":          "–",
            "PrivateRente":"Nein",
            "ETF":         "Nein",
        }
    else:
        col = "KV-pflichtig (§240)"
        kv_map = {
            "bAV":         "Ja – ohne Freibetrag (§ 240 SGB V)",
            "Riester":     "Ja (§ 240 SGB V)",
            "Rürup":       "Ja (§ 240 SGB V)",
            "LV":          "Ja – Einmalauszahlung (§ 240 SGB V)",
            "PrivateRente":"Ja (§ 240 SGB V)",
            "ETF":         "Ja – laufende Erträge (§ 240 SGB V)",
        }
    return col, kv_map.get(typ, "–")


def _steuer_steckbrief(prod_dicts: list[dict], profil: Profil,
                       profil2: Profil | None = None) -> pd.DataFrame:
    rows = []
    kv_cols_seen: set[str] = set()

    for p in prod_dicts:
        typ  = p.get("typ", "bAV")
        vbeg = p.get("vertragsbeginn", 2010)
        tf   = p.get("teilfreistellung", 0.30)
        person_label = p.get("person", "Person 1")
        profil_p = profil2 if (person_label == "Person 2" and profil2 is not None) else profil

        if typ == "bAV":
            einmal_regel = "100 % progressiv (§ 19 EStG)"
            mono_regel   = "100 % progressiv (§ 19 EStG)"
        elif typ == "Riester":
            einmal_regel = "100 % progressiv (§ 22 Nr. 5 EStG)"
            mono_regel   = "100 % progressiv (§ 22 Nr. 5 EStG)"
        elif typ == "Rürup":
            einmal_regel = "Nicht möglich (Basisrente)"
            ba = besteuerungsanteil(profil_p.eintritt_jahr)
            mono_regel   = f"Besteuerungsanteil {ba:.0%} (§ 22 Nr. 1 EStG)"
        elif typ == "LV":
            if vbeg < 2005:
                einmal_regel = "Steuerfrei (Altvertrag vor 2005)"
            else:
                einmal_regel = "Halbeinkünfte (≥ 12 J. + ≥ 60/62 J.) oder 25 % Abgeltungsteuer"
            mono_regel = "–"
        elif typ == "PrivateRente":
            if vbeg < 2005:
                einmal_regel = "Steuerfrei (Altvertrag vor 2005)"
            else:
                einmal_regel = "Halbeinkünfte (≥ 12 J. + ≥ 60/62 J.) oder 25 % Abgeltungsteuer"
            ea = ertragsanteil(profil_p.renteneintritt_alter)
            mono_regel = f"Ertragsanteil {ea:.0%} (§ 22 Nr. 1 S. 3a bb EStG)"
        elif typ == "ETF":
            einmal_regel = f"25 % Abgelt. auf {(1 - tf):.0%} des Gewinns (TF {tf:.0%}, § 20 InvStG)"
            mono_regel   = "–"
        else:
            einmal_regel = "–"
            mono_regel   = "–"

        kv_col, kv_val = _kv_label_und_wert(typ, vbeg, tf, profil_p)
        kv_cols_seen.add(kv_col)

        rows.append({
            "Produkt":          p["name"],
            "Typ":              p["typ_label"],
            "Person":           person_label,
            "Einmalauszahlung": einmal_regel,
            "Monatsrente":      mono_regel,
            "_kv_col":          kv_col,
            "_kv_val":          kv_val,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Wenn alle Produkte dieselbe KV-Spalte haben, einfache Spalte; sonst "KV-Status"
    if len(kv_cols_seen) == 1:
        col_name = kv_cols_seen.pop()
        df = df.rename(columns={"_kv_val": col_name}).drop(columns=["_kv_col"])
    else:
        df["KV-Status"] = df.apply(
            lambda r: f"{r['_kv_col']}: {r['_kv_val']}", axis=1)
        df = df.drop(columns=["_kv_col", "_kv_val"])

    return df




def _analyse_schenkungspotenzial(
    produkte: list[dict],
    profil: Profil,
    profil2: Profil | None,
    ergebnis: "RentenErgebnis | None" = None,
    ergebnis2: "RentenErgebnis | None" = None,
    mieteinnahmen_monatlich: float = 0.0,
) -> dict | None:
    """Analysiert Schenkungspotenzial zwischen GKV- und PKV-Person.

    Gibt None zurück wenn keine gemischte GKV/PKV-Konstellation vorliegt.
    Sonst ein Dict mit Empfehlungen, KV-Ersparnis und nicht übertragbaren Verträgen.
    """
    if profil2 is None:
        return None

    p1_gkv = profil.krankenversicherung == "GKV"
    p2_gkv = profil2.krankenversicherung == "GKV"
    if p1_gkv == p2_gkv:
        return None

    if p1_gkv:
        gkv_label, pkv_label, gkv_profil = "Person 1", "Person 2", profil
        gkv_ergebnis = ergebnis
    else:
        gkv_label, pkv_label, gkv_profil = "Person 2", "Person 1", profil2
        gkv_ergebnis = ergebnis2

    gkv_ist_freiwillig = not gkv_profil.kvdr_pflicht
    pv_voll, pv_halb = _pv_satz(gkv_profil.kinder_anzahl if gkv_profil.kinder else 0)
    kv_rate_voll = 0.146 + gkv_profil.gkv_zusatzbeitrag + pv_voll
    kv_rate_halb = 0.073 + gkv_profil.gkv_zusatzbeitrag / 2 + pv_halb

    gkv_prods = [p for p in produkte if p.get("person") == gkv_label]
    bav_mono_sum = sum(p.get("max_monatsrente", 0.0) for p in gkv_prods if p.get("typ") == "bAV")
    verbleibender_freibetrag = (
        max(0.0, BAV_FREIBETRAG_MONATLICH - bav_mono_sum)
        if not gkv_ist_freiwillig else 0.0
    )

    # Verbleibendes BBG-Kontingent für übertragbare Produkte (freiwillig GKV)
    # Basis: Festeinkommen das bereits KV-pflichtig ist und nicht übertragbar ist
    if gkv_ist_freiwillig and gkv_ergebnis is not None:
        ruerup_mono_sum = sum(
            p.get("max_monatsrente", 0.0) for p in gkv_prods if p.get("typ") == "Rürup"
        )
        _base_mono = (
            gkv_ergebnis.brutto_monatlich   # GRV/Pension + Profil.zusatz_monatlich
            + bav_mono_sum                   # bAV (nicht übertragbar)
            + ruerup_mono_sum                # Rürup (nicht übertragbar)
            + mieteinnahmen_monatlich / 2    # Mietanteil (50 %, konservativ)
        )
        _bbg_rest_mono = max(0.0, BBG_KV_MONATLICH - _base_mono)
    else:
        _bbg_rest_mono = BBG_KV_MONATLICH

    zu_verschieben: list[dict] = []
    nicht_verschiebbar: list[dict] = []
    gesamt_ersparnis_pa = 0.0
    gesamt_einmal_ersparnis = 0.0

    for p in gkv_prods:
        typ = p.get("typ", "")
        name = p.get("name", typ)
        mono = p.get("max_monatsrente", 0.0)
        einmal = p.get("max_einmalzahlung", 0.0)
        lfd_kap = p.get("laufende_kapitalertraege_mono", 0.0)

        if typ == "bAV":
            kv_j = (
                mono * 12 * kv_rate_voll if gkv_ist_freiwillig
                else max(0.0, mono - BAV_FREIBETRAG_MONATLICH) * 12 * kv_rate_halb
            )
            nicht_verschiebbar.append({
                "Vertrag": name, "Typ": typ,
                "KV-Kosten p.a. (ca.)": round(kv_j),
                "Grund": "Betriebsrente: nicht übertragbar (§ 1 BetrAVG)",
            })

        elif typ == "Rürup":
            kv_j = mono * 12 * kv_rate_voll if gkv_ist_freiwillig else 0.0
            nicht_verschiebbar.append({
                "Vertrag": name, "Typ": typ,
                "KV-Kosten p.a. (ca.)": round(kv_j),
                "Grund": "Rürup/Basisrente: nicht abtretbar (§ 97 EStG i.V.m. § 10 Abs. 1 Nr. 2b EStG)",
            })

        elif typ == "Riester":
            if gkv_ist_freiwillig:
                kv_relevant = min(mono, _bbg_rest_mono)
                kv_j = kv_relevant * 12 * kv_rate_voll
                _bbg_rest_mono = max(0.0, _bbg_rest_mono - kv_relevant)
            else:
                kv_j = 0.0
            gesamt_ersparnis_pa += kv_j
            zu_verschieben.append({
                "Vertrag": name, "Typ": typ, "Von": gkv_label, "An": pkv_label,
                "KV-Ersparnis p.a. (ca.)": round(kv_j),
                "Hinweis": "Nur zwischen Riester-berechtigten Eheleuten (§ 6 AltZertG)",
            })

        elif typ in ("PrivateRente", "LV"):
            _ist_einmal = False
            if gkv_ist_freiwillig:
                if mono > 0:
                    kv_relevant = min(mono, _bbg_rest_mono)
                    kv_j = kv_relevant * 12 * kv_rate_voll
                    _bbg_rest_mono = max(0.0, _bbg_rest_mono - kv_relevant)
                    hinweis = ""
                else:
                    einmal_relevant = min(einmal, _bbg_rest_mono * 12)
                    kv_j = einmal_relevant * kv_rate_voll
                    _ist_einmal = True
                    hinweis = "Einmalauszahlung – einmalige KV-Ersparnis (nicht p.a.)"
            else:
                kv_j = 0.0
                hinweis = "Unter KVdR nicht KV-pflichtig – kein KV-Vorteil durch Schenkung"
            if _ist_einmal:
                gesamt_einmal_ersparnis += kv_j
            else:
                gesamt_ersparnis_pa += kv_j
            zu_verschieben.append({
                "Vertrag": name, "Typ": typ, "Von": gkv_label, "An": pkv_label,
                "KV-Ersparnis p.a. (ca.)": round(kv_j),
                "Hinweis": hinweis,
            })

        elif typ == "ETF":
            if gkv_ist_freiwillig and lfd_kap > 0:
                kv_relevant = min(lfd_kap, _bbg_rest_mono)
                kv_j = kv_relevant * 12 * kv_rate_voll
                _bbg_rest_mono = max(0.0, _bbg_rest_mono - kv_relevant)
            else:
                kv_j = 0.0
            hinweis = (
                "" if kv_j > 0
                else "Keine lfd. Kapitalerträge erfasst – KV-Ersparnis nicht berechenbar"
            )
            gesamt_ersparnis_pa += kv_j
            zu_verschieben.append({
                "Vertrag": name, "Typ": typ, "Von": gkv_label, "An": pkv_label,
                "KV-Ersparnis p.a. (ca.)": round(kv_j),
                "Hinweis": hinweis,
            })

    return {
        "hat_empfehlung": (gesamt_ersparnis_pa + gesamt_einmal_ersparnis) > 0,
        "gkv_label": gkv_label,
        "pkv_label": pkv_label,
        "gkv_ist_freiwillig": gkv_ist_freiwillig,
        "zu_verschieben": zu_verschieben,
        "nicht_verschiebbar": nicht_verschiebbar,
        "gesamt_ersparnis_pa": gesamt_ersparnis_pa,
        "gesamt_einmal_ersparnis": gesamt_einmal_ersparnis,
        "verbleibender_freibetrag_bav_mono": verbleibender_freibetrag,
        "kv_rate_voll": kv_rate_voll,
        "kv_rate_halb": kv_rate_halb,
    }


def _render_schenkungsanalyse(analyse: dict) -> None:
    """Rendert den Schenkungsanalyse-Abschnitt."""
    st.subheader("🎁 Schenkungspotenzial – Vertragsübertragung zur KV-Optimierung")
    gkv_kv_typ = (
        "freiwillig GKV (§ 240 SGB V)" if analyse["gkv_ist_freiwillig"]
        else "KVdR-Pflichtmitglied (§ 229 SGB V)"
    )
    st.caption(
        f"**{analyse['gkv_label']}** ist {gkv_kv_typ}. "
        f"**{analyse['pkv_label']}** ist PKV-versichert (fixer Beitrag). "
        "Eine Übertragung von Vorsorgeverträgen auf die PKV-Person kann KV-Beiträge dauerhaft reduzieren."
    )

    if not analyse["hat_empfehlung"]:
        if not analyse["gkv_ist_freiwillig"]:
            st.info(
                f"**{analyse['gkv_label']} ist KVdR-Pflichtmitglied.** "
                "Unter KVdR (§ 229 SGB V) sind nur betriebliche Versorgungsbezüge (bAV) KV-pflichtig – "
                "diese sind arbeitsrechtlich nicht übertragbar (§ 1 BetrAVG). "
                "Private Renten, Riester und ETF-Erträge sind unter KVdR nicht KV-pflichtig. "
                "Eine Vertragsschenkung bringt daher **keinen KV-Vorteil**."
            )
        elif not analyse["zu_verschieben"]:
            st.info(
                "Keine Verträge der GKV-Person erfasst. "
                "Im Tab **Vorsorge-Bausteine** Produkte anlegen."
            )
        else:
            st.info(
                "Die erfassten Verträge der GKV-Person haben kein berechenbares KV-Einsparpotenzial "
                "(keine monatliche Rente oder laufende Kapitalerträge erfasst)."
            )
        if analyse["nicht_verschiebbar"]:
            with st.expander(
                f"Nicht übertragbare Verträge ({len(analyse['nicht_verschiebbar'])})",
                expanded=False,
            ):
                df_nv = pd.DataFrame(analyse["nicht_verschiebbar"])[
                    ["Vertrag", "Typ", "KV-Kosten p.a. (ca.)", "Grund"]
                ]
                st.dataframe(df_nv.set_index("Vertrag"), use_container_width=True)
        return

    _kv_rate_str = f"{analyse['kv_rate_voll']:.1%}".replace(".", ",")
    _metrics: list[tuple[str, str, str]] = []
    if analyse["gesamt_ersparnis_pa"] > 0:
        _metrics.append((
            "KV-Ersparnis p.a. (ca.)",
            f"{_de(analyse['gesamt_ersparnis_pa'])} €",
            f"Jährliche KV-Ersparnis für laufende Renten bei Übertragung auf die PKV-Person. "
            f"KV-Gesamtsatz: {_kv_rate_str}",
        ))
    if analyse["gesamt_einmal_ersparnis"] > 0:
        _metrics.append((
            "KV-Ersparnis einmalig (ca.)",
            f"{_de(analyse['gesamt_einmal_ersparnis'])} €",
            f"Einmalige KV-Ersparnis aus Einmalauszahlungen bei Übertragung auf die PKV-Person. "
            f"KV-Gesamtsatz: {_kv_rate_str}",
        ))
    if not analyse["gkv_ist_freiwillig"] and analyse["verbleibender_freibetrag_bav_mono"] > 0:
        _metrics.append((
            "Verbleibender bAV-Freibetrag",
            f"{_de(analyse['verbleibender_freibetrag_bav_mono'])} €/Mon.",
            f"Ungenutzter bAV-Freibetrag (§ 226 Abs. 2 SGB V): {_de(BAV_FREIBETRAG_MONATLICH)} €/Mon. gesamt.",
        ))
    if _metrics:
        _m_cols = st.columns(max(len(_metrics), 2))
        for _i, (_lbl, _val, _hlp) in enumerate(_metrics):
            _m_cols[_i].metric(_lbl, _val, help=_hlp)

    if analyse["zu_verschieben"]:
        st.markdown(
            f"**Empfohlen – von {analyse['gkv_label']} auf {analyse['pkv_label']} übertragen:**"
        )
        df_v = pd.DataFrame(analyse["zu_verschieben"])[
            ["Vertrag", "Typ", "Von", "An", "KV-Ersparnis p.a. (ca.)", "Hinweis"]
        ]
        st.dataframe(df_v.set_index("Vertrag"), use_container_width=True)

    if analyse["nicht_verschiebbar"]:
        with st.expander(
            f"Nicht übertragbare Verträge ({len(analyse['nicht_verschiebbar'])})",
            expanded=False,
        ):
            df_nv = pd.DataFrame(analyse["nicht_verschiebbar"])[
                ["Vertrag", "Typ", "KV-Kosten p.a. (ca.)", "Grund"]
            ]
            st.dataframe(df_nv.set_index("Vertrag"), use_container_width=True)

    st.caption(
        "⚠️ **Rechtlicher Hinweis:** Schenkungen zwischen Eheleuten können den Freibetrag "
        "von 500.000 € (alle 10 Jahre, § 16 Abs. 1 Nr. 1 ErbStG) nutzen. "
        "Riester-Übertragungen nur zwischen förderberechtigten Eheleuten (§ 6 AltZertG). "
        "Die individuelle Umsetzung sollte mit einem Steuerberater abgestimmt werden."
    )


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

        _eo_solo     = eo_person in ("Person 1", "Person 2")
        _eo_solo_fak = 0.5 if _eo_solo else 1.0
        _miet_eo     = mieteinnahmen * _eo_solo_fak

        # ── Zeitstrahl (geteilt mit Dashboard / Haushalt / Simulation) ────────
        _eo_min_j = AKTUELLES_JAHR if not _profil_eo.bereits_rentner else _profil_eo.eintritt_jahr
        _eo_max_j = _profil_eo.eintritt_jahr + 40
        _eo_def_j = _profil_eo.eintritt_jahr
        _eo_sel_j_shared = render_zeitstrahl(
            _rc, _eo_min_j, _eo_max_j, _eo_def_j, "_eo",
            help_text="Wählt das Betrachtungsjahr für die Jahresdetails unten. Synchronisiert mit allen Tabs.",
        )

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
        _kv_hint = (
            "KVdR-Pflichtmitglied (§229 SGB V)" if _profil_eo.krankenversicherung == "GKV" and _profil_eo.kvdr_pflicht
            else "freiwillig GKV (§240 SGB V)" if _profil_eo.krankenversicherung == "GKV"
            else "PKV"
        )
        st.caption(f"Steuerliche und KV-Behandlung je Produkt auf einen Blick. KV-Status: {_kv_hint}.")
        df_stb = _steuer_steckbrief(produkte_dicts, _profil_eo,
                                    profil2=_profil2_eo if eo_person == "Zusammen" else None)
        st.dataframe(df_stb.set_index("Produkt"), use_container_width=True)

        st.divider()

        # ── Schenkungsanalyse (nur bei gemischter GKV/PKV-Konstellation) ────────
        if eo_person == "Zusammen" and hat_partner:
            _analyse = _analyse_schenkungspotenzial(
                produkte_dicts, profil, profil2, ergebnis, ergebnis2, mieteinnahmen)
            if _analyse is not None:
                _render_schenkungsanalyse(_analyse)
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
                _miete_label = "Mieteinnahmen (Basis)" + (" je 50 %" if _eo_solo and hat_partner else "")
                st.metric(_miete_label,
                          f"{_de(_miet_eo)} €/Mon.",
                          help=f"Steigen um {mietsteigerung:.1%}".replace(".", ",") +
                               " p.a. und erhöhen die Steuerprogression." +
                               (" Gesamtmieteinnahmen 50/50 aufgeteilt." if _eo_solo and hat_partner else ""))
        with oc3:
            if not _profil_eo.bereits_rentner:
                if _profil_eo.ist_pensionaer:
                    gehalt = 0.0
                elif eo_person == "Person 2":
                    gehalt = _profil_eo.aktuelles_brutto_monatlich
                else:
                    gehalt = float(st.session_state.get("opt_gehalt_mono", 0.0))
                st.metric("Bruttogehalt (aktiv)",
                          f"{_de(gehalt)} €/Mon." if gehalt > 0 else "–",
                          help="Im Tab ⚙️ Profil einstellbar. "
                               "Wird für Steuerprogression in Arbeitsjahren verwendet.")
            else:
                gehalt = 0.0

        # ── Kapital (Sparkapital bei Renteneintritt) ──────────────────────────
        _spkap_orig     = float(getattr(_profil_eo, "sparkapital", 0.0))
        _spkap_sparrate = float(getattr(_profil_eo, "sparrate", 0.0))
        _spkap_rendite  = float(getattr(_profil_eo, "rendite_pa", 0.05))
        _spkap_eintritt_j = (_profil_eo.rentenbeginn_jahr if _profil_eo.bereits_rentner
                             else _profil_eo.eintritt_jahr)
        _spkap = float(getattr(_ergebnis_eo, "kapital_bei_renteneintritt", 0.0))

        # ── Hypothek ──────────────────────────────────────────────────────────
        _hyp_info = get_hyp_info()
        _ausgaben_plan: dict[int, float] = {}
        _rs              = 0.0
        _behandlung      = "keine"
        _pool_tilgung    = False
        _anschluss_spar  = False
        _einmal_tilgung  = False
        _markt_zins_pa   = 0.04
        _anschluss_lz    = 10
        _ak_zeitleiste_rs        = 0.0
        _ak_zeitleiste_startjahr = 0
        _endmonat_hyp            = 12
        _spkap_pool_startjahr    = _spkap_eintritt_j
        _spkap_pool_wert         = _spkap
        _hyp_ezl: list[dict]     = []
        _endjahr_hyp             = AKTUELLES_JAHR
        _raten_aus_kapital       = False

        # Geplante Kapital-Entnahmen (aus session_state) – vor Hypothek laden,
        # damit die Sondertilgung im Endjahr die Anschlussfinanzierung reduziert.
        _eo_entnahmen_early: list[dict] = list(st.session_state.get("eo_entnahmen", []))
        _entnahmen_dict: dict[int, float] = {e["jahr"]: e["betrag"] for e in _eo_entnahmen_early}

        if _hyp_info:
            _ausgaben_plan = get_ausgaben_plan()
            _rs = get_restschuld_end()
            # Restliche Hypothek-Variablen aus hyp_daten lesen
            hyp_d = st.session_state.get("hyp_daten", {})
            _endjahr_hyp = int(hyp_d.get("endjahr", AKTUELLES_JAHR + 20))
            _endmonat_hyp = int(hyp_d.get("endmonat", 12))
            _markt_zins_pa = float(hyp_d.get("anschluss_zins_pa", 0.04))
            _anschluss_lz = int(hyp_d.get("anschluss_laufzeit", 10))
            _behandlung = str(hyp_d.get("restschuld_behandlung", "keine"))
            _hyp_ezl: list[dict] = list(hyp_d.get("sondertilgungen", []))
            if _behandlung == "einmalzahlungen":
                _hyp_ezl += list(hyp_d.get("anschluss_einmalzahlungen", []))
            _pool_tilgung = (_behandlung == "einmalzahlungen")
            _anschluss_spar = (_behandlung == "ratenkredit")
            _einmal_tilgung = (_behandlung == "einmalzahlungen")
            _raten_aus_kapital = bool(hyp_d.get("raten_in_simulation", False))
            _ak_zeitleiste_rs = _rs
            _ak_zeitleiste_startjahr = _endjahr_hyp if _endmonat_hyp < 12 else _endjahr_hyp + 1
            _spkap_pool_startjahr = _spkap_eintritt_j
            _spkap_pool_wert = _spkap

        # Geplante Entnahmen in Ausgabenplan einrechnen (aus Kapitalpool)
        for _entr_jr, _entr_btr in _entnahmen_dict.items():
            _ausgaben_plan[_entr_jr] = _ausgaben_plan.get(_entr_jr, 0.0) + _entr_btr

        # ── Optimierung ausführen ─────────────────────────────────────────────
        st.subheader("🔍 Optimale Auszahlungsstrategie")
        produkte_obj = [_aus_dict(p) for p in produkte_dicts]
        _produkte_obj_run   = list(produkte_obj)
        _produkte_dicts_run = list(produkte_dicts)
        _use_spar_pool = False  # Sparkapital wird ausschließlich in der Kapital-Zeitleiste dargestellt
        # ── Direkte Berechnung: alle Produkte Einmal ab frühestmöglich ──────────
        # Basis-Entscheidungen: jedes Produkt zum frühestmöglichen Zeitpunkt
        _base_entsch = [
            (prod, prod.fruehestes_startjahr, 1.0 if prod.max_einmalzahlung > 0 else 0.0)
            for prod in _produkte_obj_run
        ]
        # Früh/Spät-Selektion aus session_state anwenden
        _sels_key = f"rc{_rc}_hvp_sels"
        if _sels_key not in st.session_state:
            st.session_state[_sels_key] = {}
        _sels: dict[str, str | None] = dict(st.session_state[_sels_key])

        # Effektive Entscheidungen basierend auf Benutzer-Selektion
        _prod_name_map = {
            f"{p.name} ({p.typ})": p
            for p in _produkte_obj_run
            if p.id != "__sparkapital__"
            and p.max_einmalzahlung > 0
            and p.spaetestes_startjahr > p.fruehestes_startjahr
        }
        # Broader set: also products with both mono+einmal (no LV/ETF) for Einzelvergleich
        _ev_name_map = {
            f"{p.name} ({p.typ})": p
            for p in _produkte_obj_run
            if p.id != "__sparkapital__"
            and (
                (p.max_einmalzahlung > 0 and p.spaetestes_startjahr > p.fruehestes_startjahr)
                or (p.max_monatsrente > 0 and p.max_einmalzahlung > 0
                    and not p.ist_lebensversicherung and p.typ != "ETF")
            )
        }
        # Migration: alte Formate ("frueh","spaet","mono","fm","sm","fe","se") → Defaults neu setzen
        _OLD_SELS_FMTS = {"fm", "sm", "fe", "se", "frueh", "spaet", "mono"}
        _sels_is_old = bool(_sels) and any(v in _OLD_SELS_FMTS for v in _sels.values() if v is not None)

        # Default / Neusetzung: "YYYY_mono" wenn möglich, sonst "YYYY_einmal"
        if not _sels or _sels_is_old:
            _sels = {}
            for _nm_d, _p_d in _ev_name_map.items():
                _dm = "mono" if _p_d.max_monatsrente > 0 else "einmal"
                _sels[_nm_d] = f"{_p_d.fruehestes_startjahr}_{_dm}"
            st.session_state[_sels_key] = _sels
        else:
            # Initialize any new ev_name_map products not yet in _sels
            _sels_upd = False
            for _nm_ev, _p_ev in _ev_name_map.items():
                if _nm_ev not in _sels:
                    _dm_ev = "mono" if _p_ev.max_monatsrente > 0 else "einmal"
                    _sels[_nm_ev] = f"{_p_ev.fruehestes_startjahr}_{_dm_ev}"
                    _sels_upd = True
            if _sels_upd:
                st.session_state[_sels_key] = _sels

        # Parse year and mode from "YYYY_mono"/"YYYY_einmal"
        def _parse_sel(val) -> tuple[int | None, str]:
            if val is None:
                return None, "einmal"
            try:
                _parts = str(val).rsplit("_", 1)
                return int(_parts[0]), _parts[1] if len(_parts) > 1 else "einmal"
            except (ValueError, IndexError):
                return None, "einmal"

        _prod_sj_override: dict[str, int] = {}
        for _pn_sel, _sel_val in _sels.items():
            if _pn_sel not in _prod_name_map or _sel_val is None:
                continue
            _p_sel = _prod_name_map[_pn_sel]
            _j_sel, _ = _parse_sel(_sel_val)
            if _j_sel is not None:
                _prod_sj_override[_p_sel.id] = _j_sel

        # "_mono"-Selektion → anteil=0.0 (monatliche Auszahlung statt Pool-Injektion)
        _mono_prod_ids: set[str] = {
            _ev_name_map[_pn].id
            for _pn, _sv in _sels.items()
            if _sv is not None and str(_sv).endswith("_mono") and _pn in _ev_name_map
        }
        # Produkte, die in der Tabelle angezeigt werden (Einzel- oder Jahreswahl)
        _in_table_ids: set[str] = {p.id for p in _ev_name_map.values()}

        def _entsch_anteil(prod) -> float:
            """Anteil 0.0=mono, 1.0=einmal. Produkte ohne Tabelleneintrag nutzen natürlichen Modus."""
            if prod.id in _mono_prod_ids or prod.max_einmalzahlung == 0:
                return 0.0
            # In Tabelle, aber Nutzer wählte Einmal (nicht in _mono_prod_ids): Einmal
            if prod.id in _in_table_ids:
                return 1.0
            # Nicht in Tabelle (fixes Jahr o. nur Einmal): Mono bevorzugen wenn verfügbar
            if prod.max_monatsrente > 0:
                return 0.0
            return 1.0

        _eff_entsch = [
            (prod, _prod_sj_override.get(prod.id, prod.fruehestes_startjahr),
             _entsch_anteil(prod))
            for prod in _produkte_obj_run
        ]

        _eff_netto, _eff_jd_raw = _netto_ueber_horizont(
            _profil_eo, _ergebnis_eo, _eff_entsch, horizon,
            _miet_eo, mietsteigerung,
            profil2=_profil2_eo, ergebnis2=_ergebnis2_eo, veranlagung=_ver_eo,
            gehalt_monatlich=gehalt,
            ausgaben_plan=_ausgaben_plan if _ausgaben_plan else None,
        )
        st.session_state["_sb_eo_jd"] = _eff_jd_raw
        st.session_state["_sb_eo_person"] = eo_person

        # Referenz-Netto (alle früh) für Delta-Anzeige
        _any_spaet = any(
            _parse_sel(_sv)[0] is not None
            and _pn in _prod_name_map
            and _parse_sel(_sv)[0] > _prod_name_map[_pn].fruehestes_startjahr
            for _pn, _sv in _sels.items()
            if _sv is not None
        )
        _base_netto: float | None = None
        if _any_spaet:
            _base_netto, _ = _netto_ueber_horizont(
                _profil_eo, _ergebnis_eo, _base_entsch, horizon,
                _miet_eo, mietsteigerung,
                profil2=_profil2_eo, ergebnis2=_ergebnis2_eo, veranlagung=_ver_eo,
                gehalt_monatlich=gehalt,
                ausgaben_plan=_ausgaben_plan if _ausgaben_plan else None,
            )

        # ── Kennzahlen ────────────────────────────────────────────────────────
        _df_kc = pd.DataFrame(_eff_jd_raw)
        _netto_arbeit = _df_kc.loc[_df_kc.get("Src_Gehalt", pd.Series(0, index=_df_kc.index)) > 0, "Netto"].sum() if "Src_Gehalt" in _df_kc.columns else 0
        _netto_rente  = _df_kc.loc[_df_kc.get("Src_Gehalt", pd.Series(0, index=_df_kc.index)) == 0, "Netto"].sum() if "Src_Gehalt" in _df_kc.columns else _eff_netto

        if _netto_arbeit > 0:
            kc1, kc2, kc3 = st.columns(3)
            kc1.metric("Netto Arbeitsphase", f"{_de(_netto_arbeit)} €",
                       help="Summe Netto-Jahreseinkommen in aktiven Berufsjahren.")
            kc2.metric("Netto Rentenphase", f"{_de(_netto_rente)} €",
                       help=f"Summe Netto-Jahreseinkommen in {horizon} Rentenjahren.")
            kc3.metric("Netto gesamt", f"{_de(_eff_netto)} €")
        else:
            kc1, kc2 = st.columns(2)
            kc1.metric("Netto gesamt", f"{_de(_eff_netto)} €",
                       help=f"Summe aller Netto-Jahreseinkommen über {horizon} Jahre.")
            if _base_netto is not None:
                _delta_spaet = _eff_netto - _base_netto
                _sign = "+" if _delta_spaet >= 0 else ""
                kc2.metric("Δ vs. alle früh",
                           f"{_sign}{_de(_delta_spaet)} €",
                           delta_color="normal",
                           help="Unterschied gegenüber Szenario 'alle Produkte frühestmöglich'.")

        if _any_spaet and _base_netto is not None:
            _delta_ov = _eff_netto - _base_netto
            _sign = "+" if _delta_ov >= 0 else ""
            st.info(
                f"🔄 **Spät-Auszahlung aktiv** · "
                f"Netto-Gesamt: **{_de(_eff_netto)} €** · "
                f"Δ vs. alle früh: {_sign}{_de(_delta_ov)} €"
            )

        # ── Anschlusskredit-Kennzahlen ────────────────────────────────────────
        # Effektive Restschuld: bei Sondertilgungen bereits um EZ reduziert
        _eff_ak_rs = 0.0
        if _hyp_info and _behandlung == "ratenkredit":
            _eff_ak_rs = _rs
        elif _hyp_info and _behandlung == "einmalzahlungen":
            _eff_ak_rs = _ak_zeitleiste_rs  # nach Sondertilgungen
        if _hyp_info and _eff_ak_rs > 0:
            _ak_rate_j = _annuitaet_rate(_eff_ak_rs, _markt_zins_pa, _anschluss_lz)
            _ak_gesamt = _ak_rate_j * _anschluss_lz
            _ak_zinsen = _ak_gesamt - _eff_ak_rs
            _akc1, _akc2, _akc3, _akc4 = st.columns(4)
            _akc1.metric("Kreditsumme", f"{_de(_eff_ak_rs)} €",
                         help="Verbleibende Restschuld" + (" nach Sondertilgungen." if _behandlung == "einmalzahlungen" else " der Primärhypothek."))
            _akc2.metric("Jahresrate", f"{_de(_ak_rate_j)} €",
                         help=f"{_de(_ak_rate_j / 12, 0)} €/Mon. · Nominalzins {_markt_zins_pa * 100:.2f} %")
            _akc3.metric("Laufzeit", f"{_anschluss_lz} Jahre",
                         help=f"Ab {_ak_zeitleiste_startjahr} bis {_ak_zeitleiste_startjahr + _anschluss_lz - 1}")
            _akc4.metric("Gesamtzinsen", f"{_de(_ak_zinsen)} €",
                         help=f"Gesamtbelastung {_de(_ak_gesamt)} €")
            _ak_sm = _endmonat_hyp + 1 if _endmonat_hyp < 12 else 1
            _ak_sy = _endjahr_hyp if _endmonat_hyp < 12 else _endjahr_hyp + 1
            _monate_de = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun",
                          "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]
            _ak_start_str = f"{_monate_de[_ak_sm - 1]} {_ak_sy}"
            _prim_end_str = f"{_monate_de[_endmonat_hyp - 1]} {_endjahr_hyp}"
            st.caption(
                f"Primärhypothek endet: **{_prim_end_str}** (Endmonat {_endmonat_hyp}) · "
                f"Anschlusskredit startet: **{_ak_start_str}** · "
                f"Endmonat falsch? → Hypothek-Verwaltung öffnen und erneut speichern."
            )

        # ── Einzelvergleich bei flexiblen Verträgen ──────────────────────────
        _LABELS_EV = {
            "einmal": "Einmalauszahlung",
            "monatlich": "Monatliche Rente",
            "kombiniert": "Kombiniert (Kapital + Rente)",
        }
        if _ev_name_map:
            with st.expander("📋 Empfehlungen zur Auszahlung von Vorsorgeverträgen in den Kapitalpool", expanded=True):
                st.caption(
                    "Vergleich Einmal- vs. Monatsrente und ggf. Aufschubzeitpunkt. "
                    "Netto früh/spät, Beitragsersparnis und Break-Even p.a. nur bei Produkten "
                    "mit flexiblem Auszahlungsjahr (Früh ≠ Spät)."
                )

                # 4 extra columns for year-flex products
                _yf_rows_ev: dict[str, dict] = {}
                _ak_zinsen_g_ev = 0.0
                if _eff_ak_rs > 0:
                    _ak_zinsen_g_ev = (_annuitaet_rate(_eff_ak_rs, _markt_zins_pa, _anschluss_lz)
                                       * _anschluss_lz - _eff_ak_rs)
                for _hp in _produkte_obj_run:
                    if (_hp.id == "__sparkapital__"
                            or _hp.max_einmalzahlung == 0
                            or _hp.spaetestes_startjahr <= _hp.fruehestes_startjahr):
                        continue
                    _F = _hp.fruehestes_startjahr
                    _S = _hp.spaetestes_startjahr
                    _n = _S - _F
                    _aufsch_r = max(0.0, _hp.aufschub_rendite)
                    _V_F = _hp.max_einmalzahlung
                    _V_S = _V_F * (1.0 + _aufsch_r) ** _n
                    _eff_tax_hp = (0.175 if (_hp.typ == "ETF"
                                             and not getattr(_hp, "etf_ausschuettend", False))
                                   else 0.25)
                    _einz_F_hp = _hp.einzahlungen_effektiv(_F)
                    _einz_S_hp = _hp.einzahlungen_effektiv(_S)
                    _V_F_net_hp = _V_F - max(0.0, _V_F - _einz_F_hp) * _eff_tax_hp
                    _V_S_net_hp = _V_S - max(0.0, _V_S - _einz_S_hp) * _eff_tax_hp
                    _beitr_hp = (
                        sum(
                            _hp.jaehrl_einzahlung * (1.0 + _hp.jaehrl_dynamik) ** max(0, j - AKTUELLES_JAHR)
                            for j in range(_F, _S)
                        ) if _hp.jaehrl_einzahlung > 0 else 0.0
                    )
                    if _n > 0 and _V_F > 0:
                        _be_n = _V_F_net_hp - _einz_S_hp * _eff_tax_hp + _ak_zinsen_g_ev + _beitr_hp
                        _be_d = _V_F * (1.0 - _eff_tax_hp)
                        _be_str_hp = (
                            f"{((_be_n / _be_d) ** (1.0 / _n) - 1.0) * 100:.2f} %"
                            if _be_n > 0 and _be_d > 0 else "–"
                        )
                    else:
                        _be_str_hp = "–"
                    _yf_rows_ev[f"{_hp.name} ({_hp.typ})"] = {
                        "Netto früh (€)":        _de(_V_F_net_hp),
                        "Netto spät (€)":        _de(_V_S_net_hp),
                        "Beitragsersparnis (€)": _de(_beitr_hp),
                        "Break-Even p.a.":       _be_str_hp,
                    }

                # Build table rows using vergleiche_produkt
                _rendite_ev = _profil_eo.rendite_pa
                _ev_opt_timing: dict[str, int] = {
                    prod.name: sj for prod, sj, _ in _eff_entsch
                }
                _ev_rows: list[tuple] = []
                for _pd_dict in produkte_dicts:
                    _p = _aus_dict(_pd_dict)
                    if _p.id == "__sparkapital__":
                        continue
                    _ist_lv = _p.ist_lebensversicherung
                    _hat_mono = _p.max_monatsrente > 0 and not _ist_lv and _p.typ != "ETF"
                    _hat_einz = _p.max_einmalzahlung > 0 and not _p.ist_nur_monatsrente
                    _hat_spaet = _p.spaetestes_startjahr > _p.fruehestes_startjahr
                    _pname_ev = f"{_p.name} ({_p.typ})"
                    if _pname_ev not in _ev_name_map:
                        continue
                    _v = vergleiche_produkt(_p, _rendite_ev, horizon)
                    _bestes = _v["bestes"]
                    _opt_j = _ev_opt_timing.get(_p.name, _p.fruehestes_startjahr)
                    if _p.fruehestes_startjahr == _p.spaetestes_startjahr:
                        _zeitpunkt = f"fixes Jahr ({_p.fruehestes_startjahr})"
                    elif _opt_j <= _p.fruehestes_startjahr:
                        _zeitpunkt = "frühestmöglich"
                    elif _opt_j >= _p.spaetestes_startjahr:
                        _zeitpunkt = "spätestmöglich"
                    else:
                        _zeitpunkt = f"ab {_opt_j} (+{_opt_j - _p.fruehestes_startjahr} J. Aufschub)"
                    _empf = f"{_LABELS_EV[_bestes]}, {_zeitpunkt}"
                    if _hat_mono and _hat_einz:
                        _bx = _v["kombiniert"]["anteil"]
                        _eff_lz = min(_p.laufzeit_jahre if _p.laufzeit_jahre > 0 else horizon, horizon)
                        _t_komb_r = _p.max_einmalzahlung * _bx + _p.max_monatsrente * (1 - _bx) * 12 * _eff_lz
                        _t_mono_r = _v["monatlich"]["total"]
                        if _t_mono_r >= _t_komb_r:
                            _t_komb = _t_mono_r
                            _m_komb = _v["monatlich"]["monatlich"]
                        else:
                            _t_komb = _t_komb_r
                            _m_komb = _t_komb_r / (horizon * 12) if horizon > 0 else 0.0
                        _komb_fmt = f"{_de(_t_komb)} € / {_de(_m_komb)} €"
                    else:
                        _komb_fmt = "–"
                    _sel_ev = _sels.get(_pname_ev)
                    _yr_ev, _mode_ev = _parse_sel(_sel_ev)
                    _yr_val_ev = _yr_ev if _yr_ev is not None else _p.fruehestes_startjahr
                    # Startmonat des gewählten Jahres für anteilige Berechnung im ersten Auszahlungsjahr
                    _sm_ev = (
                        int(_pd_dict.get("spaetestes_startmonat", 12)) if _yr_val_ev >= _p.spaetestes_startjahr
                        else int(_pd_dict.get("fruehestes_startmonat", 1)) if _yr_val_ev <= _p.fruehestes_startjahr
                        else 1
                    )
                    _auzz_fak_ev = (13 - _sm_ev) / 12
                    _eff_lz_ev = min(_p.laufzeit_jahre if _p.laufzeit_jahre > 0 else horizon, horizon)
                    _t_mono_prorated = _p.max_monatsrente * 12 * (_eff_lz_ev - 1 + _auzz_fak_ev)
                    _be_y_ev = (_p.max_einmalzahlung / (_p.max_monatsrente * 12)
                                if _hat_mono and _hat_einz and _p.max_monatsrente > 0 else None)
                    _yf = _yf_rows_ev.get(_pname_ev, {})
                    _row_ev: dict = {
                        "Typ":                       _pd_dict["typ_label"],
                        "Person":                    _p.person,
                        "Einmal (Total / Mon.)":      (
                            f"{_de(_p.max_einmalzahlung)} € / "
                            f"{_de(_p.max_einmalzahlung / (horizon * 12) if horizon > 0 else 0)} €"
                            if _hat_einz else "–"
                        ),
                        "Monatlich (Total / Mon.)":  (
                            f"{_de(_t_mono_prorated)} € / "
                            f"{_de(_v['monatlich']['monatlich'])} €"
                            if _hat_mono else "–"
                        ),
                        "Kombiniert (Total / Mon.)": _komb_fmt,
                        "Monatl. > Einmal ab":       (
                            str(int(_yr_val_ev) + math.ceil(_be_y_ev))
                            if _be_y_ev is not None else "–"
                        ),
                        "Einfach-Empfehlung ✅":     _empf,
                        "Früh":                      _p.fruehestes_startjahr,
                        "Spät":                      _p.spaetestes_startjahr,
                        "Endmonat":                  _MON_KURZ[int(_pd_dict.get("spaetestes_startmonat", 12)) - 1],
                        "Auszahlungsjahr":           int(_yr_val_ev),
                        "Netto früh (€)":            _yf.get("Netto früh (€)", "–"),
                        "Netto spät (€)":            _yf.get("Netto spät (€)", "–"),
                        "Beitragsersparnis (€)":     _yf.get("Beitragsersparnis (€)", "–"),
                        "Break-Even p.a.":           _yf.get("Break-Even p.a.", "–"),
                        "_has_yr":                   _hat_spaet,
                    }
                    if _hat_mono and _hat_einz:
                        _row_ev["Montl. Auszahlung"] = bool(_mode_ev == "mono")
                    _ev_rows.append((_pname_ev, _row_ev, _hat_mono and _hat_einz, _hat_spaet))

                _ev_rows_both_yr    = [(n, r) for n, r, hb, hy in _ev_rows if hb and hy]
                _ev_rows_both_no_yr = [(n, r) for n, r, hb, hy in _ev_rows if hb and not hy]
                _ev_rows_single     = [(n, r) for n, r, hb, hy in _ev_rows if not hb]

                _INFO_COLS_EV = [
                    "Typ", "Person", "Einmal (Total / Mon.)", "Monatlich (Total / Mon.)",
                    "Kombiniert (Total / Mon.)", "Monatl. > Einmal ab", "Einfach-Empfehlung ✅",
                ]
                _YF_COLS_EV = ["Netto früh (€)", "Netto spät (€)", "Beitragsersparnis (€)", "Break-Even p.a."]
                _EV_SELS_TAG = "_".join(
                    f"{i}{str(v or 'n')[:4]}"
                    for i, (_, v) in enumerate(sorted(_sels.items()))
                ) or "0"

                _col_cfg_ev: dict = {c: st.column_config.TextColumn(c) for c in _INFO_COLS_EV}
                _col_cfg_ev["Einmal (Total / Mon.)"] = st.column_config.TextColumn(
                    "Einmal (Total / Mon.)",
                    help="Einmalauszahlung: Total = vertraglicher Betrag. Mon. = Ø/Monat über Horizont.",
                )
                _col_cfg_ev["Monatlich (Total / Mon.)"] = st.column_config.TextColumn(
                    "Monatlich (Total / Mon.)",
                    help="Monatliche Rente: Total = Summe über Horizont. Mon. = Monatsbetrag.",
                )
                _col_cfg_ev["Kombiniert (Total / Mon.)"] = st.column_config.TextColumn(
                    "Kombiniert (Total / Mon.)",
                    help="Optimaler Mix aus Einmal und Rente: Total und Ø-Monatswert.",
                )
                _col_cfg_ev["Monatl. > Einmal ab"] = st.column_config.TextColumn(
                    "Monatl. > Einmal ab",
                    help="Kalenderjahr, ab dem kumulierte Monatszahlungen die Einmalauszahlung übersteigen.",
                )
                _col_cfg_ev["Früh"] = st.column_config.NumberColumn("Früh", format="%d",
                    help="Frühestmögliches Auszahlungsjahr.")
                _col_cfg_ev["Spät"] = st.column_config.NumberColumn("Spät", format="%d",
                    help="Spätestmögliches Auszahlungsjahr.")
                _col_cfg_ev["Endmonat"] = st.column_config.TextColumn(
                    "Endmonat", help="Monat im Spätesten Startjahr (aus dem Vorsorgevertrag).")
                _col_cfg_ev["Auszahlungsjahr"] = st.column_config.NumberColumn(
                    "Auszahlungsjahr", min_value=2020, max_value=2099, step=1, format="%d",
                    help="Auszahlungsjahr – muss zwischen Früh und Spät liegen.",
                )
                _col_cfg_ev["Netto früh (€)"] = st.column_config.TextColumn(
                    "Netto früh (€)", help="Netto-Auszahlungsbetrag im Früh-Jahr nach vereinfachter Steuer.")
                _col_cfg_ev["Netto spät (€)"] = st.column_config.TextColumn(
                    "Netto spät (€)", help="Netto-Auszahlungsbetrag im Spät-Jahr nach Steuer inkl. Aufschub-Rendite.")
                _col_cfg_ev["Beitragsersparnis (€)"] = st.column_config.TextColumn(
                    "Beitragsersparnis (€)", help="Eingesparte laufende Einzahlungen zwischen Früh- und Spät-Jahr.")
                _col_cfg_ev["Break-Even p.a."] = st.column_config.TextColumn(
                    "Break-Even p.a.", help="Mindestrendite p.a., ab der Investiert-Bleiben bis Spät-Jahr rentabler ist.")
                _col_cfg_ev["_has_yr"] = None

                _col_cfg_ev_both = dict(_col_cfg_ev)
                _col_cfg_ev_both["Montl. Auszahlung"] = st.column_config.CheckboxColumn(
                    "Montl. Auszahlung",
                    help="Monatliche Rente (☑) oder Einmalauszahlung (☐).",
                )

                _dis_ev = _INFO_COLS_EV + _YF_COLS_EV + ["Früh", "Spät", "Endmonat"]
                _dis_ev_fixed_yr = _dis_ev + ["Auszahlungsjahr"]
                _edited_ev_both = _edited_ev_both_no_yr = _edited_ev_single = None

                if _ev_rows_both_yr:
                    _df_ev_both = pd.DataFrame(
                        [r for _, r in _ev_rows_both_yr],
                        index=[n for n, _ in _ev_rows_both_yr],
                    )
                    _edited_ev_both = st.data_editor(
                        _df_ev_both, column_config=_col_cfg_ev_both, disabled=_dis_ev,
                        key=f"rc{_rc}_ev_edit_both_{_EV_SELS_TAG}",
                        use_container_width=True,
                    )
                if _ev_rows_both_no_yr:
                    if _ev_rows_both_yr:
                        st.caption("Verträge mit Einmal- & Monatsrenten-Option, fixes Auszahlungsjahr:")
                    _df_ev_both_no_yr = pd.DataFrame(
                        [r for _, r in _ev_rows_both_no_yr],
                        index=[n for n, _ in _ev_rows_both_no_yr],
                    )
                    _edited_ev_both_no_yr = st.data_editor(
                        _df_ev_both_no_yr, column_config=_col_cfg_ev_both, disabled=_dis_ev_fixed_yr,
                        key=f"rc{_rc}_ev_edit_both_nyr_{_EV_SELS_TAG}",
                        use_container_width=True,
                    )
                if _ev_rows_single:
                    if _ev_rows_both_yr or _ev_rows_both_no_yr:
                        st.caption("Verträge mit fester Auszahlungsart:")
                    _df_ev_single = pd.DataFrame(
                        [r for _, r in _ev_rows_single],
                        index=[n for n, _ in _ev_rows_single],
                    )
                    _edited_ev_single = st.data_editor(
                        _df_ev_single, column_config=_col_cfg_ev, disabled=_dis_ev,
                        key=f"rc{_rc}_ev_edit_single_{_EV_SELS_TAG}",
                        use_container_width=True,
                    )

                st.caption(
                    "Auszahlungsjahr und Modus wählen. Montl.-Checkbox nur bei Verträgen mit beiden "
                    "Auszahlungsoptionen. Netto früh/spät und Break-Even nur bei flexiblem Auszahlungsjahr."
                )

                _new_sels: dict[str, str | None] = {}

                def _process_ev_editor(edited_df, has_cb: bool) -> None:
                    if edited_df is None:
                        return
                    for _pn_e, _row_e in edited_df.iterrows():
                        _pn_e = str(_pn_e)
                        _po_e = _ev_name_map.get(_pn_e)
                        if _po_e is None:
                            continue
                        _frueh_e = _po_e.fruehestes_startjahr
                        _spaet_e = _po_e.spaetestes_startjahr
                        _raw_yr_e = _row_e.get("Auszahlungsjahr")
                        _new_yr_e = int(_raw_yr_e) if _raw_yr_e is not None else _frueh_e
                        if _new_yr_e < _frueh_e or _new_yr_e > _spaet_e:
                            st.warning(
                                f"Auszahlungsjahr {_new_yr_e} für «{_pn_e}» liegt außerhalb "
                                f"[{_frueh_e}, {_spaet_e}] – auf {_frueh_e} gesetzt."
                            )
                            _new_yr_e = max(_frueh_e, min(_spaet_e, _new_yr_e))
                        if has_cb:
                            _new_montl_e = bool(_row_e.get("Montl. Auszahlung", False))
                        else:
                            _new_montl_e = _po_e.max_monatsrente > 0
                        _new_sels[_pn_e] = f"{_new_yr_e}_{'mono' if _new_montl_e else 'einmal'}"

                _process_ev_editor(_edited_ev_both, has_cb=True)
                _process_ev_editor(_edited_ev_both_no_yr, has_cb=True)
                _process_ev_editor(_edited_ev_single, has_cb=False)
                for _pn_fix, _sv_fix in _sels.items():
                    if _pn_fix not in _new_sels:
                        _new_sels[_pn_fix] = _sv_fix

                if _new_sels != _sels:
                    st.session_state[_sels_key] = _new_sels
                    # Sync → vp_sels (ID-keyed) damit Dashboard/Haushalt/Simulation/Vorsorge
                    # sofort die geänderten Auszahlungseinstellungen übernehmen.
                    _vp_sels_upd = dict(st.session_state.get(f"rc{_rc}_vp_sels", {}))
                    for _pn_s, _sv_s in _new_sels.items():
                        _prod_s = _ev_name_map.get(_pn_s)
                        if _prod_s is not None and _sv_s is not None:
                            _vp_sels_upd[_prod_s.id] = _sv_s
                    st.session_state[f"rc{_rc}_vp_sels"] = _vp_sels_upd
                    st.rerun()

        # ── Frühe Definitionen für Empfehlung-von-Entnahmen-Block ────────────
        df_jd = pd.DataFrame(_eff_jd_raw).set_index("Jahr")
        _has_pool_data = (
            "Kap_Injektion" in df_jd.columns and df_jd["Kap_Injektion"].sum() > 0
        )
        _mindest_mono = int(st.session_state.get("mindest_haushalt_mono", 0) * _eo_solo_fak)
        _mindest_j_topup = _mindest_mono * 12
        _manual_w_key = "pool_topup_withdrawals"
        _manual_withdrawals: dict[int, float] = dict(st.session_state.get(_manual_w_key, {}))

        # ── Empfehlungen von Entnahmen direkt nach Empfehlungen zur Auszahlung ─
        with st.expander("💰 Empfehlungen von Entnahmen aus dem Kapitalpool zur Aufstockung des Nettogehaltes", expanded=(_mindest_j_topup > 0 and _has_pool_data)):
            if _mindest_mono == 0:
                st.info("Bitte Mindesthaushaltsbetrag im Tab 👥 Haushalt → Mindesthaushaltsbetrag festlegen.")
            elif not _has_pool_data:
                st.info("Kein Kapitalpool aktiv. Aktiviere 'In Kapitalpool einzahlen' für mindestens ein Vorsorgeprodukt im Tab 🏦 Vorsorge-Bausteine.")
            else:
                st.caption(
                    f"Mindesthaushaltsbetrag: **{_de(_mindest_mono)} €/Mon.** = **{_de(_mindest_j_topup)} €/Jahr**. "
                    "Trage gewünschte Entnahmen aus dem Kapitalpool ein. "
                    "Positive Abweichung (grün) = Ziel erreicht, negative (rot) = Nachsteuerung nötig."
                )
                _pool_rendite = getattr(_profil_eo, "kap_pool_rendite_pa", -1.0)
                if _pool_rendite < 0:
                    _pool_rendite = getattr(_profil_eo, "rendite_pa", 0.03)
                _topup_rows_eo = []
                _pool_bal_eo = 0.0
                _monatl_kap_eo = float(getattr(_ergebnis_eo, "kapital_monatlich", 0.0))
                for _tj in sorted(df_jd.index):
                    _inj_eo = float(df_jd.loc[_tj, "Kap_Injektion"]) if "Kap_Injektion" in df_jd.columns else 0.0
                    _pool_bal_eo = (_pool_bal_eo * (1 + _pool_rendite)) + _inj_eo
                    _netto_j_eo = float(df_jd.loc[_tj, "Netto"]) if "Netto" in df_jd.columns else 0.0
                    _auto_annuity_eo = float(df_jd.loc[_tj, "Src_Kapitalverzehr"]) if "Src_Kapitalverzehr" in df_jd.columns else 0.0
                    # Kap_Sonder_Tilgung: the share of Sonderausgabe (hypothek) covered by pool.
                    # Netto already has the uncovered residual deducted; subtracting kap_sonder
                    # (instead of the full ausgaben_plan amount) avoids double-counting.
                    _kap_sonder_eo = float(df_jd.loc[_tj, "Kap_Sonder_Tilgung"]) if "Kap_Sonder_Tilgung" in df_jd.columns else 0.0
                    _base_netto_eo = _netto_j_eo - _auto_annuity_eo - _kap_sonder_eo - _mindest_j_topup
                    _manual_w_eo = _manual_withdrawals.get(_tj, 0.0)
                    _pool_bal_eo = max(0.0, _pool_bal_eo - _manual_w_eo)
                    # Sparkapital-Bestand (aus Profil): dieselbe Formel wie Kapital-Zeitleiste
                    _spar_bal_eo = 0.0
                    if _spkap_orig > 0:
                        if _tj < _spkap_eintritt_j and not _profil_eo.bereits_rentner:
                            _spar_bal_eo = kapitalwachstum(
                                _spkap_orig, _spkap_sparrate, _spkap_rendite,
                                max(0, _tj - AKTUELLES_JAHR),
                            )
                        elif _tj >= _spkap_eintritt_j:
                            _spar_bal_eo = max(0.0, kapitalwachstum(
                                _spkap, -_monatl_kap_eo, _spkap_rendite,
                                max(0, _tj - _spkap_eintritt_j),
                            ))
                    _abw_val = round(_base_netto_eo + _manual_w_eo)
                    _abw_str = (f"🔴 {_de(_abw_val)}" if _abw_val < 0
                                else f"🟢 {_de(_abw_val)}")
                    _topup_rows_eo.append({
                        "Jahr": _tj,
                        "Entnahme aus Pool (€)": _manual_w_eo if _manual_w_eo > 0 else None,
                        "Frei nach Ausg.+Hyp. (€)": round(_base_netto_eo),
                        "Mindesthaushalt (€/Jahr)": _mindest_j_topup,
                        "Abweichung": _abw_str,
                        "Pool-Bestand (€)": round(_pool_bal_eo + _spar_bal_eo),
                    })
                _topup_df_eo = pd.DataFrame(_topup_rows_eo)

                _tu_ver_eo = sum(int(j) * 1000 + int(_manual_withdrawals.get(j, 0)) for j in sorted(df_jd.index))
                _edited_tu_eo = st.data_editor(
                    _topup_df_eo,
                    use_container_width=True,
                    hide_index=True,
                    key=f"rc{_rc}_topup_editor_eo_{_tu_ver_eo}",
                    disabled=["Jahr", "Frei nach Ausg.+Hyp. (€)", "Mindesthaushalt (€/Jahr)", "Abweichung", "Pool-Bestand (€)"],
                    column_config={
                        "Jahr": st.column_config.NumberColumn("Jahr", format="%d"),
                        "Entnahme aus Pool (€)": st.column_config.NumberColumn(
                            "Entnahme aus Pool (€)", min_value=0.0, max_value=5_000_000.0,
                            format="%.0f", step=1_000.0,
                            help="Gewünschte manuelle Entnahme aus dem Kapitalpool in diesem Jahr.",
                        ),
                        "Frei nach Ausg.+Hyp. (€)": st.column_config.NumberColumn(
                            "Frei nach Ausg.+Hyp. (€)", format="%.0f",
                            help="Basiseinkommen − volle Hypothekenrate − Mindesthaushalt. Entspricht der gelben Linie im Diagramm. (Pool-Entnahmen sind nicht enthalten — separat in 'Entnahme aus Pool' erfassbar.)",
                        ),
                        "Mindesthaushalt (€/Jahr)": st.column_config.NumberColumn("Mindesthaushalt (€/Jahr)", format="%.0f"),
                        "Abweichung": st.column_config.TextColumn("Abweichung",
                            help="Frei nach Ausg.+Hyp. + Pool-Entnahme. 🟢 = Mindesthaushalt erreicht; 🔴 = Unterdeckung."),
                        "Pool-Bestand (€)": st.column_config.NumberColumn("Pool-Bestand (€)", format="%.0f"),
                    },
                )
                _new_mw_eo: dict[int, float] = {}
                for _, _tu_row_eo in _edited_tu_eo.iterrows():
                    _j_tu_eo = int(_tu_row_eo["Jahr"])
                    _w_tu_eo = _tu_row_eo.get("Entnahme aus Pool (€)")
                    if pd.notna(_w_tu_eo) and float(_w_tu_eo) > 0:
                        _new_mw_eo[_j_tu_eo] = float(_w_tu_eo)
                if _new_mw_eo != _manual_withdrawals:
                    st.session_state[_manual_w_key] = _new_mw_eo
                    st.rerun()

        # ── Hypothek-Jahresraten als aufklappbare Infobox ─────────────────────
        if _ausgaben_plan and _hyp_info:
            _prim_sched_yrs_exp = {s["Jahr"] for s in get_hyp_schedule()}
            _rate_jahre_exp = sorted(yr for yr in _ausgaben_plan if yr in _prim_sched_yrs_exp)
            if _rate_jahre_exp:
                with st.expander("📋 Hypothek-Jahresraten – Quelle: 🔵 Kapital / 🔴 Einkommen", expanded=False):
                    _spar_col_jd_exp = "Kap_Pool___sparkapital__"
                    _rate_rows_exp = []
                    for _rj in _rate_jahre_exp:
                        _rate_exp = _ausgaben_plan[_rj]
                        if _raten_aus_kapital:
                            if _spar_col_jd_exp in df_jd.columns and _rj in df_jd.index:
                                _kap_avail_exp = float(df_jd.loc[_rj, _spar_col_jd_exp])
                            else:
                                _kap_avail_exp = kapitalwachstum(
                                    _spkap_orig, _spkap_sparrate, _spkap_rendite,
                                    max(0, _rj - AKTUELLES_JAHR),
                                )
                            _aus_kapital_exp = _kap_avail_exp >= _rate_exp
                        else:
                            _kap_avail_exp = 0.0
                            _aus_kapital_exp = False
                        _rate_rows_exp.append({
                            "Jahr": _rj,
                            "Jahresrate (€)": f"{_rate_exp:,.0f}".replace(",", "."),
                            "Kapital verfügbar (€)": f"{_kap_avail_exp:,.0f}".replace(",", ".") if _raten_aus_kapital else "–",
                            "Quelle": "Kapital" if _aus_kapital_exp else "Einkommen",
                        })
                    _df_rates_exp = pd.DataFrame(_rate_rows_exp).set_index("Jahr")

                    def _color_rows_exp(row: "pd.Series") -> list[str]:
                        if row["Quelle"] == "Kapital":
                            return ["background-color: #BBDEFB"] * len(row)
                        return ["background-color: #FFCDD2"] * len(row)

                    st.dataframe(
                        _df_rates_exp.style.apply(_color_rows_exp, axis=1),
                        use_container_width=True,
                    )

        st.divider()

        # ── Steuer- und KV-Verlauf ────────────────────────────────────────────
        st.subheader("Steuer- und KV-Verlauf")
        fig_tax = go.Figure()
        # ESt + Soli + KiSt = Steuer minus Abgeltungsteuer (Steuer_Progressiv enthält kein Soli)
        _abgelt_series = df_jd["Steuer_Abgeltung"] if "Steuer_Abgeltung" in df_jd.columns else pd.Series(0, index=df_jd.index)
        _est_soli_series = df_jd["Steuer"] - _abgelt_series
        _hat_prog = "Steuer_Progressiv" in df_jd.columns
        _est_soli_custom = []
        for _yr_tax, _row_tax in df_jd.iterrows():
            _yr_int = int(_yr_tax)
            _zve_val = int(_row_tax.get("zvE", 0))
            _est_soli_val = float(_est_soli_series.loc[_yr_tax])
            _est_prog = int(_row_tax.get("Steuer_Progressiv", 0)) if _hat_prog else 0
            _soli_val = max(0, int(_est_soli_val) - _est_prog)
            _parts_es = [f"<b>{_yr_int} – Einkommensteuer + Soli</b>",
                         f"zvE: {_de(_zve_val)} €/Jahr"]
            if _ver_eo == "Zusammen" and _profil2_eo:
                _parts_es.append(f"Splitting (§ 32a Abs. 5 EStG): 2 × ESt(zvE/2)")
            if _hat_prog:
                _parts_es.append(f"ESt (§ 32a EStG): {_de(_est_prog)} €/Jahr")
                if _soli_val > 0:
                    _parts_es.append(f"Soli (§ 51a EStG): {_de(_soli_val)} €/Jahr")
            _parts_es.append(f"ESt + Soli: {_de(int(_est_soli_val))} €/Jahr · {_de(int(_est_soli_val / 12))} €/Mon.")
            _est_soli_custom.append("<br>".join(_parts_es))
        fig_tax.add_trace(go.Bar(
            name="ESt + Soli", x=df_jd.index, y=_est_soli_series,
            marker_color="#EF9A9A",
            customdata=_est_soli_custom,
            hovertemplate="%{customdata}<extra></extra>",
        ))
        if "Steuer_Abgeltung" in df_jd.columns and df_jd["Steuer_Abgeltung"].sum() > 0:
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
            _kv_custom_solo = []
            for _yr_kv, _row_kv in df_jd.iterrows():
                _kv_val = int(_row_kv.get("KV_PV", 0))
                _in_rente_yr = _profil_eo.bereits_rentner or int(_yr_kv) >= _profil_eo.eintritt_jahr
                if not _in_rente_yr:
                    _kv_custom_solo.append(f"AN-Anteil GKV: {_de(_kv_val)} €")
                elif _profil_eo.krankenversicherung == "PKV":
                    _kv_custom_solo.append(f"PKV: {_de(_kv_val)} €")
                elif _profil_eo.kvdr_pflicht:
                    _kv_custom_solo.append(f"KVdR: {_de(_kv_val)} €")
                else:
                    _kv_custom_solo.append(f"freiwillig GKV: {_de(_kv_val)} €")
            fig_tax.add_trace(go.Bar(
                name="KV/PV", x=df_jd.index, y=df_jd["KV_PV"],
                marker_color="#FFF176",
                customdata=_kv_custom_solo,
                hovertemplate="%{x}: %{y:,.0f} €<br><i>%{customdata}</i><extra>KV/PV</extra>",
            ))
        _ba_p1_eo = besteuerungsanteil(_profil_eo.eintritt_jahr)
        _ba_p2_eo = besteuerungsanteil(_profil2_eo.eintritt_jahr) if _profil2_eo else 0.0
        _zve_custom = []
        for _yr_tax, _row_tax in df_jd.iterrows():
            _yr_int = int(_yr_tax)
            _zve_total = int(_row_tax.get("zvE", 0))
            _parts_zv = [f"<b>{_yr_int} – zvE: {_de(_zve_total)} €/Jahr</b>"]
            _gehalt_z = _row_tax.get("Src_Gehalt", 0)
            _gesrente_z = _row_tax.get("Src_GesRente", 0)
            _p2rente_z = _row_tax.get("Src_P2_Rente", 0)
            _bav_z = _row_tax.get("Src_bAV_P1", 0) + _row_tax.get("Src_bAV_P2", 0)
            _riester_z = _row_tax.get("Src_Riester_P1", 0) + _row_tax.get("Src_Riester_P2", 0)
            _miete_z = _row_tax.get("Src_Miete", 0)
            _duv_buv_z = _row_tax.get("Src_DUV_P1", 0) + _row_tax.get("Src_BUV_P1", 0)
            if _gehalt_z > 0:
                _parts_zv.append(f"Bruttogehalt: {_de(int(_gehalt_z))} € (100 %, § 19 EStG)")
            if _gesrente_z > 0:
                _parts_zv.append(f"GRV P1: {_de(int(_gesrente_z))} € × {_ba_p1_eo:.0%} = {_de(int(_gesrente_z * _ba_p1_eo))} € (§ 22 EStG)")
            if _p2rente_z > 0:
                _parts_zv.append(f"GRV P2: {_de(int(_p2rente_z))} € × {_ba_p2_eo:.0%} = {_de(int(_p2rente_z * _ba_p2_eo))} € (§ 22 EStG)")
            if _bav_z > 0:
                _parts_zv.append(f"bAV: {_de(int(_bav_z))} € (100 %, § 22 Nr. 5 EStG)")
            if _riester_z > 0:
                _parts_zv.append(f"Riester/PrivRV: {_de(int(_riester_z))} € (Ertragsanteil)")
            if _miete_z > 0:
                _parts_zv.append(f"Mieteinnahmen: {_de(int(_miete_z))} € (100 %, § 21 EStG)")
            if _duv_buv_z > 0:
                _parts_zv.append(f"DUV/BUV: {_de(int(_duv_buv_z))} € (Ertragsanteil, § 22 EStG)")
            _kap_inj_z = _row_tax.get("Src_KapInjektion", 0)
            _kap_inj_progr_z = _row_tax.get("Src_KapInjektion_progr", 0)
            if _kap_inj_z > 0:
                if _kap_inj_progr_z > 0:
                    _parts_zv.append(
                        f"Pool-Einzahlung: {_de(int(_kap_inj_z))} € Brutto "
                        f"→ {_de(int(_kap_inj_progr_z))} € steuerpfl. "
                        f"(50 % Ertrag, § 20 Abs. 1 Nr. 6 EStG)"
                    )
                else:
                    _parts_zv.append(
                        f"Pool-Einzahlung: {_de(int(_kap_inj_z))} € "
                        f"(steuerfrei oder Abgeltungsteuer – kein zvE-Beitrag)"
                    )
            _parts_zv.append(f"(Abzgl. Grundfreibetrag, Werbungskosten, Sonderausgaben)")
            _zve_custom.append("<br>".join(_parts_zv))
        fig_tax.add_trace(go.Scatter(
            name="zvE", x=df_jd.index, y=df_jd["zvE"],
            mode="lines", line=dict(color="#5C6BC0", width=2, dash="dot"),
            yaxis="y2",
            customdata=_zve_custom,
            hovertemplate="%{customdata}<extra></extra>",
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

        st.divider()

        # ── Jahresverlauf nach Einkommensquelle ───────────────────────────────
        st.subheader("Jahresverlauf nach Einkommensquelle")
        _rl_col1, _rl_col2 = st.columns([2, 1])
        with _rl_col1:
            _real_toggle = st.checkbox(
                "Reale Werte (inflationsbereinigt)",
                value=False, key=f"rc{_rc}_eo_real",
                help="Deflationiert alle Jahreswerte auf die Kaufkraft des Renteneintritts-Jahres.",
            )
        with _rl_col2:
            _real_inf = st.number_input(
                "Inflation p.a. (%)", 0.0, 5.0, 2.0, 0.1,
                key=f"rc{_rc}_eo_inflation",
                disabled=not _real_toggle,
                help="Jährliche Inflationsrate für Kaufkraftkorrektur.",
            ) if _real_toggle else 2.0
        if _any_spaet:
            _ov_desc = " · ".join(
                f"**{pn.rsplit('(', 1)[0].strip()}** spät"
                for pn, sel in _sels.items() if sel == "spaet"
            )
            st.info(
                f"🔄 **Spät-Auszahlung aktiv** · {_ov_desc}  \n"
                "Alle Diagramme zeigen diese Strategie."
            )

        # Reale Werte: alle numerischen Spalten mit Inflationsdeflaktor skalieren
        _start_j = int(df_jd.index[0]) if len(df_jd) > 0 else 0
        if _real_toggle and _real_inf > 0:
            _inf_r = _real_inf / 100
            _deflator = {j: 1.0 / (1 + _inf_r) ** (j - _start_j) for j in df_jd.index}
            _num_cols = [c for c in df_jd.columns if df_jd[c].dtype in ("float64", "int64")
                         and c not in ("LHK",)]
            for _col in _num_cols:
                df_jd[_col] = df_jd[_col] * df_jd.index.map(_deflator)

        # Vertragsnamen pro Jahr für Einmal- und Versorgungsbalken
        _jahre = list(df_jd.index)
        _VERSORGUNG_TYPEN = {"bAV", "Riester", "Rürup", "PrivateRente"}
        _einmal_info         = {j: [] for j in _jahre}  # Einkommens-Einmalzahlungen (nicht aus Pool)
        _einmal_info_kapital = {j: [] for j in _jahre}  # als_kapitalanlage → Pool-Injektion
        _bav_info     = {j: [] for j in _jahre}   # bAV-Produkte (konsolidiert)
        _riester_info = {j: [] for j in _jahre}   # Riester-Produkte
        _sonstige_versorg_info = {j: [] for j in _jahre}  # Rürup, PrivateRente
        for _prod, _startjahr, _anteil in _eff_entsch:
            _aufschub = max(0, _startjahr - _prod.fruehestes_startjahr)
            _fak = (1 + _prod.aufschub_rendite) ** _aufschub
            # Einmalauszahlung: nur im Startjahr
            if _anteil > 0 and _startjahr in _einmal_info:
                _betrag = _prod.max_einmalzahlung * _fak * _anteil
                if _prod.als_kapitalanlage:
                    _einmal_info_kapital[_startjahr].append(f"{_prod.name} (Brutto: {_de(_betrag)} €)")
                else:
                    _einmal_info[_startjahr].append(f"{_prod.name}: {_de(_betrag)} €")
            # Laufende Versorgung: ab Startjahr für die Laufzeit – nach Typ aufteilen
            if _anteil < 1.0 and _prod.typ in _VERSORGUNG_TYPEN:
                _mono = _prod.max_monatsrente * _fak * (1 - _anteil)
                _lz = _prod.laufzeit_jahre  # 0 = lebenslang
                _info_target = (
                    _bav_info if _prod.typ == "bAV"
                    else _riester_info if _prod.typ == "Riester"
                    else _sonstige_versorg_info
                )
                for _j in _jahre:
                    if _j < _startjahr:
                        continue
                    if _lz > 0 and _j >= _startjahr + _lz:
                        break
                    _info_target[_j].append(f"{_prod.name}: {_de(_mono)} €/Mon.")

        def _hover_lines(info_dict: dict, jahre: list) -> list[str]:
            return [
                "<br>".join(info_dict[j]) if info_dict[j] else ""
                for j in jahre
            ]

        _cd_einmal   = _hover_lines(_einmal_info,         _jahre)
        _cd_bav      = _hover_lines(_bav_info,            _jahre)
        _cd_riester  = _hover_lines(_riester_info,        _jahre)
        _cd_sonstige = _hover_lines(_sonstige_versorg_info, _jahre)

        # Berechnete Kombinationsspalten für bAV und Riester (P1 + P2)
        _bav_p1     = df_jd["Src_bAV_P1"]     if "Src_bAV_P1"     in df_jd.columns else pd.Series(0, index=df_jd.index)
        _bav_p2     = df_jd["Src_bAV_P2"]     if "Src_bAV_P2"     in df_jd.columns else pd.Series(0, index=df_jd.index)
        _riester_p1 = df_jd["Src_Riester_P1"] if "Src_Riester_P1" in df_jd.columns else pd.Series(0, index=df_jd.index)
        _riester_p2 = df_jd["Src_Riester_P2"] if "Src_Riester_P2" in df_jd.columns else pd.Series(0, index=df_jd.index)
        df_jd["Src_bAV_Gesamt"]          = _bav_p1 + _bav_p2
        df_jd["Src_Riester_Gesamt"]       = _riester_p1 + _riester_p2
        # Sonstige Versorgung = Src_Versorgung minus bAV und Riester (Rürup, PrivateRente, P2-Anteile)
        if "Src_Versorgung" in df_jd.columns:
            df_jd["Src_Sonstige_Versorgung"] = (
                df_jd["Src_Versorgung"] - df_jd["Src_bAV_Gesamt"] - df_jd["Src_Riester_Gesamt"]
            ).clip(lower=0)

        fig_src = go.Figure()
        src_cols = [
            ("Src_Gehalt",              "Bruttogehalt (aktiv)",      "#78909C", None),
            ("Src_Zusatzentgelt",       "Zusatzentgelt (PV, stfr.)", "#546E7A", None),
            ("Src_GesRente",            "Gesetzl. Rente P1",         "#4CAF50", None),
            ("Src_P2_Rente",            "Gesetzl. Rente P2",         "#81C784", None),
            ("Src_bAV_Gesamt",          "bAV (gesamt)",              "#1565C0", _cd_bav),
            ("Src_Riester_Gesamt",      "Riester",                   "#42A5F5", _cd_riester),
            ("Src_Sonstige_Versorgung", "Versorgung (Rürup/Privat)", "#26C6DA", _cd_sonstige),
            ("Src_Einmal",              "Einmalauszahlungen",        "#FF9800", _cd_einmal),
            ("Src_Miete",               "Mieteinnahmen",             "#9C27B0", None),
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
        # Vorsorge-Beiträge werden nicht als Balken dargestellt; nur in der Netto-Hover sichtbar.

        # "Monatlich ✓"-Selektion: Scatter-Linie für monatliche Vertragsauszahlungen
        for _pn_mono, _sv_mono in _sels.items():
            if _sv_mono != "mono":
                continue
            _p_mono = _prod_name_map.get(_pn_mono)
            if _p_mono is None or _p_mono.max_monatsrente == 0:
                continue
            _sj_m = _p_mono.fruehestes_startjahr
            _val_pa_m = _p_mono.max_monatsrente * 12
            _lz_m = _p_mono.laufzeit_jahre if _p_mono.laufzeit_jahre > 0 else horizon
            _ej_m = _sj_m + _lz_m - 1
            _xs_m = [j for j in _jahre if _sj_m <= j <= _ej_m]
            if _xs_m:
                fig_src.add_trace(go.Scatter(
                    name=f"{_p_mono.name} (monatl.)",
                    x=_xs_m, y=[_val_pa_m] * len(_xs_m),
                    mode="lines+markers",
                    line=dict(color="#FF6F00", width=3),
                    marker=dict(size=6, color="#FF6F00"),
                    hovertemplate=(
                        f"<b>%{{x}}</b>: {_de(_p_mono.max_monatsrente)} €/Mon."
                        f" = {_de(_val_pa_m)} €/Jahr<br>{_p_mono.name}"
                        "<extra>Monatlich</extra>"
                    ),
                ))

        # Geplante Entnahmen: nur als y1-Balken wenn kein Pool aktiv
        _has_pool_data = (
            "Kap_Injektion" in df_jd.columns and df_jd["Kap_Injektion"].sum() > 0
        )
        _sonder_yrs_chart: dict[int, float] = {}
        if _hyp_info and not _has_pool_data:
            for _sc_s in get_hyp_schedule():
                if _sc_s["Sondertilgung"] > 0 and _sc_s["Jahr"] in df_jd.index:
                    _sonder_yrs_chart[_sc_s["Jahr"]] = _sc_s["Sondertilgung"]
        _pf_abs: dict[int, float] = {}

        if _entnahmen_dict and not _has_pool_data:
            _en_yrs_src = [j for j in _entnahmen_dict if j in df_jd.index]
            if _en_yrs_src:
                fig_src.add_trace(go.Bar(
                    name="Entnahmen (geplant)",
                    x=_en_yrs_src,
                    y=[-_entnahmen_dict[j] for j in _en_yrs_src],
                    marker_color="#E65100",
                    opacity=0.85,
                    hovertemplate="%{x}: %{y:,.0f} € Entnahme<extra>Entnahmen (geplant)</extra>",
                ))

        # ── Zwei getrennte Pool-Flow-Balken nebeneinander (sekundäre Y-Achse) ──
        # Einzahlung (links, teal) und manuelle Entnahmen (rechts, rot) als je halbe Balkenbreite.
        _manual_w_key = "pool_topup_withdrawals"
        _manual_withdrawals: dict[int, float] = dict(st.session_state.get(_manual_w_key, {}))
        _hat_pool_y2 = False
        if _has_pool_data:
            _hat_pool_y2 = True
            _pf_inj_col    = "Kap_Injektion"
            _pf_sonder_col = "Kap_Sonder_Tilgung"
            _pf_all_yrs = sorted(set(
                (list(df_jd[df_jd[_pf_inj_col] > 0].index)
                 if _pf_inj_col in df_jd.columns else [])
                + list(_manual_withdrawals.keys())
                + (list(df_jd[df_jd[_pf_sonder_col] > 0].index)
                   if _pf_sonder_col in df_jd.columns else [])
            ))
            def _pf_val(col, j):
                return float(df_jd.loc[j, col]) if col in df_jd.columns and j in df_jd.index else 0.0
            _pf_inj = {j: _pf_val(_pf_inj_col, j) for j in _pf_all_yrs}
            _pf_vzr_manual = {j: _manual_withdrawals.get(j, 0.0) for j in _pf_all_yrs if _manual_withdrawals.get(j, 0.0) > 0}
            # Für y2-Skalenberechnung: Maximum aus Einzahlung und manuelle Entnahmen
            _pf_abs = {j: max(_pf_inj[j], _pf_vzr_manual.get(j, 0.0)) for j in _pf_all_yrs}

            # Pool-Einzahlung nur anzeigen wenn Früh/Spät-Checkbox aktiv
            _any_sels = any(v is not None for v in _sels.values())
            # Jahre mit Einzahlung: Balken links (x - 0.2), teal
            _pf_inj_yrs = [j for j in _pf_all_yrs if _pf_inj[j] > 0]
            if _pf_inj_yrs and _any_sels:
                def _pf_inj_hover(j):
                    parts = [f"Pool-Einzahlung: {_de(_pf_inj[j])} €"]
                    ki_det = "<br>".join(_einmal_info_kapital.get(j, []))
                    if ki_det:
                        parts.append(f"<i>{ki_det}</i>")
                    return "<br>".join(parts)
                fig_src.add_trace(go.Bar(
                    name="Pool-Einzahlung",
                    x=[j - 0.2 for j in _pf_inj_yrs],
                    y=[-_pf_inj[j] for j in _pf_inj_yrs],
                    width=0.4,
                    marker_color="#00838F",
                    opacity=0.87,
                    yaxis="y2",
                    customdata=[_pf_inj_hover(j) for j in _pf_inj_yrs],
                    hovertemplate="%{x|.0f}:<br>%{customdata}<extra>Pool-Einzahlung</extra>",
                ))

            # Manuelle Pool-Entnahmen aus Top-Up-Tabelle (statt Auto-Annuität)
            if _pf_vzr_manual:
                fig_src.add_trace(go.Bar(
                    name="Pool-Entnahme (manuell)",
                    x=[j + 0.2 for j in sorted(_pf_vzr_manual)],
                    y=[-_pf_vzr_manual[j] for j in sorted(_pf_vzr_manual)],
                    width=0.4,
                    marker_color="#E53935",
                    opacity=0.87,
                    yaxis="y2",
                    hovertemplate="%{x|.0f}: %{y:,.0f} € manuelle Pool-Entnahme<extra>Pool-Entnahme</extra>",
                ))
        elif _manual_withdrawals:
            _hat_pool_y2 = True
            _pf_abs = {j: v for j, v in _manual_withdrawals.items()}

        if _sonder_yrs_chart and not _has_pool_data:
            _hat_pool_y2 = True
            for _stj, _sta in _sonder_yrs_chart.items():
                _pf_abs[_stj] = max(_pf_abs.get(_stj, 0.0), _sta)
            _st_chart_yrs = sorted(_sonder_yrs_chart)
            fig_src.add_trace(go.Bar(
                name="Sondertilgung",
                x=_st_chart_yrs,
                y=[-_sonder_yrs_chart[j] for j in _st_chart_yrs],
                width=0.6,
                marker_color="#E53935",
                opacity=0.87,
                yaxis="y2",
                hovertemplate="%{x|.0f}: %{y:,.0f} € Sondertilgung<extra>Sondertilgung</extra>",
            ))

        # Korrigiertes Netto: nach Steuer+KV, vor Vorsorge-Beiträgen und LHK
        _vb_col_eo  = df_jd["Vorsorge_Beitraege"] if "Vorsorge_Beitraege" in df_jd.columns else pd.Series(0, index=df_jd.index)
        _lhk_col_eo = df_jd["LHK"]                if "LHK"                in df_jd.columns else pd.Series(0, index=df_jd.index)
        _netto_korr_eo = df_jd["Netto"] + _vb_col_eo + _lhk_col_eo

        # Netto-Linie mit Hover-Details zu allen Abzügen
        _netto_hover = []
        for _nhj in _jahre:
            _nh_parts = []
            _nh_steuer = int(df_jd.loc[_nhj, "Steuer"])              if "Steuer"             in df_jd.columns else 0
            _nh_kv     = int(df_jd.loc[_nhj, "KV_PV"])               if "KV_PV"              in df_jd.columns else 0
            _nh_vb     = int(df_jd.loc[_nhj, "Vorsorge_Beitraege"])  if "Vorsorge_Beitraege" in df_jd.columns else 0
            _nh_lhk    = int(df_jd.loc[_nhj, "LHK"])                 if "LHK"                in df_jd.columns else 0
            if _nh_steuer > 0: _nh_parts.append(f"Steuer: −{_de(_nh_steuer)} €")
            if _nh_kv     > 0: _nh_parts.append(f"KV/PV: −{_de(_nh_kv)} €")
            if _nh_vb     > 0: _nh_parts.append(f"Vorsorgebeitr.: −{_de(_nh_vb)} €")
            if _nh_lhk    > 0: _nh_parts.append(f"Lebenshaltung: −{_de(_nh_lhk)} €")
            _netto_hover.append("<br>".join(_nh_parts))
        fig_src.add_trace(go.Scatter(
            name="Netto", x=df_jd.index, y=_netto_korr_eo,
            mode="lines+markers",
            line=dict(color="black", width=2),
            customdata=_netto_hover,
            hovertemplate="%{x}: %{y:,.0f} € Netto (nach Steuer+KV)<br>%{customdata}<extra>Netto</extra>",
        ))
        # Mindesthaushaltsbetrag als blaue Linie
        _mindest_mono = int(st.session_state.get("mindest_haushalt_mono", 0) * _eo_solo_fak)
        _mindest_j_line = _mindest_mono * 12
        if _mindest_j_line > 0:
            fig_src.add_hline(
                y=_mindest_j_line,
                line_width=2, line_dash="dot", line_color="#1565C0",
                annotation_text=f"Mindesthaushalt {_de(_mindest_mono)} €/Mon.",
                annotation_position="top left",
                annotation_font_color="#1565C0",
            )
        # Netto nach Hypotheken-Rate: Primärhypothek (rot) + Anschlusskredit (orange), getrennte Linien
        if _ausgaben_plan:
            _prim_sched_yrs = {s["Jahr"] for s in get_hyp_schedule()}
            _ap_prim_yrs = sorted(
                yr for yr in df_jd.index
                if _ausgaben_plan.get(yr, 0) > 0 and yr in _prim_sched_yrs
            )
            _ap_ak_yrs = sorted(
                yr for yr in df_jd.index
                if _ausgaben_plan.get(yr, 0) > 0 and yr not in _prim_sched_yrs
            )
            # Anschlusskredit-Linie beim letzten Primär-Jahr beginnen lassen (visueller Anschluss)
            if _ap_prim_yrs and _ap_ak_yrs:
                _connect_yr = _ap_prim_yrs[-1]
                if _connect_yr not in _ap_ak_yrs:
                    _ap_ak_yrs = [_connect_yr] + _ap_ak_yrs
            if _ap_prim_yrs:
                fig_src.add_trace(go.Scatter(
                    name="Netto nach Hyp.-Rate",
                    x=_ap_prim_yrs,
                    y=[_netto_korr_eo.loc[yr] - _ausgaben_plan[yr] for yr in _ap_prim_yrs],
                    mode="lines+markers",
                    line=dict(color="#D32F2F", width=2, dash="dot"),
                    hovertemplate="%{x}: %{y:,.0f} € nach Hyp.-Rate<extra></extra>",
                ))
            if _ap_ak_yrs:
                fig_src.add_trace(go.Scatter(
                    name="Netto nach Anschlusskredit",
                    x=_ap_ak_yrs,
                    y=[_netto_korr_eo.loc[yr] - _ausgaben_plan.get(yr, 0) for yr in _ap_ak_yrs],
                    mode="lines+markers",
                    line=dict(color="#FF6F00", width=2, dash="dot"),
                    hovertemplate="%{x}: %{y:,.0f} € nach Anschlusskredit<extra></extra>",
                ))
        # Gelbe Linie: frei verfügbares Einkommen nach allen Ausgaben + Hypothek
        # Formel: engine_Netto − Fixausgaben − Kap_Sonder_Tilgung
        # Netto hat den nicht-pool-gedeckten Hypothek-Anteil bereits abgezogen; nur der
        # pool-gedeckte Anteil (kap_sonder) muss noch subtrahiert werden, damit die Linie
        # konsistent "Netto nach voller Hypothekenbelastung" zeigt – unabhängig vom Pool-Zustand.
        _fixausgaben_eo = list(st.session_state.get("hh_fixausgaben", []))
        _yel_yrs = list(df_jd.index)
        _yel_ys = []
        for _yr in _yel_yrs:
            _fix_j = sum(
                fa["betrag_monatlich"] * 12
                for fa in _fixausgaben_eo
                if fa["startjahr"] <= _yr <= fa["endjahr"]
            ) * _eo_solo_fak
            _kap_sonder_yr = (float(df_jd.loc[_yr, "Kap_Sonder_Tilgung"])
                              if "Kap_Sonder_Tilgung" in df_jd.columns else 0.0) * _eo_solo_fak
            _yel_ys.append(df_jd.loc[_yr, "Netto"] - _fix_j - _kap_sonder_yr)
        fig_src.add_trace(go.Scatter(
            name="Frei nach Ausg.+Hyp.",
            x=_yel_yrs, y=_yel_ys,
            mode="lines+markers",
            line=dict(color="#F9A825", width=2, dash="dash"),
            customdata=[f"{v:,.0f} € Ausgaben + Hypothek" for v in _yel_ys],
            hovertemplate="%{x}: %{customdata}<extra>Frei nach Ausg.+Hyp.</extra>",
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
                annotation_text="P2 Renteneintritt", annotation_position="bottom left",
            )
        # Einmalige Auszahlungen (Einkommen) als Markierungen oberhalb des Diagramms
        _einmal_idx = 0
        for _ej in _jahre:
            if _einmal_info.get(_ej):
                fig_src.add_vline(x=_ej, line_width=1, line_dash="dot", line_color="#FF9800")
                _ann_y = 1.08 if _einmal_idx % 2 == 0 else 1.22
                fig_src.add_annotation(
                    x=_ej, xref="x",
                    y=_ann_y, yref="paper",
                    text="<br>".join(_einmal_info[_ej]),
                    showarrow=False,
                    xanchor="left", yanchor="bottom",
                    font=dict(color="#FF9800", size=9),
                    bgcolor="rgba(255,152,0,0.08)",
                    bordercolor="#FF9800",
                )
                _einmal_idx += 1
        # Sonderausgaben (Hypothek-Raten / Einmaltilgung) als Annotationen unterhalb der Balken
        _hat_sonder = "Sonderausgabe" in df_jd.columns and df_jd["Sonderausgabe"].sum() > 0
        if _hat_sonder:
            for _si, _sj in enumerate(df_jd[df_jd["Sonderausgabe"] > 0].index):
                _sa = df_jd.loc[_sj, "Sonderausgabe"]
                _ay_val = 35 if _si % 2 == 0 else 65
                fig_src.add_annotation(
                    x=_sj, y=0,
                    text=f"Hyp. {_de(_sa / 1000, 0)}k€",
                    showarrow=True, arrowhead=2, arrowcolor="#D32F2F",
                    font=dict(color="#D32F2F", size=11),
                    ax=0, ay=_ay_val,
                )
        # ── Y-Achsen-Bereiche (explizit für Null-Ausrichtung) ────────────────────
        # Ziel: Nulllinie bei genau 1/3 der Chart-Höhe von unten.
        # Formel: |lo| = hi/2  →  f = |lo|/(|lo|+hi) = (hi/2)/(hi/2+hi) = 1/3 ✓
        _y1_pos_cols = [
            "Src_Gehalt", "Src_Zusatzentgelt", "Src_GesRente", "Src_P2_Rente",
            "Src_bAV_Gesamt", "Src_Riester_Gesamt", "Src_Sonstige_Versorgung",
            "Src_Einmal", "Src_Miete",
        ]
        _y1_pos_sum = sum(
            df_jd[c].clip(lower=0) for c in _y1_pos_cols if c in df_jd.columns
        )
        _y1_hi_data = float(_y1_pos_sum.max()) if hasattr(_y1_pos_sum, "max") else 0.0
        _y1_lo_data = 0.0
        if "Vorsorge_Beitraege" in df_jd.columns:
            _y1_lo_data = min(_y1_lo_data, -float(df_jd["Vorsorge_Beitraege"].max()))
        _y1_hi = _y1_hi_data * 1.08 or 1.0

        if _hat_pool_y2:
            # Maximaler Saldo-Absolutwert der Pool-Flows bestimmt y2-Skala
            _pool_range = max(_pf_abs.values()) * 1.15 if _pf_abs else 1.0
            # y1: Nulllinie bei 1/3 → |lo| = hi/2
            _y1_lo = min(_y1_lo_data * 1.08, -_y1_hi / 2)
            # y2: Nulllinie bei 1/3 → y2_lo=-pool_range, y2_hi=2*pool_range
            # Probe: pool_range/(pool_range+2*pool_range) = 1/3 ✓
            _y2_lo = -_pool_range
            _y2_hi = 2.0 * _pool_range
            # Ticks auf y2 nur von 0 nach unten (als positive Labels).
            # Ziel: ~4 Ticks. Exponent auf Basis des Ideal-Schritts (pool_range/4) berechnen,
            # damit round() nicht auf 0 abrundet wenn pool_range < 4 * 10^tick_exp.
            if _pool_range >= 1:
                _ideal_step = _pool_range / 4
                _tick_exp = math.floor(math.log10(max(_ideal_step, 1)))
                _tick_step = max(1, round(_ideal_step / 10 ** _tick_exp) * (10 ** _tick_exp))
            else:
                _tick_step = 1
            _y2_tick_neg = [0]
            _t = _tick_step
            while _t <= _pool_range * 1.01:
                _y2_tick_neg.append(-_t)
                _t += _tick_step
            _y2_tick_lbl = [f"{int(abs(v)):,}".replace(",", ".") for v in _y2_tick_neg]
        else:
            _y1_lo = min(_y1_lo_data * 1.08, -_y1_hi * 0.05)

        _has_einmal_annotations = any(_einmal_info.get(j) for j in _jahre)
        # Legende über dem Diagramm: Einmal-Annotations gehen jetzt bis y=1.22 (alternierend),
        # daher Legende und Top-Margin entsprechend erhöht.
        _legend_y = 1.50 if _has_einmal_annotations else 1.20
        _margin_t = 310 if _has_einmal_annotations else 160
        _src_layout: dict = dict(
            barmode="stack", template="plotly_white", height=520,
            xaxis=dict(title="Jahr", dtick=2),
            yaxis=dict(title="€ / Jahr (brutto)", tickformat=",.0f",
                       range=[_y1_lo, _y1_hi]),
            legend=dict(orientation="h", yanchor="bottom", y=_legend_y, xanchor="right", x=1),
            margin=dict(l=10, r=10, t=_margin_t, b=10),
            separators=",.",
        )
        if _hat_pool_y2:
            _src_layout["yaxis2"] = dict(
                title="Pool-Flows (€/Jahr)",
                overlaying="y",
                side="right",
                showgrid=False,
                range=[_y2_lo, _y2_hi],
                tickvals=_y2_tick_neg,
                ticktext=_y2_tick_lbl,
            )
        fig_src.update_layout(**_src_layout)
        st.plotly_chart(fig_src, use_container_width=True)

        if _has_pool_data:
            with st.expander("ℹ️ Was bedeuten Pool-Einzahlung und Pool-Entnahme?", expanded=False):
                st.markdown(
                    "**Pool-Einzahlung** (türkiser Balken, rechte Achse)  \n"
                    "Ein Vorsorgevertrag (z.B. Lebensversicherung, ETF-Sparplan) wird als Einmalbetrag "
                    "ausgezahlt. Die App berechnet für jedes Produkt genau die gesetzlich anfallende "
                    "Steuer und Krankenversicherung (ETF: Abgeltungsteuer 25 %; LV/Private Rente: "
                    "Halbeinkünfte- oder Abgeltungsverfahren; bAV/Riester: voller Einkommensteuersatz). "
                    "Nur der **verbleibende Nettobetrag** fließt in den internen **Kapitalpool** "
                    "und wird dort weiter verzinst.\n\n"
                    "**Pool-Entnahme** (roter Balken, rechte Achse)  \n"
                    "Manuelle Entnahmen aus dem Kapitalpool (eingetragen in der Tabelle unten). "
                    "Diese erhöhen das verfügbare Nettoeinkommen im jeweiligen Jahr.\n\n"
                    "**Warum macht das Sinn?**  \n"
                    "Eine einmalige große Auszahlung würde mit dem Spitzensteuersatz des Auszahlungsjahres "
                    "besteuert. Wird das Kapital dagegen über viele Jahre als Annuität entnommen, bleibt "
                    "man in niedrigeren Steuerzonen – das erhöht das Netto über den gesamten Zeitraum.\n\n"
                    "**Tipp:** Wie hoch die jährliche Pool-Entnahme ist, hängt vom Planungshorizont "
                    "(Slider oben) und der Pool-Rendite im Tab ⚙️ Profil → Erweiterte Einstellungen ab."
                )

        # ── Kapital-Zeitleiste ─────────────────────────────────────────────────
        # P2 Kapital-Werte
        _spkap2_orig     = 0.0
        _spkap2_sparrate = 0.0
        _spkap2_rendite  = 0.05
        _spkap2_eintritt_j = _spkap_eintritt_j
        _spkap2          = 0.0
        if _profil2_eo is not None and _ergebnis2_eo is not None:
            _spkap2_orig     = float(getattr(_profil2_eo, "sparkapital", 0.0))
            _spkap2_sparrate = float(getattr(_profil2_eo, "sparrate", 0.0))
            _spkap2_rendite  = float(getattr(_profil2_eo, "rendite_pa", 0.05))
            _spkap2_eintritt_j = (_profil2_eo.rentenbeginn_jahr if _profil2_eo.bereits_rentner
                                  else _profil2_eo.eintritt_jahr)
            _spkap2 = float(getattr(_ergebnis2_eo, "kapital_bei_renteneintritt", 0.0))

        _hat_spar_post = False  # Sparkapital nicht mehr als Pool-Produkt — Zeitleiste verfolgt es direkt

        # Vorsorge-Pools (als_kapitalanlage-Produkte, ohne synthetisches Sparkapital)
        _real_pool_pids = [
            c[len("Kap_Pool_"):] for c in df_jd.columns
            if c.startswith("Kap_Pool_") and not c.endswith("__sparkapital__")
            and df_jd[c].sum() > 0
        ]
        _prod_names_all = {p.id: p.name for p in _produkte_obj_run}
        # Identify P1 vs P2 product pools
        _p1_pool_pids = [pid for pid in _real_pool_pids
                         if any(p.id == pid and getattr(p, "person", "Person 1") == "Person 1"
                                for p in _produkte_obj_run)]
        _p2_pool_pids = [pid for pid in _real_pool_pids
                         if any(p.id == pid and getattr(p, "person", "Person 1") == "Person 2"
                                for p in _produkte_obj_run)]

        _show_kap_chart = _spkap_orig > 0 or _spkap2_orig > 0 or len(_real_pool_pids) > 0
        if _show_kap_chart:
            st.subheader("💰 Kapital-Zeitleiste")
            fig_spar = go.Figure()
            _x_chart_start = AKTUELLES_JAHR
            _x_chart_end   = _spkap_eintritt_j + horizon

            _p1_post_series_gesamt: pd.Series | None = None
            _p2_post_series_gesamt: pd.Series | None = None
            _hat_partner_kap = _spkap2_orig > 0 or bool(_p2_pool_pids)

            def _kap_hover(series: pd.Series, pool_pids: list[str],
                           label: str, df: "pd.DataFrame",
                           rendite_pa: float = 0.05,
                           sparrate_p1: float = 0.0, eintritt_j_p1: int = 0,
                           sparrate_p2: float = 0.0, eintritt_j_p2: int = 0,
                           ) -> tuple[pd.Series, list[str]]:
                """Baut customdata-Liste mit Jahresveränderungs-Info für eine Kapitallinie."""
                yrs = list(series.index)
                hover = []
                for i, j in enumerate(yrs):
                    curr = series[j]
                    prev = series[yrs[i - 1]] if i > 0 else curr
                    inj = float(df.loc[j, "Kap_Injektion"]) if ("Kap_Injektion" in df.columns and j in df.index) else 0.0
                    manual_w = _manual_withdrawals.get(j, 0.0)
                    sparrate_j = 0.0
                    if eintritt_j_p1 > 0 and j < eintritt_j_p1:
                        sparrate_j += sparrate_p1 * 12
                    if eintritt_j_p2 > 0 and j < eintritt_j_p2:
                        sparrate_j += sparrate_p2 * 12
                    # Rendite direkt aus konfigurierter Rate (nicht aus Delta berechnen)
                    rendite_amt = prev * rendite_pa
                    parts = []
                    if i > 0:
                        if rendite_amt > 0.5:
                            parts.append(f"+{_de(rendite_amt)} € Rendite ({rendite_pa * 100:.1f} %)")
                        if sparrate_j > 0.5:
                            parts.append(f"+{_de(sparrate_j)} € Spareinlage")
                        if manual_w > 0.5:
                            parts.append(f"−{_de(manual_w)} € Entnahme")
                        if inj > 0.5:
                            parts.append(f"+{_de(inj)} € Einzahlung")
                    hover.append("<br>".join(parts) if parts else "")
                return series, hover

            # ── Kapital gesamt (P1 + P2, eine einzige Linie) ─────────────────
            if _spkap_orig > 0 or _p1_pool_pids or _hat_partner_kap:
                _all_yrs_kap = list(range(AKTUELLES_JAHR, _x_chart_end + 1))

                def _p1_kap(j: int) -> float:
                    if j < _spkap_eintritt_j and not _profil_eo.bereits_rentner:
                        return kapitalwachstum(_spkap_orig, _spkap_sparrate, _spkap_rendite,
                                               j - AKTUELLES_JAHR)
                    # Kapital wird durch monatliche Annuität abgebaut
                    _monatl_kap = float(getattr(_ergebnis_eo, "kapital_monatlich", 0.0))
                    return max(0.0, kapitalwachstum(_spkap, -_monatl_kap, _spkap_rendite,
                                                    max(0, j - _spkap_eintritt_j)))

                # Reconstruct product-pool trajectory independently:
                # • grows by rendite • injected via Kap_Injektion • auto-annuity subtracted
                # • manual withdrawals subtracted • hypothek (Sonderausgabe) NOT subtracted
                _all_pids_kap = _p1_pool_pids + _p2_pool_pids
                _rpool_bal = 0.0
                _rpool_series: dict[int, float] = {}
                for _j in sorted(_all_yrs_kap):
                    _rpool_bal *= (1.0 + _spkap_rendite)
                    _inj_j = float(df_jd.at[_j, "Kap_Injektion"]) if "Kap_Injektion" in df_jd.columns and _j in df_jd.index else 0.0
                    _rpool_bal += _inj_j
                    _ann_j = sum(
                        float(df_jd.at[_j, f"Src_Kap_{_pid}"])
                        for _pid in _all_pids_kap
                        if f"Src_Kap_{_pid}" in df_jd.columns and _j in df_jd.index
                    )
                    _rpool_bal = max(0.0, _rpool_bal - _ann_j - _manual_withdrawals.get(_j, 0.0))
                    _rpool_series[_j] = _rpool_bal
                _rpool_pd = pd.Series(_rpool_series).reindex(_all_yrs_kap, fill_value=0.0)

                _df_kap = pd.Series([_p1_kap(j) for j in _all_yrs_kap], index=_all_yrs_kap)
                _df_kap = _df_kap + _rpool_pd

                if _hat_partner_kap:
                    def _p2_kap(j: int) -> float:
                        if _spkap2_orig <= 0:
                            return 0.0
                        if (j < _spkap2_eintritt_j
                                and _profil2_eo is not None
                                and not _profil2_eo.bereits_rentner):
                            return kapitalwachstum(_spkap2_orig, _spkap2_sparrate, _spkap2_rendite,
                                                   j - AKTUELLES_JAHR)
                        return kapitalwachstum(_spkap2, 0.0, _spkap2_rendite,
                                               max(0, j - _spkap2_eintritt_j))
                    _p2_series = pd.Series([_p2_kap(j) for j in _all_yrs_kap], index=_all_yrs_kap)
                    # P2 product pools already included in _rpool_pd
                    _df_kap = _df_kap + _p2_series
                    _p1_post_series_gesamt = _df_kap
                    _p2_post_series_gesamt = pd.Series(0.0, index=_all_yrs_kap)
                else:
                    _p1_post_series_gesamt = _df_kap

                _eintritt_p1_spar = 0 if _profil_eo.bereits_rentner else _spkap_eintritt_j
                _eintritt_p2_spar = 0 if (_profil2_eo is None or _profil2_eo.bereits_rentner) else _spkap2_eintritt_j
                _, _kap_cd = _kap_hover(
                    _df_kap, _p1_pool_pids + _p2_pool_pids, "Kapital", df_jd,
                    rendite_pa=_spkap_rendite,
                    sparrate_p1=_spkap_sparrate, eintritt_j_p1=_eintritt_p1_spar,
                    sparrate_p2=(_spkap2_sparrate if _hat_partner_kap else 0.0),
                    eintritt_j_p2=(_eintritt_p2_spar if _hat_partner_kap else 0),
                )
                fig_spar.add_trace(go.Scatter(
                    name="Kapital", x=_df_kap.index, y=_df_kap.values,
                    mode="lines+markers", line=dict(color="#2E7D32", width=2.5),
                    customdata=_kap_cd,
                    hovertemplate="%{x}: %{y:,.0f} €<br>%{customdata}<extra>Kapital</extra>",
                ))

            # ── Restschuld (Jahresverlauf) ───────────────────────────────────
            _sched_spar = get_hyp_schedule()
            if _sched_spar:
                _rs_x: list[int] = []
                _rs_y: list[float] = []
                _rs_st_x: list[int] = []
                _rs_st_y: list[float] = []
                _rs_st_hover: list[str] = []
                for _s in _sched_spar:
                    if _s["Restschuld_Anfang"] > 0:
                        _rs_x.append(_s["Jahr"])
                        _rs_y.append(_s["Restschuld_Anfang"])
                        if _s.get("Sondertilgung", 0) > 0:
                            _rs_x.append(_s["Jahr"])
                            _rs_y.append(_s["Restschuld_Ende"])
                            _rs_st_x.append(_s["Jahr"])
                            _rs_st_y.append(_s["Restschuld_Anfang"])
                            _rs_st_hover.append(
                                f"{_s['Jahr']}: Sondertilgung {_de(_s['Sondertilgung'])} €"
                                f"<br>Restschuld: {_de(_s['Restschuld_Anfang'])} → {_de(_s['Restschuld_Ende'])} €"
                            )
                    if _s["Restschuld_Ende"] <= 0:
                        break
                # Endpunkt: am endjahr die tatsächliche Resthypothek anzeigen (nicht 0),
                # damit die Linie nahtlos in den Anschlusskredit übergeht.
                _rs_end_val = _ak_zeitleiste_rs if _ak_zeitleiste_rs > 0 else 0.0
                if _rs_x and _endjahr_hyp and _rs_x[-1] < _endjahr_hyp:
                    _rs_x.append(_endjahr_hyp)
                    _rs_y.append(_rs_end_val)
                elif _rs_x and _rs_x[-1] == _endjahr_hyp and _rs_end_val > 0:
                    _rs_y[-1] = _rs_end_val
                if _rs_x:
                    fig_spar.add_trace(go.Scatter(
                        name="Restschuld",
                        x=_rs_x, y=_rs_y,
                        mode="lines+markers",
                        line=dict(color="#D32F2F", width=2, dash="dash"),
                        marker=dict(size=5, symbol="diamond"),
                        hovertemplate="%{x}: %{y:,.0f} € Restschuld<extra>Restschuld</extra>",
                    ))
                if _rs_st_x:
                    fig_spar.add_trace(go.Scatter(
                        name="Sondertilgung",
                        x=_rs_st_x, y=_rs_st_y,
                        mode="markers",
                        marker=dict(size=12, symbol="star", color="#E53935"),
                        customdata=_rs_st_hover,
                        hovertemplate="%{customdata}<extra>Sondertilgung</extra>",
                    ))

            # ── Anschlusskredit-Restschuld ───────────────────────────────────
            if _ak_zeitleiste_rs > 0 and _hyp_info and _anschluss_lz > 0:
                _ak_start = _ak_zeitleiste_startjahr
                _ak_bal = _ak_zeitleiste_rs
                # Einmalzahlungen im Anschlusszeitraum (nach endjahr_hyp)
                _ak_ez_map: dict[int, float] = {}
                for _e in _hyp_ezl:
                    _ej = int(_e["jahr"])
                    if _ej > _endjahr_hyp:
                        _ak_ez_map[_ej] = _ak_ez_map.get(_ej, 0.0) + float(_e["betrag"])

                def _ak_annuitat(bal: float, zins: float, lz: int) -> float:
                    if lz <= 0 or bal <= 0:
                        return 0.0
                    if zins > 0:
                        return bal * zins * (1 + zins) ** lz / ((1 + zins) ** lz - 1)
                    return bal / lz

                _ak_rate = _ak_annuitat(_ak_bal, _markt_zins_pa, _anschluss_lz)
                # Startpunkt am Ende des ersten Kredits (visueller Anschluss)
                _ak_xs: list[int] = [_endjahr_hyp]
                _ak_ys: list[float] = [_ak_bal]
                for _ak_y in range(_ak_start, _ak_start + _anschluss_lz):
                    if _ak_bal <= 0:
                        break
                    # EZ für dieses Jahr: Restschuld reduzieren, Annuität neu berechnen
                    if _ak_y in _ak_ez_map:
                        _ak_bal = max(0.0, _ak_bal - _ak_ez_map[_ak_y])
                        _remaining = _ak_start + _anschluss_lz - _ak_y
                        _ak_rate = _ak_annuitat(_ak_bal, _markt_zins_pa, _remaining)
                    # Anteil für erstes Jahr berechnen (wenn endmonat < 12)
                    _ak_fak = (12 - _endmonat_hyp) / 12 if _ak_y == _ak_start and _endmonat_hyp < 12 else 1.0
                    _ak_zinsen = _ak_bal * _markt_zins_pa * _ak_fak
                    _ak_bal = max(0.0, _ak_bal - (_ak_rate * _ak_fak - _ak_zinsen))
                    _ak_xs.append(_ak_y)
                    _ak_ys.append(_ak_bal)
                if _ak_xs:
                    fig_spar.add_trace(go.Scatter(
                        name="Anschlusskredit",
                        x=_ak_xs, y=_ak_ys,
                        mode="lines+markers",
                        line=dict(color="#FF6F00", width=2, dash="dashdot"),
                        marker=dict(size=5, symbol="diamond-open"),
                        hovertemplate="%{x}: %{y:,.0f} € Anschlusskredit<extra>Anschlusskredit</extra>",
                    ))

            # ── Referenzlinien ──────────────────────────────────────────────
            if _hyp_info and _rs > 0:
                fig_spar.add_vline(
                    x=_hyp_info['endjahr'], line_width=1.5, line_dash="dot",
                    line_color="#D32F2F",
                    annotation_text=f"Hyp.-Ende {_hyp_info['endjahr']}",
                    annotation_position="bottom left", annotation_font_color="#D32F2F",
                )
            if not _profil_eo.bereits_rentner:
                _vl_label = "P1 Renteneintritt" if _spkap2_orig > 0 else "Renteneintritt"
                fig_spar.add_vline(
                    x=_spkap_eintritt_j, line_width=2, line_dash="dash", line_color="#5C6BC0",
                    annotation_text=_vl_label, annotation_position="top right",
                )
            if (_profil2_eo is not None and not _profil2_eo.bereits_rentner
                    and _spkap2_eintritt_j != _spkap_eintritt_j):
                fig_spar.add_vline(
                    x=_spkap2_eintritt_j, line_width=2, line_dash="dash", line_color="#E91E63",
                    annotation_text="P2 Renteneintritt", annotation_position="bottom left",
                )

            # ── Geplante Entnahmen ──────────────────────────────────────────
            if _entnahmen_dict:
                _en_xs = list(_entnahmen_dict.keys())
                _en_ys = [_entnahmen_dict[j] for j in _en_xs]
                fig_spar.add_trace(go.Scatter(
                    name="Entnahmen (geplant)",
                    x=_en_xs, y=_en_ys,
                    mode="markers+text",
                    marker=dict(color="#E65100", size=14, symbol="arrow-bar-down",
                                line=dict(color="#BF360C", width=1)),
                    text=[f"−{_de(b/1000, 0)}k€" for b in _en_ys],
                    textposition="top center",
                    textfont=dict(color="#E65100", size=10),
                    hovertemplate="%{x}: −%{y:,.0f} € Entnahme<extra>Entnahmen (geplant)</extra>",
                ))

            # ── Einmalzahlungen (geplant) ──────────────────────────────────
            if _hyp_ezl:
                _ez_xs = [e["jahr"] for e in _hyp_ezl]
                _ez_ys = [e["betrag"] for e in _hyp_ezl]
                fig_spar.add_trace(go.Scatter(
                    name="Einmalzahlungen (geplant)",
                    x=_ez_xs, y=_ez_ys,
                    mode="markers+text",
                    marker=dict(color="#D32F2F", size=14, symbol="arrow-bar-down",
                                line=dict(color="#B71C1C", width=1)),
                    text=[f"−{_de(b/1000, 0)}k€" for b in _ez_ys],
                    textposition="top center",
                    textfont=dict(color="#D32F2F", size=10),
                    hovertemplate="%{x}: −%{y:,.0f} € Einmalzahlung<extra>Einmalzahlungen (geplant)</extra>",
                ))

            fig_spar.update_layout(
                template="plotly_white", height=400,
                xaxis=dict(title="Jahr", dtick=2,
                           range=[_x_chart_start - 0.5, _x_chart_end + 0.5]),
                yaxis=dict(title="Kapital (€)", tickformat=",.0f"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(l=10, r=10, t=50, b=10),
                separators=",.",
            )
            st.plotly_chart(fig_spar, use_container_width=True)
            _cap_parts = []
            if _spkap_orig > 0:
                _cap_parts.append(
                    f"P1 Kapital @ Renteneintritt: **{_de(_spkap)} €** "
                    f"({_spkap_rendite:.1%} p.a.)"
                )
            if _p1_pool_pids:
                _cap_parts.append(f"{len(_p1_pool_pids)} Vorsorge-Pool(s) in P1 Kapital enthalten")
            if _spkap2_orig > 0:
                _cap_parts.append(
                    f"P2 Kapital @ Renteneintritt: **{_de(_spkap2)} €** "
                    f"({_spkap2_rendite:.1%} p.a.)"
                )
            if _p2_pool_pids:
                _cap_parts.append(f"{len(_p2_pool_pids)} Vorsorge-Pool(s) in P2 Kapital enthalten")
            if _cap_parts:
                st.caption(" · ".join(_cap_parts) + ".")

        # ── Hypothek-Tilgung: Status-Meldungen ───────────────────────────────
        if _hat_sonder and _rs > 0:
            _hat_pool_data = "Kap_Pool" in df_jd.columns and df_jd["Kap_Pool"].sum() > 0
            if _pool_tilgung and _hat_pool_data:
                st.success(
                    f"✅ Restschuld **{_de(_rs)} €** durch Kapital gedeckt "
                    f"(kein Netto-Abzug im Jahr {_hyp_info['endjahr']})."
                )
            elif _einmal_tilgung:
                st.info(
                    f"ℹ️ Restschuld **{_de(_rs)} €** wird im Jahr **{_hyp_info['endjahr']}** "
                    "direkt aus dem verfügbaren Netto getilgt (kein Kapital-Pool aktiv)."
                )
            else:
                # Ratenkredit: nur Anschlussfinanzierungsraten (nach endjahr) aufsummieren
                _sa_raten = sum(
                    v for k, v in _ausgaben_plan.items() if k > _hyp_info['endjahr']
                )
                st.info(
                    f"ℹ️ Anschlussfinanzierung: Gesamtbelastung **{_de(_sa_raten)} €** "
                    f"über {_anschluss_lz} Jahre ab {_hyp_info['endjahr'] + 1} "
                    f"(Nominalzins {_markt_zins_pa*100:.2f} %)."
                )

        # Kapital-Fehlbetrag Warnung (Pool konfiguriert aber unzureichend)
        if "Kap_Fehlbetrag" in df_jd.columns and df_jd["Kap_Fehlbetrag"].sum() > 0:
            _fb_j = df_jd[df_jd["Kap_Fehlbetrag"] > 0]
            _fb_total = _fb_j["Kap_Fehlbetrag"].sum()
            st.warning(
                f"⚠️ Kapital-Fehlbetrag: Kapital reicht in {len(_fb_j)} Jahr(en) nicht "
                f"für alle geplanten Zahlungen (Fehlbetrag gesamt: **{_de(_fb_total)} €**). "
                "Kapital oder Strategie anpassen."
            )

        # ── Tilgungsplan (aufklappbar) ────────────────────────────────────────
        if _hyp_info:
            with st.expander("📋 Tilgungsplan anzeigen", expanded=False):
                _sched = get_hyp_schedule()
                if _sched:
                    _df_tp = pd.DataFrame(_sched)
                    _df_tp_fmt = pd.DataFrame({
                        "Jahr": _df_tp["Jahr"].astype(str),
                        "Restschuld Anfang (€)": _df_tp["Restschuld_Anfang"].map(_de),
                        "Zinsen (€)": _df_tp["Zinsen"].map(_de),
                        "Tilgung (€)": _df_tp["Tilgung"].map(_de),
                        "Sondertilgung (€)": _df_tp["Sondertilgung"].map(_de),
                        "Jahresausgabe (€)": _df_tp["Jahresausgabe"].map(_de),
                        "Restschuld Ende (€)": _df_tp["Restschuld_Ende"].map(_de),
                    })
                    st.dataframe(_df_tp_fmt.set_index("Jahr"), use_container_width=True)
                else:
                    st.caption("Keine Hypothek konfiguriert.")

        # ── Kapitalverzehr-Kalkulator ──────────────────────────────────────────
        with st.expander("💰 Kapitalverzehr-Kalkulator", expanded=False):
            auszahlung.render_section(_profil_eo, _ergebnis_eo)

        # ── Jahresdetails ─────────────────────────────────────────────────────
        st.subheader("Jahresdetails")
        _min_j_jd = int(df_jd.index.min())
        _max_j_jd = int(df_jd.index.max())
        _sel_j = min(_max_j_jd, max(_min_j_jd, _eo_sel_j_shared))
        if _sel_j in df_jd.index:
            _jrow = df_jd.loc[_sel_j]
            jm1, jm2, jm3, jm4 = st.columns(4)
            jm1.metric(
                f"Brutto {_sel_j}", f"{_de(_jrow['Brutto'] / 12)} €/Mon.",
                help=(
                    "Summe aller Bruttoeinnahmen: gesetzliche Rente/Pension, Gehalt (Arbeitsjahre), "
                    "Vorsorgeauszahlungen (bAV, Riester, PrivRV, LV, ETF), Mieteinnahmen und "
                    "Kapitalverzehr aus dem Pool. Vor Steuern und KV/PV."
                ),
            )
            jm2.metric(
                f"Netto {_sel_j}", f"{_de(_jrow['Netto'] / 12)} €/Mon.",
                help=(
                    "Verbleibendes Einkommen nach Abzug von Einkommensteuer (inkl. Soli), "
                    "Abgeltungsteuer, Kranken- und Pflegeversicherung sowie laufenden "
                    "Vorsorgebeiträgen und Lebenshaltungskosten."
                ),
            )
            jm3.metric(
                f"Steuer {_sel_j}", f"{_de(_jrow['Steuer'] / 12)} €/Mon.",
                help=(
                    "Gesamte Steuerbelastung: Einkommensteuer (§ 32a EStG) + Solidaritätszuschlag "
                    "(§ 51a EStG) auf progressiv besteuerte Einkünfte, plus Abgeltungsteuer (25 %) "
                    "auf Kapitalerträge und Gewinne aus dem Kapitalanlage-Pool."
                ),
            )
            jm4.metric(
                f"KV/PV {_sel_j}", f"{_de(_jrow['KV_PV'] / 12)} €/Mon.",
                help=(
                    "Kranken- und Pflegeversicherungsbeiträge. "
                    "KVdR-Pflichtmitglieder (§ 5 Abs. 1 Nr. 11 SGB V): Beiträge nur auf §229-Einkünfte "
                    "(gesetzliche Rente, bAV nach Freibetrag 187,25 €/Mon.). "
                    "Freiwillig GKV (§ 240 SGB V): alle Einkünfte beitragspflichtig, "
                    "Mindest-BMG 1.096,67 €/Mon. "
                    "PKV: fixer Monatsbeitrag."
                ),
            )
            _eo_vors, _eo_vors_help = _vorsorge_ausz_breakdown(_jrow.to_dict())
            if _eo_vors > 0:
                vm1, vm2, vm3, vm4 = st.columns(4)
                vm1.metric(
                    f"Vorsorgeauszahlungen {_sel_j}", f"{_de(_eo_vors)} €/Mon.",
                    help=_eo_vors_help,
                )
            if _jrow["Netto"] < 0:
                st.warning(
                    f"⚠️ Netto in {_sel_j} ist **negativ** ({_de(_jrow['Netto'] / 12)} €/Mon.)! "
                    "Die Ausgaben (Steuern, KV, Sonderausgaben) übersteigen die Einnahmen. "
                    "Kapitalanlage-Pool oder Einnahmen erhöhen, oder Ausgaben reduzieren."
                )
            if "KV_P2" in df_jd.columns and _jrow["KV_P2"] > 0:
                st.caption(
                    f"KV-Aufteilung: P1 {_de(_jrow['KV_P1'] / 12)} €/Mon. "
                    f"| P2 {_de(_jrow['KV_P2'] / 12)} €/Mon."
                )

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

        with st.expander("Rohdaten – Jahresverlauf"):
            st.dataframe(df_jd, use_container_width=True)

        st.caption(
            "⚠️ Simulation auf Basis der Rechtslage 2024. "
            "Solidaritätszuschlag, Kirchensteuer (auf progressive ESt), Sparerpauschbetrag, "
            "Altersentlastungsbetrag (§ 24a EStG) und PV-Kinderstaffelung (§ 55 Abs. 3a SGB XI) "
            "sind berücksichtigt. "
            "Kirchensteuer auf Abgeltungsteuer sowie weitere individuelle Freibeträge "
            "sind nicht modelliert. Steuerberatung empfohlen."
        )

