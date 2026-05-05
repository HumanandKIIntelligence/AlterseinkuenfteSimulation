"""Gemeinsame Hilfsfunktionen für alle Tab-Module."""

from __future__ import annotations

import streamlit as st

from engine import AKTUELLES_JAHR, Profil, RentenErgebnis


def render_zeitstrahl(
    rc: int,
    min_year: int,
    max_year: int,
    default_year: int,
    key_suffix: str,
    label: str = "Betrachtungsjahr",
    help_text: str = "Zeigt projizierte Werte für das gewählte Jahr.",
) -> int:
    """Jahresslider mit automatischer Synchronisation über alle Tabs via rc{rc}_shared_jahr."""
    _shared = f"rc{rc}_shared_jahr"
    _wkey = f"rc{rc}_zeitstrahl{key_suffix}"
    if _shared not in st.session_state:
        st.session_state[_shared] = default_year
    _val = min(max_year, max(min_year, int(st.session_state[_shared])))
    st.session_state[_wkey] = _val

    def _sync():
        st.session_state[_shared] = st.session_state[_wkey]

    return st.slider(label, min_year, max_year, _val, key=_wkey, help=help_text, on_change=_sync)


def _de(v: float, dec: int = 0) -> str:
    s = f"{v:,.{dec}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _actual_startjahr(vp: dict) -> int:
    """Tatsächlich gewähltes Auszahlungs-Startjahr aus dem Vorsorge-Tab.

    Liest rc{_rc}_vp_sels (vom Vorsorge-Tab gespeichert); Fallback: fruehestes_startjahr.
    """
    _rc = st.session_state.get("_rc", 0)
    _sels = st.session_state.get(f"rc{_rc}_vp_sels", {})
    _pid = vp.get("id")
    _sel = _sels.get(_pid) if _pid else None
    if _sel is not None:
        try:
            return int(str(_sel).rsplit("_", 1)[0])
        except (ValueError, IndexError):
            pass
    return int(vp.get("fruehestes_startjahr", AKTUELLES_JAHR))


def _blend_brutto_wf(prof: Profil, jd: list[dict], sel_jahr: int) -> float | None:
    """Monatlich gemitteltes Brutto für das Renteneintritts-Jahr.

    Gibt None zurück wenn kein Blend nötig (Aufrufer nutzt Engine-Wert).
    Formel: (m_vor × Gehalt/Mon. + m_nach × Rente/Mon.) / 12
    """
    if prof.bereits_rentner or sel_jahr != prof.eintritt_jahr:
        return None
    m = getattr(prof, "renteneintritt_monat", 1)
    if m <= 1:
        return None
    by_y = {r["Jahr"]: r for r in jd}
    row_ej   = by_y.get(sel_jahr)
    row_prev = by_y.get(sel_jahr - 1)
    if row_ej is None or row_prev is None:
        return None
    pension_mono = row_ej.get("Src_GesRente", 0.0) / 12
    salary_mono  = row_prev.get("Src_Gehalt", 0.0) / 12
    m_before = m - 1
    m_after  = 12 - m_before
    return (m_before * salary_mono + m_after * pension_mono) / 12


def _vorsorge_non_bav_einzeln(produkte: list[dict], jahr: int,
                               person: str | None = None) -> list[tuple[str, float]]:
    """Liste von (Name, €/Mon.) für aktive nicht-bAV Vorsorge-Beiträge im Jahr."""
    result: list[tuple[str, float]] = []
    for vp in produkte:
        if vp.get("typ") == "bAV":
            continue
        if person is not None and vp.get("person", "Person 1") != person:
            continue
        je = float(vp.get("jaehrl_einzahlung", 0.0))
        if je <= 0.0:
            continue
        if vp.get("typ") != "LV":
            if _actual_startjahr(vp) <= jahr:
                continue
        bbj = int(vp.get("beitragsbefreiung_jahr", 0))
        if bbj > 0 and jahr >= bbj:
            continue
        dyn = float(vp.get("jaehrl_dynamik", 0.0))
        monatlich = je * (1.0 + dyn) ** max(0, jahr - AKTUELLES_JAHR) / 12.0
        result.append((vp.get("name", "Vorsorge"), monatlich))
    return result


def _vorsorge_non_bav_monatlich(produkte: list[dict], jahr: int,
                                 person: str | None = None) -> float:
    return sum(b for _, b in _vorsorge_non_bav_einzeln(produkte, jahr, person=person))


def _vorsorge_bav_monatlich(produkte: list[dict], jahr: int,
                             person: str | None = None) -> float:
    """Monatliche bAV-Beiträge (AN-Anteil) für das gegebene Jahr."""
    total = 0.0
    for vp in produkte:
        if vp.get("typ") != "bAV":
            continue
        if person is not None and vp.get("person", "Person 1") != person:
            continue
        je = float(vp.get("jaehrl_einzahlung", 0.0))
        if je <= 0.0:
            continue
        if _actual_startjahr(vp) <= jahr:
            continue
        bbj = int(vp.get("beitragsbefreiung_jahr", 0))
        if bbj > 0 and jahr >= bbj:
            continue
        dyn = float(vp.get("jaehrl_dynamik", 0.0))
        total += je * (1.0 + dyn) ** max(0, jahr - AKTUELLES_JAHR) / 12.0
    return total


def _eink_label(profil: Profil, sel_jahr: int) -> str:
    in_rente = profil.bereits_rentner or sel_jahr >= profil.eintritt_jahr
    if not in_rente:
        return "Brutto"
    return "Pension" if profil.ist_pensionaer else "Rente"


def _netto_label(eink_lbl: str) -> str:
    return {"Rente": "Nettorente", "Pension": "Nettopension"}.get(eink_lbl, "Nettoeinkommen")


def _vorsorge_ausz_breakdown(row: dict) -> tuple[float, str]:
    """Vorsorgeauszahlungen monatlich aus einem jahresdaten-Row + Aufschlüsselung als Help-Text.

    Enthält: bAV, Riester/PrivRV/LV (monatlich), Versorgungsbezüge, DUV/BUV,
    Einmalauszahlungen (Jahresbetrag ÷ 12), Kapitalverzehr.
    Nicht enthalten: gesetzliche Rente, Gehalt, Mieteinnahmen.
    """
    _fields = [
        ("bAV P1",              "Src_bAV_P1"),
        ("Riester/PrivRV P1",   "Src_Riester_P1"),
        ("bAV P2",              "Src_bAV_P2"),
        ("Riester/PrivRV P2",   "Src_Riester_P2"),
        ("Versorgungsbez.",     "Src_Versorgung"),
        ("DUV",                 "Src_DUV_P1"),
        ("BUV",                 "Src_BUV_P1"),
        ("Einmalausz. (÷12)",   "Src_Einmal"),
        ("Pool-Einzahlung (÷12)", "Src_KapInjektion"),
        ("Kapitalverzehr",      "Src_Kapitalverzehr"),
    ]
    total = 0.0
    parts: list[str] = []
    for label, key in _fields:
        v = row.get(key, 0) / 12
        if v > 0.5:
            total += v
            parts.append(f"{label}: {_de(v)} €/Mon.")
    detail = (" | ".join(parts)) if parts else "Keine Vorsorgeauszahlungen in diesem Jahr."
    help_text = (
        f"Monatliche Einnahmen aus Vorsorgeprodukten: {detail}\n\n"
        "Enthält:\n"
        "• bAV: Betriebliche Altersversorgung (laufende Monatsrente)\n"
        "• Riester / PrivRV / LV: Private Rentenversicherungen und Lebensversicherungen (Monatsrente, Ertragsanteil-besteuert)\n"
        "• Versorgungsbez.: Zusatzversorgung aus Versorgungswerk, Pensionskasse oder arbeitgeberfinanzierten Direktzusagen "
        "(§ 19 Abs. 2 EStG; Versorgungsfreibetrag anwendbar)\n"
        "• DUV / BUV: Dienstunfähigkeits- bzw. Berufsunfähigkeitsrente (Ertragsanteil-besteuert, nicht KVdR-pflichtig)\n"
        "• Einmalausz. (÷ 12): Kapitalabfindung aus Vorsorgeverträgen (kein Pool), gleichmäßig auf 12 Monate verteilt\n"
        "• Pool-Einzahlung (÷ 12): Brutto-Einzahlung in den Kapitalanlage-Pool im Injektionsjahr "
        "(z. B. LV-Ablaufleistung, Erbschaft) – steuerlich meist zu 50 % als Ertrag progressiv besteuert; "
        "der Nettobetrag nach Steuern und KV geht in den Pool und wird in den Folgejahren "
        "als Annuität entnommen (→ Kapitalverzehr)\n"
        "• Kapitalverzehr: Planmäßige monatliche Entnahme aus dem Kapitalanlage-Pool – "
        "Gewinnanteile der Entnahmen unterliegen der Abgeltungsteuer (25 %)\n\n"
        "Nicht enthalten: gesetzl. Rente/Pension, Gehalt, Mieteinnahmen."
    )
    return total, help_text


def _kv_pv_split(profil: Profil, kv_gesamt: float,
                  ergebnis: RentenErgebnis | None = None) -> tuple[float, float]:
    """Gibt (GKV-Anteil, PV-Anteil) des monatlichen KV-Beitrags zurück."""
    if ergebnis is not None and (ergebnis.kv_gkv_monatlich + ergebnis.kv_pv_monatlich) > 0:
        return ergebnis.kv_gkv_monatlich, ergebnis.kv_pv_monatlich
    if profil.krankenversicherung == "PKV":
        return kv_gesamt, 0.0
    _freiwillig = profil.ist_pensionaer or not profil.kvdr_pflicht
    if _freiwillig:
        _kv_rate = 0.146 + profil.gkv_zusatzbeitrag
        _pv_rate = 0.034 if profil.kinder else 0.040
    else:
        _kv_rate = 0.073 + profil.gkv_zusatzbeitrag / 2
        _pv_rate = 0.017 if profil.kinder else 0.023
    _total = _kv_rate + _pv_rate
    if _total == 0:
        return 0.0, 0.0
    return kv_gesamt * _kv_rate / _total, kv_gesamt * _pv_rate / _total
