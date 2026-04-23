"""Rentenberechnungs-Engine – keine Streamlit-Abhängigkeit.

Alle Berechnungen sind Näherungen für Simulationszwecke.
Keine Haftung für steuerliche oder rechtliche Entscheidungen.
"""

from __future__ import annotations
from dataclasses import dataclass, replace
import numpy as np

# ── Konstanten ────────────────────────────────────────────────────────────────
RENTENWERT_2024 = 39.32        # €/Punkt West, Stand 01.07.2024
GRUNDFREIBETRAG_2024 = 11_604  # €
WERBUNGSKOSTEN_PAUSCHBETRAG = 102   # € Pauschbetrag für Rentner
SONDERAUSGABEN_PAUSCHBETRAG = 36    # €
AKTUELLES_JAHR = 2025


# ── Steuerformeln (§ 32a EStG Grundtarif 2024) ────────────────────────────────

def einkommensteuer(zvE: float) -> float:
    """Einkommensteuer nach Grundtarif 2024. zvE = zu versteuerndes Einkommen."""
    if zvE <= 11_604:
        return 0.0
    if zvE <= 17_005:
        y = (zvE - 11_604) / 10_000
        return (928.37 * y + 1_400) * y
    if zvE <= 66_760:
        z = (zvE - 17_005) / 10_000
        return (176.64 * z + 2_397) * z + 1_025.38
    if zvE <= 277_825:
        return 0.42 * zvE - 9_972.98
    return 0.45 * zvE - 18_307.73


def besteuerungsanteil(eintritt_jahr: int) -> float:
    """Besteuerungsanteil der gesetzlichen Rente nach § 22 Nr. 1 Satz 3 EStG (JStG 2022)."""
    if eintritt_jahr <= 2005:
        return 0.50
    if eintritt_jahr <= 2020:
        return min(0.50 + (eintritt_jahr - 2005) * 0.02, 0.80)
    if eintritt_jahr == 2021:
        return 0.81
    if eintritt_jahr == 2022:
        return 0.82
    # Ab 2023: nur noch +0,5 % p.a.
    return min(0.825 + (eintritt_jahr - 2023) * 0.005, 1.0)


# ── Datenprofil ───────────────────────────────────────────────────────────────

@dataclass
class Profil:
    geburtsjahr: int = 1970
    renteneintritt_alter: int = 67
    aktuelle_punkte: float = 25.0
    punkte_pro_jahr: float = 1.2
    zusatz_monatlich: float = 0.0      # bAV / Riester / Rürup – monatliche Auszahlung in Rente
    sparkapital: float = 50_000.0      # bereits angespartes Kapital
    sparrate: float = 500.0            # monatliche Sparrate bis Rente
    rendite_pa: float = 0.05           # Rendite auf Sparkapital p.a.
    rentenanpassung_pa: float = 0.02   # jährliche Rentenanpassung
    krankenversicherung: str = "GKV"   # "GKV" oder "PKV"
    pkv_beitrag: float = 500.0         # €/Monat, nur bei PKV
    gkv_zusatzbeitrag: float = 0.017   # kassenindividueller Zusatzbeitrag
    kinder: bool = True

    @property
    def aktuelles_alter(self) -> int:
        return AKTUELLES_JAHR - self.geburtsjahr

    @property
    def eintritt_jahr(self) -> int:
        return self.geburtsjahr + self.renteneintritt_alter

    @property
    def jahre_bis_rente(self) -> int:
        return max(0, self.renteneintritt_alter - self.aktuelles_alter)


# ── Ergebnis-Dataclass ────────────────────────────────────────────────────────

@dataclass
class RentenErgebnis:
    brutto_monatlich: float
    steuer_monatlich: float
    kv_monatlich: float
    netto_monatlich: float
    kapital_bei_renteneintritt: float
    besteuerungsanteil: float
    effektiver_steuersatz: float
    gesamtpunkte: float
    brutto_gesetzlich: float
    rentenwert_angepasst: float
    zvE_jahres: float
    jahressteuer: float


# ── Kernberechnungen ──────────────────────────────────────────────────────────

def kapitalwachstum(kapital: float, sparrate: float, rendite_pa: float, jahre: int) -> float:
    """Endkapital nach `jahre` Jahren mit monatlicher Sparrate und Zinseszins."""
    if jahre <= 0:
        return kapital
    monate = jahre * 12
    r_m = rendite_pa / 12
    endwert = kapital * (1 + rendite_pa) ** jahre
    if r_m > 0:
        endwert += sparrate * ((1 + r_m) ** monate - 1) / r_m
    else:
        endwert += sparrate * monate
    return endwert


def berechne_rente(p: Profil) -> RentenErgebnis:
    # Gesetzliche Rente
    gesamtpunkte = p.aktuelle_punkte + p.punkte_pro_jahr * p.jahre_bis_rente
    rentenwert = RENTENWERT_2024 * (1 + p.rentenanpassung_pa) ** p.jahre_bis_rente
    brutto_gesetzlich = gesamtpunkte * rentenwert
    brutto_total = brutto_gesetzlich + p.zusatz_monatlich

    # Sparkapital
    kapital = kapitalwachstum(p.sparkapital, p.sparrate, p.rendite_pa, p.jahre_bis_rente)

    # Einkommensteuer
    ba = besteuerungsanteil(p.eintritt_jahr)
    zvE = max(
        0.0,
        brutto_total * 12 * ba
        - WERBUNGSKOSTEN_PAUSCHBETRAG
        - SONDERAUSGABEN_PAUSCHBETRAG,
    )
    jahressteuer = einkommensteuer(zvE)
    steuer_monatlich = jahressteuer / 12

    # Krankenversicherung
    if p.krankenversicherung == "PKV":
        kv = p.pkv_beitrag
    else:
        kv_satz = 0.073 + p.gkv_zusatzbeitrag / 2
        pv_satz = 0.034 if p.kinder else 0.040
        kv = brutto_total * (kv_satz + pv_satz)

    netto = brutto_total - steuer_monatlich - kv
    eff_st = steuer_monatlich / brutto_total if brutto_total > 0 else 0.0

    return RentenErgebnis(
        brutto_monatlich=brutto_total,
        steuer_monatlich=steuer_monatlich,
        kv_monatlich=kv,
        netto_monatlich=netto,
        kapital_bei_renteneintritt=kapital,
        besteuerungsanteil=ba,
        effektiver_steuersatz=eff_st,
        gesamtpunkte=gesamtpunkte,
        brutto_gesetzlich=brutto_gesetzlich,
        rentenwert_angepasst=rentenwert,
        zvE_jahres=zvE,
        jahressteuer=jahressteuer,
    )


def simuliere_szenarien(p: Profil) -> dict[str, RentenErgebnis]:
    """Pessimistisch / Neutral / Optimistisch – Rentenanpassung und Kapitalrendite."""
    return {
        "Pessimistisch": berechne_rente(replace(p, rentenanpassung_pa=0.01, rendite_pa=0.03)),
        "Neutral":       berechne_rente(replace(p, rentenanpassung_pa=p.rentenanpassung_pa,
                                                    rendite_pa=p.rendite_pa)),
        "Optimistisch":  berechne_rente(replace(p, rentenanpassung_pa=0.03, rendite_pa=0.07)),
    }


# ── Ehegatten-Splitting ───────────────────────────────────────────────────────

def einkommensteuer_splitting(zvE_gesamt: float) -> float:
    """Splittingtarif (§ 32a Abs. 5 EStG): 2 × ESt(zvE / 2)."""
    return 2.0 * einkommensteuer(zvE_gesamt / 2.0)


def berechne_haushalt(
    erg1: RentenErgebnis,
    erg2: "RentenErgebnis | None",
    veranlagung: str,  # "Zusammen" | "Getrennt"
) -> dict:
    """Haushalts-Nettoeinkommen mit optionalem Splitting."""
    if erg2 is None:
        return {
            "netto_gesamt": erg1.netto_monatlich,
            "steuer_gesamt": erg1.steuer_monatlich,
            "kv_gesamt": erg1.kv_monatlich,
            "brutto_gesamt": erg1.brutto_monatlich,
            "steuerersparnis_splitting": 0.0,
        }
    brutto = erg1.brutto_monatlich + erg2.brutto_monatlich
    kv = erg1.kv_monatlich + erg2.kv_monatlich
    steuer_getrennt = erg1.steuer_monatlich + erg2.steuer_monatlich

    if veranlagung == "Zusammen":
        zvE_gesamt = erg1.zvE_jahres + erg2.zvE_jahres
        steuer_zusammen = einkommensteuer_splitting(zvE_gesamt) / 12
        ersparnis = max(0.0, steuer_getrennt - steuer_zusammen)
        steuer = steuer_zusammen
    else:
        steuer = steuer_getrennt
        ersparnis = 0.0

    return {
        "netto_gesamt": brutto - steuer - kv,
        "steuer_gesamt": steuer,
        "kv_gesamt": kv,
        "brutto_gesamt": brutto,
        "steuerersparnis_splitting": ersparnis,
    }


# ── Vorsorge-Bausteine ────────────────────────────────────────────────────────

@dataclass
class VorsorgeProdukt:
    id: str
    typ: str                   # "bAV" | "PrivateRente" | "Riester" | "LV"
    name: str
    person: str                # "Person 1" | "Person 2"
    max_einmalzahlung: float   # Maximale Einmalauszahlung ab frühestem Startdatum
    max_monatsrente: float     # Maximale monatliche Rente ab frühestem Startdatum
    laufzeit_jahre: int        # 0 = lebenslang, sonst befristet
    fruehestes_startjahr: int  # Frühestes mögliches Startjahr
    spaetestes_startjahr: int  # Spätestes mögliches Startjahr
    aufschub_rendite: float    # Verzinsung je Aufschubjahr (0.02 = 2 % p.a.)

    @property
    def ist_lebensversicherung(self) -> bool:
        return self.typ == "LV"


def _annuitaet(kapital: float, rendite_pa: float, jahre: int) -> float:
    """Monatliche Entnahme-Annuität: Kapital wird über `jahre` aufgebraucht."""
    if jahre <= 0 or kapital <= 0:
        return 0.0
    r_m = rendite_pa / 12
    n = jahre * 12
    if r_m > 0:
        return kapital * r_m / (1 - (1 + r_m) ** (-n))
    return kapital / n


def _wert_bei_start(prod: VorsorgeProdukt, startjahr: int) -> tuple[float, float]:
    """Einmalbetrag und Monatsrente nach Aufschubverzinsung bis `startjahr`."""
    deferral = max(0, startjahr - prod.fruehestes_startjahr)
    f = (1 + prod.aufschub_rendite) ** deferral
    return prod.max_einmalzahlung * f, prod.max_monatsrente * f


def vergleiche_produkt(
    produkt: VorsorgeProdukt,
    rendite_pa: float,
    horizon_jahre: int,
) -> dict:
    """Vergleicht Einmal / Monatlich / Kombiniert für ein Produkt am frühesten Startdatum."""
    H = horizon_jahre
    K = produkt.max_einmalzahlung
    M = produkt.max_monatsrente if produkt.max_monatsrente > 0 else _annuitaet(K, rendite_pa, H)
    lz = produkt.laufzeit_jahre if produkt.laufzeit_jahre > 0 else H
    effective_lz = min(lz, H)

    m_einmal = _annuitaet(K, rendite_pa, H)
    t_einmal = m_einmal * 12 * H
    t_monatlich = M * 12 * effective_lz
    m_monatlich = M

    if not produkt.ist_lebensversicherung and produkt.max_monatsrente > 0:
        xs = np.linspace(0.0, 1.0, 101)
        totale = [
            _annuitaet(K * x, rendite_pa, H) * 12 * H + M * (1 - x) * 12 * effective_lz
            for x in xs
        ]
        best_idx = int(np.argmax(totale))
        best_x = float(xs[best_idx])
        t_komb = float(totale[best_idx])
        m_komb = _annuitaet(K * best_x, rendite_pa, H) + M * (1 - best_x)
    else:
        best_x = 1.0
        t_komb = t_einmal
        m_komb = m_einmal

    bestes = "einmal" if (produkt.ist_lebensversicherung or produkt.max_monatsrente <= 0) else max(
        {"einmal": t_einmal, "monatlich": t_monatlich, "kombiniert": t_komb},
        key=lambda k: {"einmal": t_einmal, "monatlich": t_monatlich, "kombiniert": t_komb}[k],
    )
    return {
        "einmal":     {"monatlich": m_einmal,    "total": t_einmal},
        "monatlich":  {"monatlich": m_monatlich, "total": t_monatlich},
        "kombiniert": {"monatlich": m_komb,      "total": t_komb, "anteil": best_x},
        "bestes": bestes,
    }


# ── Steueroptimierung Vertragsauszahlungen ────────────────────────────────────

def _netto_ueber_horizont(
    profil: Profil,
    ergebnis: RentenErgebnis,
    entscheidungen: list,   # [(VorsorgeProdukt, startjahr: int, einmal_anteil: float)]
    horizont_jahre: int,
) -> tuple[float, list[dict]]:
    """
    Simuliert das Netto-Einkommen Jahr für Jahr über `horizont_jahre` ab Renteneintritt.
    Lump sums werden im Startjahr als Sondereinkommen gewertet.
    Alle Vertragseinnahmen werden vereinfacht voll besteuert (konservativ, korrekt für bAV).
    """
    ba = ergebnis.besteuerungsanteil
    gesetzl_mono = ergebnis.brutto_monatlich
    ist_pkv = profil.krankenversicherung == "PKV"
    kv_rate = (0.073 + profil.gkv_zusatzbeitrag / 2) + (0.034 if profil.kinder else 0.040)

    total_netto = 0.0
    jahresdaten: list[dict] = []

    for y in range(horizont_jahre):
        jahr = profil.eintritt_jahr + y
        gesetzl_jahres = gesetzl_mono * 12
        mono_jahres = 0.0
        einmal_jahres = 0.0

        for prod, startjahr, anteil in entscheidungen:
            if jahr < startjahr:
                continue
            einmal_wert, mono_wert = _wert_bei_start(prod, startjahr)
            if jahr == startjahr and anteil > 0:
                einmal_jahres += einmal_wert * anteil
            lz = prod.laufzeit_jahre if prod.laufzeit_jahre > 0 else horizont_jahre
            if 0 <= jahr - startjahr < lz and anteil < 1.0:
                mono_jahres += mono_wert * (1 - anteil) * 12

        zvE = max(
            0.0,
            gesetzl_jahres * ba + mono_jahres + einmal_jahres
            - WERBUNGSKOSTEN_PAUSCHBETRAG - SONDERAUSGABEN_PAUSCHBETRAG,
        )
        steuer = einkommensteuer(zvE)
        brutto_mono_ges = gesetzl_mono + (mono_jahres + einmal_jahres) / 12
        kv = profil.pkv_beitrag * 12 if ist_pkv else brutto_mono_ges * 12 * kv_rate
        brutto = gesetzl_jahres + mono_jahres + einmal_jahres
        netto = brutto - steuer - kv
        total_netto += netto
        jahresdaten.append({
            "Jahr": jahr,
            "Brutto (€)": round(brutto),
            "Steuer (€)": round(steuer),
            "KV/PV (€)": round(kv),
            "Netto (€)": round(netto),
        })

    return total_netto, jahresdaten


def optimiere_auszahlungen(
    profil: Profil,
    ergebnis: RentenErgebnis,
    produkte: list,
    horizont_jahre: int,
) -> dict:
    """
    Durchsucht alle Kombinationen aus Startjahr × Auszahlungsart je Vertrag
    und gibt die steuerlich optimale Kombination zurück.

    Startjahre: bis zu 4 gleichmäßig verteilte Punkte im erlaubten Bereich.
    Auszahlungsarten: Einmal (100%), Kombiniert (50/50), Monatlich (0%).
    """
    from itertools import product as iterproduct

    if not produkte:
        return {}

    def optionen(prod: VorsorgeProdukt) -> list[tuple[int, float]]:
        jahre = list(range(prod.fruehestes_startjahr, prod.spaetestes_startjahr + 1))
        # Max 4 Stützstellen für Rechenzeit
        if len(jahre) > 4:
            idx = [0, len(jahre) // 3, 2 * len(jahre) // 3, len(jahre) - 1]
            jahre = [jahre[i] for i in idx]
        anteile = [1.0] if prod.ist_lebensversicherung or prod.max_monatsrente <= 0 \
            else [0.0, 0.5, 1.0]
        return [(j, a) for j in jahre for a in anteile]

    alle_optionen = [optionen(p) for p in produkte]
    bestes_netto = float("-inf")
    beste_entscheidungen: list = []
    alle_ergebnisse: list[dict] = []

    for kombi in iterproduct(*alle_optionen):
        ents = [(produkte[i], kombi[i][0], kombi[i][1]) for i in range(len(produkte))]
        netto, _ = _netto_ueber_horizont(profil, ergebnis, ents, horizont_jahre)
        label = " | ".join(
            f"{produkte[i].name}: "
            f"{'Einmal' if kombi[i][1] == 1.0 else 'Monatlich' if kombi[i][1] == 0.0 else '50/50'} "
            f"ab {kombi[i][0]}"
            for i in range(len(produkte))
        )
        alle_ergebnisse.append({"Kombination": label, "Netto gesamt (€)": round(netto)})
        if netto > bestes_netto:
            bestes_netto = netto
            beste_entscheidungen = ents

    alle_ergebnisse.sort(key=lambda x: x["Netto gesamt (€)"], reverse=True)
    _, jahresdaten = _netto_ueber_horizont(profil, ergebnis, beste_entscheidungen, horizont_jahre)

    ref_mono   = [(p, p.fruehestes_startjahr, 0.0) for p in produkte]
    ref_einmal = [(p, p.fruehestes_startjahr, 1.0) for p in produkte]
    netto_mono,   _ = _netto_ueber_horizont(profil, ergebnis, ref_mono,   horizont_jahre)
    netto_einmal, _ = _netto_ueber_horizont(profil, ergebnis, ref_einmal, horizont_jahre)

    return {
        "bestes_netto":          bestes_netto,
        "beste_entscheidungen":  beste_entscheidungen,
        "jahresdaten":           jahresdaten,
        "top10":                 alle_ergebnisse[:10],
        "netto_alle_monatlich":  netto_mono,
        "netto_alle_einmal":     netto_einmal,
        "anzahl_kombinationen":  len(alle_ergebnisse),
    }


def kapital_vs_rente(kapital: float, rendite_pa: float, laufzeit_jahre: int) -> dict:
    """Monatliche Annuität und Kapitalverlauf bei Verzehr über `laufzeit_jahre`."""
    r_m = rendite_pa / 12
    n = max(1, laufzeit_jahre * 12)
    if r_m > 0:
        monatsrate = kapital * r_m / (1 - (1 + r_m) ** (-n))
    else:
        monatsrate = kapital / n
    verlauf = []
    k = kapital
    for i in range(n + 1):
        verlauf.append({"Monat": i, "Kapital": max(0.0, k)})
        k = k * (1 + r_m) - monatsrate
    return {
        "monatsrate": monatsrate,
        "verlauf": verlauf,
        "gesamtauszahlung": monatsrate * n,
    }
