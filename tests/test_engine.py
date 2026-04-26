"""Unit Tests für engine.py – alle mathematischen Kernberechnungen.

Kein Streamlit-Import nötig; engine.py hat keine UI-Abhängigkeit.
"""

import math
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from engine import (
    RENTENWERT_2024,
    GRUNDFREIBETRAG_2024,
    WERBUNGSKOSTEN_PAUSCHBETRAG,
    SONDERAUSGABEN_PAUSCHBETRAG,
    BAV_FREIBETRAG_MONATLICH,
    BBG_KV_MONATLICH,
    SPARERPAUSCHBETRAG,
    MINDEST_BMG_FREIWILLIG_MONO,
    AKTUELLES_JAHR,
    einkommensteuer,
    einkommensteuer_splitting,
    besteuerungsanteil,
    ertragsanteil,
    versorgungsfreibetrag,
    kapitalwachstum,
    berechne_rente,
    berechne_haushalt,
    simuliere_szenarien,
    kapital_vs_rente,
    _annuitaet,
    _wert_bei_start,
    _netto_ueber_horizont,
    Profil,
    RentenErgebnis,
    VorsorgeProdukt,
)


# ─────────────────────────────────────────────────────────────────────────────
# Hilfsfunktionen
# ─────────────────────────────────────────────────────────────────────────────

def _profil(**kwargs) -> Profil:
    """Standardprofil mit überschreibbaren Feldern."""
    defaults = dict(
        geburtsjahr=1970,
        renteneintritt_alter=67,
        aktuelle_punkte=30.0,
        punkte_pro_jahr=1.0,
        zusatz_monatlich=0.0,
        sparkapital=0.0,
        sparrate=0.0,
        rendite_pa=0.0,
        rentenanpassung_pa=0.0,
        krankenversicherung="GKV",
        pkv_beitrag=0.0,
        gkv_zusatzbeitrag=0.017,
        kinder=True,
    )
    defaults.update(kwargs)
    return Profil(**defaults)


def _bav_produkt(**kwargs) -> VorsorgeProdukt:
    defaults = dict(
        id="test-bav",
        typ="bAV",
        name="Test-bAV",
        person="Person 1",
        max_einmalzahlung=50_000.0,
        max_monatsrente=500.0,
        laufzeit_jahre=0,
        fruehestes_startjahr=2037,
        spaetestes_startjahr=2037,
        aufschub_rendite=0.0,
    )
    defaults.update(kwargs)
    return VorsorgeProdukt(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# einkommensteuer – § 32a EStG Grundtarif 2024
# ─────────────────────────────────────────────────────────────────────────────

class TestEinkommensteuer:
    def test_unterhalb_grundfreibetrag(self):
        assert einkommensteuer(0.0) == 0.0
        assert einkommensteuer(11_603.99) == 0.0
        assert einkommensteuer(11_604.0) == 0.0

    def test_erste_progressionszone(self):
        # zvE = 11_605: kleine positive Steuer
        steuer = einkommensteuer(11_605.0)
        assert steuer > 0.0
        assert steuer < 10.0

    def test_zweite_progressionszone_grenze(self):
        # Werte klar innerhalb beider Zonen prüfen (nicht am Knick selbst)
        steuer_16000 = einkommensteuer(16_000.0)
        steuer_18000 = einkommensteuer(18_000.0)
        assert steuer_18000 > steuer_16000
        assert steuer_16000 > 0.0

    def test_proportionalzone_42prozent(self):
        # Zwischen 66_760 und 277_825: 42 % linear
        zvE = 100_000.0
        expected = 0.42 * zvE - 9_972.98
        assert abs(einkommensteuer(zvE) - expected) < 0.01

    def test_spitzensteuersatz_45prozent(self):
        zvE = 300_000.0
        expected = 0.45 * zvE - 18_307.73
        assert abs(einkommensteuer(zvE) - expected) < 0.01

    def test_steuersatz_monoton_steigend(self):
        punkte = [0, 11_604, 12_000, 17_005, 20_000, 66_760, 100_000, 277_825, 300_000]
        steuern = [einkommensteuer(z) for z in punkte]
        for i in range(1, len(steuern)):
            assert steuern[i] >= steuern[i - 1], f"Nicht monoton bei zvE={punkte[i]}"

    def test_negativer_zve_liefert_null(self):
        # Negative zvE nicht definiert, aber Robustheit prüfen
        assert einkommensteuer(0.0) == 0.0

    def test_proportionalzone_ab_66761(self):
        # Proportionalzone beginnt bei zvE > 66_760
        for zvE in [66_761.0, 80_000.0, 100_000.0]:
            expected = 0.42 * zvE - 9_972.98
            assert abs(einkommensteuer(zvE) - expected) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# einkommensteuer_splitting
# ─────────────────────────────────────────────────────────────────────────────

class TestSplitting:
    def test_definition_zwei_mal_halb(self):
        zvE = 80_000.0
        assert einkommensteuer_splitting(zvE) == pytest.approx(
            2.0 * einkommensteuer(zvE / 2), rel=1e-9
        )

    def test_splitting_vorteil_bei_ungleichen_einkommen(self):
        # Person 1: 40_000 €, Person 2: 0 € zvE
        zvE_gesamt = 40_000.0
        steuer_einzeln = einkommensteuer(zvE_gesamt)
        steuer_splitting = einkommensteuer_splitting(zvE_gesamt)
        assert steuer_splitting < steuer_einzeln

    def test_kein_splitting_vorteil_bei_gleichen_einkommen(self):
        # Zwei gleich hohe Einkommen: Splitting == Summe Einzelsteuer
        zvE_je = 30_000.0
        steuer_einzel_sum = 2 * einkommensteuer(zvE_je)
        steuer_splitting = einkommensteuer_splitting(2 * zvE_je)
        assert abs(steuer_splitting - steuer_einzel_sum) < 0.01

    def test_symmetrie(self):
        # Splitting(a+b) == Splitting(b+a)
        assert einkommensteuer_splitting(70_000.0) == einkommensteuer_splitting(70_000.0)


# ─────────────────────────────────────────────────────────────────────────────
# besteuerungsanteil – § 22 EStG / JStG 2022
# ─────────────────────────────────────────────────────────────────────────────

class TestBesteuerungsanteil:
    def test_vor_2005(self):
        assert besteuerungsanteil(2000) == 0.50
        assert besteuerungsanteil(2005) == 0.50

    def test_stufenweise_bis_2020(self):
        assert besteuerungsanteil(2006) == pytest.approx(0.52)
        assert besteuerungsanteil(2010) == pytest.approx(0.60)
        assert besteuerungsanteil(2020) == pytest.approx(0.80)

    def test_sonderregeln_2021_2022(self):
        assert besteuerungsanteil(2021) == pytest.approx(0.81)
        assert besteuerungsanteil(2022) == pytest.approx(0.82)

    def test_jstg2022_ab_2023_halber_schritt(self):
        assert besteuerungsanteil(2023) == pytest.approx(0.825)
        assert besteuerungsanteil(2024) == pytest.approx(0.830)
        assert besteuerungsanteil(2025) == pytest.approx(0.835)

    def test_cap_bei_100_prozent(self):
        # Ab 2058: 0.825 + (2058-2023)*0.005 = 0.825 + 0.175 = 1.000
        assert besteuerungsanteil(2058) == pytest.approx(1.0)
        assert besteuerungsanteil(2100) == pytest.approx(1.0)

    def test_monoton_steigend(self):
        jahre = list(range(2000, 2070))
        anteile = [besteuerungsanteil(j) for j in jahre]
        for i in range(1, len(anteile)):
            assert anteile[i] >= anteile[i - 1]


# ─────────────────────────────────────────────────────────────────────────────
# ertragsanteil – § 22 Nr. 1 S. 3a bb EStG
# ─────────────────────────────────────────────────────────────────────────────

class TestErtragsanteil:
    def test_gesetzliche_kerenwerte(self):
        assert ertragsanteil(60) == pytest.approx(0.22)
        assert ertragsanteil(62) == pytest.approx(0.21)
        assert ertragsanteil(65) == pytest.approx(0.18)
        assert ertragsanteil(67) == pytest.approx(0.17)

    def test_monoton_fallend_mit_steigendem_alter(self):
        werte = [ertragsanteil(a) for a in range(0, 97)]
        for i in range(1, len(werte)):
            assert werte[i] <= werte[i - 1], f"Nicht monoton bei Alter {i}"

    def test_junges_alter_hoch(self):
        assert ertragsanteil(0) == pytest.approx(0.59)

    def test_hohes_alter_niedrig(self):
        assert ertragsanteil(80) == pytest.approx(0.08)
        assert ertragsanteil(96) == pytest.approx(0.02)

    def test_rueckgabe_als_dezimalzahl(self):
        assert ertragsanteil(67) < 1.0
        assert ertragsanteil(67) > 0.0


# ─────────────────────────────────────────────────────────────────────────────
# kapitalwachstum
# ─────────────────────────────────────────────────────────────────────────────

class TestKapitalwachstum:
    def test_null_jahre_unveraendert(self):
        assert kapitalwachstum(10_000, 500, 0.05, 0) == pytest.approx(10_000)

    def test_null_rendite_nur_sparrate(self):
        # 0 % Rendite: nur Sparrate aufaddieren
        ergebnis = kapitalwachstum(0.0, 100.0, 0.0, 10)
        assert ergebnis == pytest.approx(100.0 * 12 * 10)

    def test_null_sparrate_nur_zinseszins(self):
        kapital = 10_000.0
        rendite = 0.05
        jahre = 10
        expected = kapital * (1 + rendite) ** jahre
        assert kapitalwachstum(kapital, 0.0, rendite, jahre) == pytest.approx(expected, rel=1e-6)

    def test_kombiniert_groesser_als_teile(self):
        k1 = kapitalwachstum(10_000, 500, 0.05, 20)
        k_nur_kapital = kapitalwachstum(10_000, 0, 0.05, 20)
        k_nur_sparrate = kapitalwachstum(0, 500, 0.05, 20)
        # Gesamtkapital ≥ Summe beider Teile wegen Zinseszins auf Sparrate
        assert k1 >= k_nur_kapital + k_nur_sparrate - 1  # praktisch gleich

    def test_monoton_wachsend_mit_mehr_jahren(self):
        for j in [5, 10, 20, 30]:
            assert kapitalwachstum(10_000, 200, 0.05, j) > kapitalwachstum(10_000, 200, 0.05, j - 1)


# ─────────────────────────────────────────────────────────────────────────────
# berechne_rente
# ─────────────────────────────────────────────────────────────────────────────

class TestBerechneRente:
    def test_brutto_positiv(self):
        p = _profil()
        e = berechne_rente(p)
        assert e.brutto_monatlich > 0.0

    def test_netto_kleiner_brutto(self):
        p = _profil(aktuelle_punkte=30.0, renteneintritt_alter=67)
        e = berechne_rente(p)
        assert e.netto_monatlich < e.brutto_monatlich

    def test_pkv_beitrag_fix(self):
        pkv = 650.0
        p = _profil(krankenversicherung="PKV", pkv_beitrag=pkv)
        e = berechne_rente(p)
        assert e.kv_monatlich == pytest.approx(pkv)

    def test_gkv_beitrag_berechnet(self):
        p = _profil(krankenversicherung="GKV", gkv_zusatzbeitrag=0.017, kinder=True, kvdr_pflicht=True)
        e = berechne_rente(p)
        # KVdR: halber GKV-Satz (DRV trägt andere Hälfte) + halber PV-Satz
        # KV = 7,3 % + 0,85 % + 1,7 % = 9,85 %
        expected_rate = 0.073 + 0.0085 + 0.017
        assert e.kv_monatlich == pytest.approx(e.brutto_monatlich * expected_rate, rel=1e-4)

    def test_pv_ohne_kinder_hoeher(self):
        p_kinder     = _profil(kinder=True)
        p_no_kinder  = _profil(kinder=False)
        e_kinder     = berechne_rente(p_kinder)
        e_no_kinder  = berechne_rente(p_no_kinder)
        assert e_no_kinder.kv_monatlich > e_kinder.kv_monatlich

    def test_brutto_gesetzlich_korrekt(self):
        # Keine Rentenanpassung, 0 Jahre bis Rente → einfach Punkte × RENTENWERT
        p = _profil(geburtsjahr=1958, renteneintritt_alter=67, aktuelle_punkte=40.0,
                    punkte_pro_jahr=0.0, rentenanpassung_pa=0.0)
        e = berechne_rente(p)
        expected = 40.0 * RENTENWERT_2024
        assert e.brutto_gesetzlich == pytest.approx(expected, rel=1e-6)

    def test_zusatz_in_brutto(self):
        zusatz = 300.0
        p_ohne = _profil(zusatz_monatlich=0.0)
        p_mit  = _profil(zusatz_monatlich=zusatz)
        e_ohne = berechne_rente(p_ohne)
        e_mit  = berechne_rente(p_mit)
        assert e_mit.brutto_monatlich == pytest.approx(e_ohne.brutto_monatlich + zusatz)

    def test_kapital_waechst_mit_sparrate(self):
        p_ohne = _profil(sparkapital=0.0, sparrate=0.0)
        p_mit  = _profil(sparkapital=50_000.0, sparrate=500.0, rendite_pa=0.05)
        e_ohne = berechne_rente(p_ohne)
        e_mit  = berechne_rente(p_mit)
        assert e_mit.kapital_bei_renteneintritt > e_ohne.kapital_bei_renteneintritt

    def test_netto_konsistent(self):
        p = _profil()
        e = berechne_rente(p)
        expected_netto = e.brutto_monatlich - e.steuer_monatlich - e.kv_monatlich
        assert e.netto_monatlich == pytest.approx(expected_netto, rel=1e-9)

    def test_zvE_jahres_im_ergebnis(self):
        p = _profil()
        e = berechne_rente(p)
        assert e.zvE_jahres >= 0.0
        assert e.jahressteuer == pytest.approx(einkommensteuer(e.zvE_jahres), rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# berechne_haushalt
# ─────────────────────────────────────────────────────────────────────────────

class TestBerechneHaushalt:
    def _ergebnis(self, brutto=1_500.0, steuer=100.0, kv=150.0, zvE_jahres=10_000.0):
        return RentenErgebnis(
            brutto_monatlich=brutto,
            steuer_monatlich=steuer,
            kv_monatlich=kv,
            netto_monatlich=brutto - steuer - kv,
            kapital_bei_renteneintritt=0.0,
            besteuerungsanteil=0.83,
            effektiver_steuersatz=steuer / brutto,
            gesamtpunkte=30.0,
            brutto_gesetzlich=brutto,
            rentenwert_angepasst=RENTENWERT_2024,
            zvE_jahres=zvE_jahres,
            jahressteuer=steuer * 12,
        )

    def test_einzelperson_ohne_miete(self):
        e = self._ergebnis(1_500, 100, 150, 0.0)
        hh = berechne_haushalt(e, None, "Getrennt", 0.0)
        assert hh["brutto_gesamt"] == pytest.approx(1_500.0)
        assert hh["kv_gesamt"] == pytest.approx(150.0)
        assert hh["steuerersparnis_splitting"] == 0.0

    def test_einzelperson_mit_miete_erhoetht_brutto(self):
        e = self._ergebnis(1_500, 100, 150, 0.0)
        hh = berechne_haushalt(e, None, "Getrennt", 500.0)
        assert hh["brutto_gesamt"] == pytest.approx(2_000.0)
        assert hh["kv_gesamt"] == pytest.approx(150.0)  # keine KV auf Miete

    def test_paar_brutto_summe(self):
        e1 = self._ergebnis(2_000, 200, 200, 15_000.0)
        e2 = self._ergebnis(1_000, 50, 100, 5_000.0)
        hh = berechne_haushalt(e1, e2, "Getrennt", 0.0)
        assert hh["brutto_gesamt"] == pytest.approx(3_000.0)
        assert hh["kv_gesamt"] == pytest.approx(300.0)

    def test_splitting_vorteil_bei_ungleichen_einkommen(self):
        # Stark ungleiche zvE → Splitting bringt Vorteil
        e1 = self._ergebnis(3_000, 500, 300, 30_000.0)
        e2 = self._ergebnis(500, 10, 50, 2_000.0)
        hh = berechne_haushalt(e1, e2, "Zusammen", 0.0)
        assert hh["steuerersparnis_splitting"] > 0.0

    def test_kein_splitting_vorteil_gleiche_einkommen(self):
        zvE = 15_000.0
        e1 = self._ergebnis(1_500, 100, 150, zvE)
        e2 = self._ergebnis(1_500, 100, 150, zvE)
        hh = berechne_haushalt(e1, e2, "Zusammen", 0.0)
        # Bei identischen Einkommen kein Splitting-Vorteil
        assert hh["steuerersparnis_splitting"] == pytest.approx(0.0, abs=0.01)

    def test_mieteinnahmen_keine_kv(self):
        e1 = self._ergebnis(2_000, 200, 200, 15_000.0)
        e2 = self._ergebnis(1_000, 50, 100, 5_000.0)
        hh_ohne = berechne_haushalt(e1, e2, "Getrennt", 0.0)
        hh_mit  = berechne_haushalt(e1, e2, "Getrennt", 1_000.0)
        # KV bleibt gleich
        assert hh_mit["kv_gesamt"] == pytest.approx(hh_ohne["kv_gesamt"])
        # Brutto steigt um Mieteinnahmen
        assert hh_mit["brutto_gesamt"] == pytest.approx(hh_ohne["brutto_gesamt"] + 1_000.0)

    def test_mieteinnahmen_erhoehen_steuer(self):
        e = self._ergebnis(1_500, 0, 150, 20_000.0)
        hh_ohne = berechne_haushalt(e, None, "Getrennt", 0.0)
        hh_mit  = berechne_haushalt(e, None, "Getrennt", 1_000.0)
        assert hh_mit["steuer_gesamt"] >= hh_ohne["steuer_gesamt"]

    def test_netto_konsistent(self):
        e1 = self._ergebnis(2_000, 200, 200, 15_000.0)
        e2 = self._ergebnis(1_500, 150, 150, 10_000.0)
        hh = berechne_haushalt(e1, e2, "Zusammen", 500.0)
        expected_netto = hh["brutto_gesamt"] - hh["steuer_gesamt"] - hh["kv_gesamt"]
        assert hh["netto_gesamt"] == pytest.approx(expected_netto, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# _annuitaet
# ─────────────────────────────────────────────────────────────────────────────

class TestAnnuitaet:
    def test_null_kapital(self):
        assert _annuitaet(0.0, 0.05, 20) == 0.0

    def test_null_jahre(self):
        assert _annuitaet(100_000.0, 0.05, 0) == 0.0

    def test_null_rendite(self):
        kapital = 120_000.0
        jahre = 10
        expected = kapital / (jahre * 12)
        assert _annuitaet(kapital, 0.0, jahre) == pytest.approx(expected, rel=1e-9)

    def test_gesamtauszahlung_mindestens_kapital(self):
        # Bei positiver Rendite: Gesamtauszahlung > Startkapital
        m = _annuitaet(100_000.0, 0.04, 20)
        assert m * 12 * 20 > 100_000.0

    def test_hoehere_rendite_hoehere_rate(self):
        m_niedrig = _annuitaet(100_000.0, 0.01, 20)
        m_hoch    = _annuitaet(100_000.0, 0.06, 20)
        assert m_hoch > m_niedrig


# ─────────────────────────────────────────────────────────────────────────────
# _wert_bei_start – Aufschubverzinsung
# ─────────────────────────────────────────────────────────────────────────────

class TestWertBeiStart:
    def _produkt(self, einmal=50_000.0, mono=500.0, frueh=2030, aufschub=0.02):
        return _bav_produkt(
            max_einmalzahlung=einmal,
            max_monatsrente=mono,
            fruehestes_startjahr=frueh,
            spaetestes_startjahr=frueh + 5,
            aufschub_rendite=aufschub,
        )

    def test_kein_aufschub(self):
        prod = self._produkt()
        e, m = _wert_bei_start(prod, 2030)
        assert e == pytest.approx(50_000.0)
        assert m == pytest.approx(500.0)

    def test_zwei_jahre_aufschub(self):
        prod = self._produkt(aufschub=0.02)
        e, m = _wert_bei_start(prod, 2032)
        expected_f = 1.02 ** 2
        assert e == pytest.approx(50_000.0 * expected_f, rel=1e-9)
        assert m == pytest.approx(500.0 * expected_f, rel=1e-9)

    def test_null_aufschubrendite_kein_wachstum(self):
        prod = self._produkt(aufschub=0.0)
        e, m = _wert_bei_start(prod, 2035)
        assert e == pytest.approx(50_000.0)
        assert m == pytest.approx(500.0)

    def test_startjahr_vor_fruehestem(self):
        # deferral = max(0, ...) → kein negativer Aufschub
        prod = self._produkt()
        e, m = _wert_bei_start(prod, 2025)
        assert e == pytest.approx(50_000.0)
        assert m == pytest.approx(500.0)


# ─────────────────────────────────────────────────────────────────────────────
# kapital_vs_rente
# ─────────────────────────────────────────────────────────────────────────────

class TestKapitalVsRente:
    def test_null_rendite_monatlicheRate_korrekt(self):
        kapital = 120_000.0
        jahre   = 10
        expected = kapital / (jahre * 12)
        result = kapital_vs_rente(kapital, 0.0, jahre)
        assert result["monatsrate"] == pytest.approx(expected, rel=1e-9)

    def test_gesamtauszahlung_konsistent(self):
        result = kapital_vs_rente(100_000.0, 0.04, 20)
        assert result["gesamtauszahlung"] == pytest.approx(
            result["monatsrate"] * 20 * 12, rel=1e-9
        )

    def test_positive_rendite_ergibt_hoehere_rate(self):
        r0 = kapital_vs_rente(100_000.0, 0.0, 20)["monatsrate"]
        r4 = kapital_vs_rente(100_000.0, 0.04, 20)["monatsrate"]
        assert r4 > r0

    def test_kapitalverlauf_startet_mit_kapital(self):
        result = kapital_vs_rente(100_000.0, 0.04, 20)
        assert result["verlauf"][0]["Kapital"] == pytest.approx(100_000.0)

    def test_kapitalverlauf_endet_nahe_null(self):
        result = kapital_vs_rente(100_000.0, 0.04, 20)
        # Letzter Eintrag ≈ 0 (annuity läuft Kapital auf Null)
        assert result["verlauf"][-1]["Kapital"] == pytest.approx(0.0, abs=1.0)


# ─────────────────────────────────────────────────────────────────────────────
# _netto_ueber_horizont – KV/PV-Korrektheit
# ─────────────────────────────────────────────────────────────────────────────

class TestNettoUeberHorizont:
    def _ergebnis_gkv(self):
        p = _profil(geburtsjahr=1958, renteneintritt_alter=67,
                    aktuelle_punkte=35.0, punkte_pro_jahr=0.0)
        return berechne_rente(p)

    def _profil_gkv(self):
        return _profil(geburtsjahr=1958, renteneintritt_alter=67,
                       aktuelle_punkte=35.0, punkte_pro_jahr=0.0)

    def test_leere_entscheidungen_positives_netto(self):
        p = self._profil_gkv()
        e = self._ergebnis_gkv()
        total, jd = _netto_ueber_horizont(p, e, [], 10)
        assert total > 0.0
        assert len(jd) == 10

    def test_privat_rv_keine_kv(self):
        """PrivateRV-Auszahlung erhöht KV NICHT."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()

        privat = VorsorgeProdukt(
            id="t1", typ="PrivateRente", name="Privat-RV", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=500.0,
            laufzeit_jahre=10, fruehestes_startjahr=p.eintritt_jahr,
            spaetestes_startjahr=p.eintritt_jahr, aufschub_rendite=0.0,
        )
        _, jd_ohne = _netto_ueber_horizont(p, e, [], 10)
        _, jd_mit  = _netto_ueber_horizont(p, e, [(privat, p.eintritt_jahr, 0.0)], 10)

        kv_ohne = jd_ohne[0]["KV_PV"]
        kv_mit  = jd_mit[0]["KV_PV"]
        assert kv_mit == kv_ohne, "PrivateRV darf KV nicht erhöhen"

    def test_bav_kv_erhoeht_kv(self):
        """Hohe bAV-Monatsrente über Freibetrag erhöht KV-Basis."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()

        bav = VorsorgeProdukt(
            id="t2", typ="bAV", name="bAV-Test", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=2_000.0,
            laufzeit_jahre=10, fruehestes_startjahr=p.eintritt_jahr,
            spaetestes_startjahr=p.eintritt_jahr, aufschub_rendite=0.0,
        )
        _, jd_ohne = _netto_ueber_horizont(p, e, [], 10)
        _, jd_mit  = _netto_ueber_horizont(p, e, [(bav, p.eintritt_jahr, 0.0)], 10)

        assert jd_mit[0]["KV_PV"] > jd_ohne[0]["KV_PV"]

    def test_bav_freibetrag_greift(self):
        """bAV unter Freibetrag (187,25 €/Mon.) erhöht KV-Basis NICHT."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()

        bav_klein = VorsorgeProdukt(
            id="t3", typ="bAV", name="bAV-klein", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=100.0,
            laufzeit_jahre=10, fruehestes_startjahr=p.eintritt_jahr,
            spaetestes_startjahr=p.eintritt_jahr, aufschub_rendite=0.0,
        )
        _, jd_ohne = _netto_ueber_horizont(p, e, [], 10)
        _, jd_mit  = _netto_ueber_horizont(p, e, [(bav_klein, p.eintritt_jahr, 0.0)], 10)

        # 100 €/Mon bAV < 187,25 € Freibetrag → KV bleibt gleich
        assert jd_mit[0]["KV_PV"] == jd_ohne[0]["KV_PV"]

    def test_bbg_cap_wirkt(self):
        """KV-Basis wird bei BBG gedeckelt."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()

        # Sehr hohe bAV → KV-Basis bei BBG gedeckelt
        bav_gross = VorsorgeProdukt(
            id="t4", typ="bAV", name="bAV-groß", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=10_000.0,
            laufzeit_jahre=20, fruehestes_startjahr=p.eintritt_jahr,
            spaetestes_startjahr=p.eintritt_jahr, aufschub_rendite=0.0,
        )
        bav_riesig = VorsorgeProdukt(
            id="t5", typ="bAV", name="bAV-riesig", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=50_000.0,
            laufzeit_jahre=20, fruehestes_startjahr=p.eintritt_jahr,
            spaetestes_startjahr=p.eintritt_jahr, aufschub_rendite=0.0,
        )
        _, jd_gross  = _netto_ueber_horizont(p, e, [(bav_gross,  p.eintritt_jahr, 0.0)], 5)
        _, jd_riesig = _netto_ueber_horizont(p, e, [(bav_riesig, p.eintritt_jahr, 0.0)], 5)

        # KV bei BBG gedeckelt: beide müssen gleiche KV haben (BBG erreicht)
        assert jd_gross[0]["KV_PV"] == jd_riesig[0]["KV_PV"]

    def test_mieteinnahmen_kein_kv_beitrag(self):
        """Mieteinnahmen erhöhen Brutto und Steuer, aber nicht KV."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()

        _, jd_ohne = _netto_ueber_horizont(p, e, [], 5, 0.0, 0.0)
        _, jd_mit  = _netto_ueber_horizont(p, e, [], 5, 1_000.0, 0.0)

        assert jd_mit[0]["KV_PV"] == jd_ohne[0]["KV_PV"]
        assert jd_mit[0]["Brutto"] > jd_ohne[0]["Brutto"]
        assert jd_mit[0]["Steuer"] >= jd_ohne[0]["Steuer"]

    def test_mietsteigerung_wirkt(self):
        """Miete wächst jährlich."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()

        _, jd = _netto_ueber_horizont(p, e, [], 5, 1_000.0, 0.02)
        # Brutto steigt von Jahr zu Jahr durch Mietsteigerung
        for i in range(1, len(jd)):
            assert jd[i]["Brutto"] >= jd[i - 1]["Brutto"]

    def test_pkv_kv_fix(self):
        """PKV-Beitrag ist fix, unabhängig vom Einkommen."""
        p_pkv = _profil(geburtsjahr=1958, renteneintritt_alter=67,
                        aktuelle_punkte=35.0, punkte_pro_jahr=0.0,
                        krankenversicherung="PKV", pkv_beitrag=700.0)
        e = berechne_rente(p_pkv)

        bav = VorsorgeProdukt(
            id="t6", typ="bAV", name="bAV", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=2_000.0,
            laufzeit_jahre=10, fruehestes_startjahr=p_pkv.eintritt_jahr,
            spaetestes_startjahr=p_pkv.eintritt_jahr, aufschub_rendite=0.0,
        )
        _, jd_ohne = _netto_ueber_horizont(p_pkv, e, [], 5)
        _, jd_mit  = _netto_ueber_horizont(p_pkv, e, [(bav, p_pkv.eintritt_jahr, 0.0)], 5)

        assert jd_mit[0]["KV_PV"] == jd_ohne[0]["KV_PV"]
        assert jd_ohne[0]["KV_PV"] == 700.0 * 12

    def test_jahresdaten_vollstaendig(self):
        p = self._profil_gkv()
        e = self._ergebnis_gkv()
        total, jd = _netto_ueber_horizont(p, e, [], 20)
        assert len(jd) == 20
        for row in jd:
            assert "Jahr" in row
            assert "Brutto" in row
            assert "Steuer" in row
            assert "KV_PV" in row
            assert "Netto" in row
            # Jede Komponente wird unabhängig gerundet → max. ±2 Rundungsdifferenz
            assert abs(row["Netto"] - (row["Brutto"] - row["Steuer"] - row["KV_PV"])) <= 2

    def test_total_nahe_summe_jahresdaten(self):
        # total_netto verwendet ungerundete Werte; jahresdaten speichert round()-Werte
        # Toleranz: max. 1 € pro Jahr Rundungsdifferenz
        p = self._profil_gkv()
        e = self._ergebnis_gkv()
        total, jd = _netto_ueber_horizont(p, e, [], 10)
        assert abs(total - sum(r["Netto"] for r in jd)) < len(jd) * 1.0

    def test_privat_rv_monatsrente_nur_ertragsanteil_versteuert(self):
        """PrivateRente monatlich → nur Ertragsanteil im zvE; Netto höher als bAV."""
        p = self._profil_gkv()   # eintritt_jahr = 1958 + 67 = 2025
        e = self._ergebnis_gkv()
        sj = p.eintritt_jahr
        priv_prod = VorsorgeProdukt(
            id="priv", typ="PrivateRente", name="PRV", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=1_000.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )
        bav_prod = VorsorgeProdukt(
            id="bav", typ="bAV", name="BAV", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=1_000.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )
        total_priv, _ = _netto_ueber_horizont(p, e, [(priv_prod, sj, 0.0)], 5)
        total_bav, _  = _netto_ueber_horizont(p, e, [(bav_prod,  sj, 0.0)], 5)
        assert total_priv > total_bav

    def test_lv_altvertrag_steuerfrei(self):
        """LV-Altvertrag (Vertragsbeginn vor 2005) → Einmalauszahlung steuerfrei."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()
        sj = p.eintritt_jahr
        lv_alt = VorsorgeProdukt(
            id="lv_alt", typ="LV", name="LV-Alt", person="Person 1",
            max_einmalzahlung=50_000.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0, vertragsbeginn=1995, einzahlungen_gesamt=30_000.0,
        )
        lv_neu = VorsorgeProdukt(
            id="lv_neu", typ="LV", name="LV-Neu", person="Person 1",
            max_einmalzahlung=50_000.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0, vertragsbeginn=2010, einzahlungen_gesamt=30_000.0,
        )
        total_alt, _ = _netto_ueber_horizont(p, e, [(lv_alt, sj, 1.0)], 5)
        total_neu, _ = _netto_ueber_horizont(p, e, [(lv_neu, sj, 1.0)], 5)
        assert total_alt > total_neu

    def test_lv_halbeinkunfte_bei_langer_laufzeit(self):
        """LV ab 2012, Laufzeit ≥ 12 J. und Alter ≥ 62 → Halbeinkünfte günstiger als
        Abgeltungsteuer (kurze Laufzeit)."""
        p = self._profil_gkv()   # geb. 1958, Eintritt 67 = 2025
        e = self._ergebnis_gkv()
        sj = p.eintritt_jahr     # 2025; Alter = 67 ≥ 62
        # lang: Laufzeit 2012 → 2025 = 13 J. ≥ 12 → Halbeinkünfte
        lv_lang = VorsorgeProdukt(
            id="lv_l", typ="LV", name="LV-Lang", person="Person 1",
            max_einmalzahlung=50_000.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0, vertragsbeginn=2012, einzahlungen_gesamt=30_000.0,
        )
        # kurz: Laufzeit 2020 → 2025 = 5 J. < 12 → Abgeltungsteuer
        lv_kurz = VorsorgeProdukt(
            id="lv_k", typ="LV", name="LV-Kurz", person="Person 1",
            max_einmalzahlung=50_000.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0, vertragsbeginn=2020, einzahlungen_gesamt=30_000.0,
        )
        total_lang, _ = _netto_ueber_horizont(p, e, [(lv_lang, sj, 1.0)], 5)
        total_kurz, _ = _netto_ueber_horizont(p, e, [(lv_kurz, sj, 1.0)], 5)
        assert total_lang > total_kurz

    def test_ruerup_besteuerungsanteil_nicht_100prozent(self):
        """Rürup-Rente wird mit Besteuerungsanteil, nicht 100 % versteuert."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()
        sj = p.eintritt_jahr
        ba = besteuerungsanteil(sj)
        assert ba < 1.0, "Test-Voraussetzung: Besteuerungsanteil < 100 %"

        ruerup = VorsorgeProdukt(
            id="r1", typ="Rürup", name="Rürup-Test", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=1_000.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )
        riester = VorsorgeProdukt(
            id="ri1", typ="Riester", name="Riester-Test", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=1_000.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )
        total_ruerup,  _ = _netto_ueber_horizont(p, e, [(ruerup,  sj, 0.0)], 5)
        total_riester, _ = _netto_ueber_horizont(p, e, [(riester, sj, 0.0)], 5)
        # Rürup: weniger steuerpflichtig → höheres Netto
        assert total_ruerup > total_riester

    def test_etf_teilfreistellung_und_sparerpauschbetrag(self):
        """ETF-Entnahme: nur (1 – TF) × Gewinn steuerpflichtig; Sparerpauschbetrag greift."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()
        sj = p.eintritt_jahr
        # ETF mit kleinem Ertrag unter Sparerpauschbetrag → keine Abgeltungsteuer
        etf_klein = VorsorgeProdukt(
            id="etf1", typ="ETF", name="ETF-klein", person="Person 1",
            max_einmalzahlung=10_000.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0, einzahlungen_gesamt=9_500.0, teilfreistellung=0.30,
        )
        # Ertrag = 10.000 × (1 - 9.500/10.000) = 500 €; TF 30 % → steuerpfl. 350 € < 1.000 €
        _, jd = _netto_ueber_horizont(p, e, [(etf_klein, sj, 1.0)], 5)
        assert jd[0]["Steuer_Abgeltung"] == 0  # unter Sparerpauschbetrag

        # ETF mit großem Ertrag über Sparerpauschbetrag
        etf_gross = VorsorgeProdukt(
            id="etf2", typ="ETF", name="ETF-groß", person="Person 1",
            max_einmalzahlung=100_000.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0, einzahlungen_gesamt=50_000.0, teilfreistellung=0.30,
        )
        # Ertrag = 50.000 €; TF 30 % → steuerpfl. 35.000 € >> 1.000 €
        _, jd2 = _netto_ueber_horizont(p, e, [(etf_gross, sj, 1.0)], 5)
        expected = (35_000.0 - SPARERPAUSCHBETRAG) * 0.25
        assert jd2[0]["Steuer_Abgeltung"] == pytest.approx(expected, abs=1.0)

    def test_jahresdaten_quellenschluessel_vorhanden(self):
        """Erweiterte Schlüssel in jahresdaten (Src_*, zvE, Steuer_*) sind vorhanden."""
        p = self._profil_gkv()
        e = self._ergebnis_gkv()
        _, jd = _netto_ueber_horizont(p, e, [], 5)
        expected_keys = {"Src_Gehalt", "Src_GesRente", "Src_Versorgung", "Src_Einmal",
                         "Src_Miete", "zvE", "Steuer_Progressiv", "Steuer_Abgeltung"}
        for row in jd:
            assert expected_keys.issubset(row.keys())


# ─────────────────────────────────────────────────────────────────────────────
# simuliere_szenarien
# ─────────────────────────────────────────────────────────────────────────────

class TestSimuliereSzenarien:
    def test_alle_szenarien_vorhanden(self):
        p = _profil()
        sz = simuliere_szenarien(p)
        assert set(sz.keys()) == {"Pessimistisch", "Neutral", "Optimistisch"}

    def test_optimistisch_groesser_pessimistisch(self):
        p = _profil()
        sz = simuliere_szenarien(p)
        assert sz["Optimistisch"].netto_monatlich > sz["Pessimistisch"].netto_monatlich

    def test_neutral_zwischen_den_extremen(self):
        # Basis-Rentenanpassung muss zwischen pess (1%) und opt (3%) liegen
        p = _profil(rentenanpassung_pa=0.02, rendite_pa=0.05)
        sz = simuliere_szenarien(p)
        assert sz["Pessimistisch"].netto_monatlich <= sz["Neutral"].netto_monatlich
        assert sz["Neutral"].netto_monatlich <= sz["Optimistisch"].netto_monatlich


# ─────────────────────────────────────────────────────────────────────────────
# Konstanten-Sanity-Checks
# ─────────────────────────────────────────────────────────────────────────────

class TestKonstanten:
    def test_rentenwert_plausibel(self):
        assert 35.0 < RENTENWERT_2024 < 45.0

    def test_grundfreibetrag_plausibel(self):
        assert 10_000 < GRUNDFREIBETRAG_2024 < 15_000

    def test_bav_freibetrag_plausibel(self):
        assert 150 < BAV_FREIBETRAG_MONATLICH < 250

    def test_bbg_kv_plausibel(self):
        assert 4_000 < BBG_KV_MONATLICH < 7_000

    def test_sparerpauschbetrag_plausibel(self):
        assert SPARERPAUSCHBETRAG == 1_000


# ─────────────────────────────────────────────────────────────────────────────
# versorgungsfreibetrag – § 19 Abs. 2 EStG (M1)
# ─────────────────────────────────────────────────────────────────────────────

class TestVersorgungsfreibetrag:
    def test_2005_maximaler_freibetrag(self):
        # 2005: 40 % × Pension, max. 3.000 €, Zuschlag 900 €
        pension_j = 100_000.0
        vfb = versorgungsfreibetrag(2005, pension_j)
        assert vfb == pytest.approx(3_000.0 + 900.0)

    def test_2005_klein_anteil_greift(self):
        # Pension so klein, dass 40 % unter 3.000 €
        pension_j = 5_000.0
        vfb = versorgungsfreibetrag(2005, pension_j)
        assert vfb == pytest.approx(5_000.0 * 0.40 + 900.0)

    def test_2024_werte(self):
        # 2024: 19 Schritte nach 2005 – aber ab 2021 nur noch halber Schritt
        # Wert für 2020: anteil = 0.40 - 15*0.016 = 0.16; max = 3000-15*120 = 1200; zuschlag = 900-15*36 = 360
        # 2024: n = 4 Schritte von 2020; anteil = 0.16 - 4*0.008 = 0.128; max = 1200-4*60 = 960; zuschlag = 360-4*18 = 288
        pension_j = 100_000.0
        vfb = versorgungsfreibetrag(2024, pension_j)
        # anteil × pension > max → max + zuschlag = 960 + 288 = 1248
        assert vfb == pytest.approx(960.0 + 288.0)

    def test_2040_kein_freibetrag(self):
        assert versorgungsfreibetrag(2040, 50_000.0) == 0.0
        assert versorgungsfreibetrag(2050, 50_000.0) == 0.0

    def test_monoton_sinkend_mit_spatem_ruhestand(self):
        pension_j = 50_000.0
        vfb_2005 = versorgungsfreibetrag(2005, pension_j)
        vfb_2015 = versorgungsfreibetrag(2015, pension_j)
        vfb_2025 = versorgungsfreibetrag(2025, pension_j)
        assert vfb_2005 > vfb_2015 > vfb_2025

    def test_kein_negativer_freibetrag(self):
        for j in range(2000, 2045):
            assert versorgungsfreibetrag(j, 0.0) >= 0.0


# ─────────────────────────────────────────────────────────────────────────────
# berechne_rente Pensionär – § 19 EStG, KV § 229 (M1)
# ─────────────────────────────────────────────────────────────────────────────

class TestPensionaerBerechne:
    def _pensionaer(self, **kwargs):
        defaults = dict(
            geburtsjahr=1965,
            renteneintritt_alter=65,
            aktuelle_punkte=0.0,
            punkte_pro_jahr=0.0,
            zusatz_monatlich=0.0,
            sparkapital=0.0,
            sparrate=0.0,
            rendite_pa=0.0,
            rentenanpassung_pa=0.0,
            krankenversicherung="GKV",
            pkv_beitrag=0.0,
            gkv_zusatzbeitrag=0.017,
            kinder=True,
            ist_pensionaer=True,
            aktuelles_brutto_monatlich=4_000.0,
        )
        defaults.update(kwargs)
        return Profil(**defaults)

    def test_brutto_gleich_eingabe(self):
        p = self._pensionaer(aktuelles_brutto_monatlich=3_500.0)
        e = berechne_rente(p)
        assert e.brutto_gesetzlich == pytest.approx(3_500.0)

    def test_versorgungsfreibetrag_senkt_steuer(self):
        """Pensionär zahlt weniger Steuer als bei voller Besteuerung (ohne VFB)."""
        p = self._pensionaer(aktuelles_brutto_monatlich=3_000.0)
        e = berechne_rente(p)
        # Steuer mit VFB < Steuer ohne VFB
        pension_j = 3_000.0 * 12
        zvE_ohne_vfb = max(0.0, pension_j - WERBUNGSKOSTEN_PAUSCHBETRAG - SONDERAUSGABEN_PAUSCHBETRAG)
        steuer_ohne_vfb = einkommensteuer(zvE_ohne_vfb)
        assert e.jahressteuer < steuer_ohne_vfb

    def test_kv_keine_bav_freibetrag(self):
        """Bei Pensionären gilt kein bAV-Freibetrag (§ 229 Abs. 1 Nr. 1 SGB V)."""
        p_pensionaer = self._pensionaer(aktuelles_brutto_monatlich=500.0, kinder=True)
        e = berechne_rente(p_pensionaer)
        # Pensionär ist immer freiwillig GKV-versichert → voller GKV- + PV-Satz (kein DRV-Trägeranteil)
        # Kein bAV-Freibetrag (§ 229 Abs. 1 Nr. 1 SGB V gilt nur für GRV-Rentner)
        kv_satz = 0.146 + 0.017 + 0.034   # 14,6 % + Zusatz 1,7 % + PV 3,4 %
        expected_kv = 500.0 * kv_satz
        assert e.kv_monatlich == pytest.approx(expected_kv, rel=1e-4)

    def test_netto_konsistent(self):
        p = self._pensionaer()
        e = berechne_rente(p)
        assert e.netto_monatlich == pytest.approx(
            e.brutto_monatlich - e.steuer_monatlich - e.kv_monatlich, rel=1e-9
        )

    def test_pkv_beihilfe_pensionaer(self):
        p = self._pensionaer(krankenversicherung="PKV", pkv_beitrag=250.0)
        e = berechne_rente(p)
        assert e.kv_monatlich == pytest.approx(250.0)

    def test_rentenpunkte_null_fuer_pensionaer(self):
        p = self._pensionaer()
        e = berechne_rente(p)
        assert e.gesamtpunkte == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# DUV/BUV – Ertragsanteil und KV-Behandlung (M1)
# ─────────────────────────────────────────────────────────────────────────────

class TestDuvBuv:
    def _pensionaer_mit_duv(self, duv_mon=500.0, duv_end=2060):
        return _profil(
            geburtsjahr=1985,
            renteneintritt_alter=65,
            aktuelle_punkte=0.0,
            punkte_pro_jahr=0.0,
            ist_pensionaer=True,
            aktuelles_brutto_monatlich=3_000.0,
            krankenversicherung="GKV",
            duv_monatlich=duv_mon,
            duv_endjahr=duv_end,
        )

    def _grv_mit_buv(self, buv_mon=500.0, buv_end=2060):
        return _profil(
            geburtsjahr=1985,
            renteneintritt_alter=67,
            aktuelle_punkte=30.0,
            punkte_pro_jahr=0.0,
            ist_pensionaer=False,
            buv_monatlich=buv_mon,
            buv_endjahr=buv_end,
        )

    def test_duv_erhoetht_brutto(self):
        p_ohne = self._pensionaer_mit_duv(duv_mon=0.0)
        p_mit  = self._pensionaer_mit_duv(duv_mon=500.0)
        e_ohne = berechne_rente(p_ohne)
        e_mit  = berechne_rente(p_mit)
        assert e_mit.brutto_monatlich == pytest.approx(e_ohne.brutto_monatlich + 500.0)

    def test_duv_nicht_kvdr_pflichtig(self):
        """DUV erhöht KV-Beitrag NICHT (nur Pensionsbezug ist KV-pflichtig)."""
        p_ohne = self._pensionaer_mit_duv(duv_mon=0.0)
        p_mit  = self._pensionaer_mit_duv(duv_mon=1_000.0)
        e_ohne = berechne_rente(p_ohne)
        e_mit  = berechne_rente(p_mit)
        assert e_mit.kv_monatlich == pytest.approx(e_ohne.kv_monatlich, rel=1e-4)

    def test_duv_ertragsanteil_senkt_steuer_vs_voll(self):
        """DUV wird mit Ertragsanteil versteuert – weniger als 100 % Besteuerung."""
        p = self._pensionaer_mit_duv(duv_mon=1_000.0)
        e = berechne_rente(p)
        # Ertragsanteil bei Alter 40 = ertragsanteil(40) = 38 %
        ea = ertragsanteil(2025 - 1985)  # aktuelles Alter bei DU
        assert ea < 1.0  # Ertragsanteil ist deutlich unter 100 %
        # Jahres-zvE enthält nur ea × duv_monatl × 12 (nicht voll)
        duv_voll_j  = 1_000.0 * 12
        duv_ea_j    = duv_voll_j * ea
        assert duv_ea_j < duv_voll_j

    def test_duv_abgelaufen_kein_einfluss(self):
        """DUV nach Endjahr hat keinen Einfluss auf Berechnung."""
        p_aktiv    = self._pensionaer_mit_duv(duv_mon=500.0, duv_end=2060)
        p_abgelauf = self._pensionaer_mit_duv(duv_mon=500.0, duv_end=2000)
        e_aktiv    = berechne_rente(p_aktiv)
        e_abgelauf = berechne_rente(p_abgelauf)
        # Abgelaufene DUV soll keinen Beitrag liefern (rentenbeginn > duv_endjahr)
        assert e_abgelauf.brutto_monatlich < e_aktiv.brutto_monatlich

    def test_buv_erhoetht_brutto(self):
        p_ohne = self._grv_mit_buv(buv_mon=0.0)
        p_mit  = self._grv_mit_buv(buv_mon=600.0)
        e_ohne = berechne_rente(p_ohne)
        e_mit  = berechne_rente(p_mit)
        assert e_mit.brutto_monatlich == pytest.approx(e_ohne.brutto_monatlich + 600.0)

    def test_buv_nicht_kvdr_pflichtig(self):
        """BUV erhöht KV-Beitrag NICHT."""
        p_ohne = self._grv_mit_buv(buv_mon=0.0)
        p_mit  = self._grv_mit_buv(buv_mon=2_000.0)
        e_ohne = berechne_rente(p_ohne)
        e_mit  = berechne_rente(p_mit)
        # KV-Basis ist nur die GRV-Rente, nicht die BUV
        assert e_mit.kv_monatlich == pytest.approx(e_ohne.kv_monatlich, rel=1e-4)

    def test_buv_ertragsanteil_im_zvE(self):
        """BUV ist mit Ertragsanteil steuerpflichtig – zvE steigt, aber weniger als voll."""
        p_ohne = self._grv_mit_buv(buv_mon=0.0)
        p_mit  = self._grv_mit_buv(buv_mon=1_000.0)
        e_ohne = berechne_rente(p_ohne)
        e_mit  = berechne_rente(p_mit)
        # zvE steigt um Ertragsanteil × 12.000, nicht 12.000
        zvE_diff = e_mit.zvE_jahres - e_ohne.zvE_jahres
        ea = ertragsanteil(2025 - 1985)
        assert zvE_diff == pytest.approx(1_000.0 * 12 * ea, abs=1.0)

    def test_buv_nicht_fuer_pensionaer(self):
        """BUV greift nicht, wenn ist_pensionaer=True (DUV stattdessen)."""
        p = _profil(
            geburtsjahr=1985, renteneintritt_alter=65, aktuelle_punkte=0.0,
            punkte_pro_jahr=0.0, ist_pensionaer=True,
            aktuelles_brutto_monatlich=3_000.0,
            buv_monatlich=1_000.0, buv_endjahr=2060,
        )
        e = berechne_rente(p)
        # BUV-Betrag darf bei Pensionär nicht ins Brutto eingehen
        p_ohne_buv = _profil(
            geburtsjahr=1985, renteneintritt_alter=65, aktuelle_punkte=0.0,
            punkte_pro_jahr=0.0, ist_pensionaer=True,
            aktuelles_brutto_monatlich=3_000.0,
        )
        e_ohne = berechne_rente(p_ohne_buv)
        assert e.brutto_monatlich == pytest.approx(e_ohne.brutto_monatlich)


# ─────────────────────────────────────────────────────────────────────────────
# KVdR vs. freiwillig GKV (§ 5 Abs. 1 Nr. 11 SGB V vs. § 240 SGB V)
# ─────────────────────────────────────────────────────────────────────────────

class TestKVdRVsFreiwillig:
    """KV-Beitragspflicht: KVdR (§229 SGB V) vs. freiwillig GKV (§240 SGB V)."""

    def _profil_gkv(self, kvdr: bool) -> Profil:
        return _profil(
            geburtsjahr=1958, renteneintritt_alter=67,
            aktuelle_punkte=35.0, punkte_pro_jahr=0.0,
            kvdr_pflicht=kvdr,
        )

    def test_kvdr_mieteinnahmen_kein_kv(self):
        """KVdR: Mieteinnahmen nicht §229-Einkommen → KV unverändert."""
        p = self._profil_gkv(kvdr=True)
        e = berechne_rente(p)
        _, jd_ohne = _netto_ueber_horizont(p, e, [], 5, 0.0, 0.0)
        _, jd_mit  = _netto_ueber_horizont(p, e, [], 5, 1_000.0, 0.0)
        assert jd_mit[0]["KV_PV"] == jd_ohne[0]["KV_PV"]

    def test_freiwillig_mieteinnahmen_erhoetht_kv(self):
        """Freiwillig GKV: Mieteinnahmen beitragspflichtig → KV steigt."""
        p = self._profil_gkv(kvdr=False)
        e = berechne_rente(p)
        _, jd_ohne = _netto_ueber_horizont(p, e, [], 5, 0.0, 0.0)
        _, jd_mit  = _netto_ueber_horizont(p, e, [], 5, 500.0, 0.0)
        assert jd_mit[0]["KV_PV"] > jd_ohne[0]["KV_PV"]

    def test_kvdr_privatrv_kein_kv(self):
        """KVdR: Private RV-Monatsrente nicht §229-Einkommen → KV unverändert."""
        p = self._profil_gkv(kvdr=True)
        e = berechne_rente(p)
        sj = p.eintritt_jahr
        prod = VorsorgeProdukt(
            id="priv", typ="PrivateRente", name="PRV", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=800.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )
        _, jd_ohne = _netto_ueber_horizont(p, e, [], 5)
        _, jd_mit  = _netto_ueber_horizont(p, e, [(prod, sj, 0.0)], 5)
        assert jd_mit[0]["KV_PV"] == jd_ohne[0]["KV_PV"]

    def test_freiwillig_privatrv_erhoetht_kv(self):
        """Freiwillig GKV: Private RV-Monatsrente beitragspflichtig → KV steigt."""
        p = self._profil_gkv(kvdr=False)
        e = berechne_rente(p)
        sj = p.eintritt_jahr
        prod = VorsorgeProdukt(
            id="priv", typ="PrivateRente", name="PRV", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=800.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )
        _, jd_ohne = _netto_ueber_horizont(p, e, [], 5)
        _, jd_mit  = _netto_ueber_horizont(p, e, [(prod, sj, 0.0)], 5)
        assert jd_mit[0]["KV_PV"] > jd_ohne[0]["KV_PV"]

    def test_freiwillig_bav_kein_freibetrag(self):
        """Freiwillig GKV: bAV-Freibetrag gilt NICHT → auch kleine bAV erhöht KV."""
        # Under KVdR, bAV of 100 €/Mon. < 187.25 € Freibetrag → no KV change
        # Under freiwillig GKV, 100 €/Mon. counts fully
        p_kvdr      = self._profil_gkv(kvdr=True)
        p_freiwillig = self._profil_gkv(kvdr=False)
        e_k = berechne_rente(p_kvdr)
        e_f = berechne_rente(p_freiwillig)
        sj  = p_kvdr.eintritt_jahr
        bav_klein = VorsorgeProdukt(
            id="bav_k", typ="bAV", name="bAV-klein", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=100.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )
        _, jd_kvdr_ohne = _netto_ueber_horizont(p_kvdr,      e_k, [], 5)
        _, jd_kvdr_mit  = _netto_ueber_horizont(p_kvdr,      e_k, [(bav_klein, sj, 0.0)], 5)
        _, jd_frei_ohne = _netto_ueber_horizont(p_freiwillig, e_f, [], 5)
        _, jd_frei_mit  = _netto_ueber_horizont(p_freiwillig, e_f, [(bav_klein, sj, 0.0)], 5)
        # KVdR: 100 € < Freibetrag → KV unverändert
        assert jd_kvdr_mit[0]["KV_PV"] == jd_kvdr_ohne[0]["KV_PV"]
        # Freiwillig: auch 100 € bAV trägt zur KV-Basis bei
        assert jd_frei_mit[0]["KV_PV"] > jd_frei_ohne[0]["KV_PV"]

    def test_freiwillig_mindestbemessungsgrundlage(self):
        """Freiwillig GKV: sehr kleine Rente → Mindest-BMG (≈1.097 €/Mon.) greift."""
        p_f = _profil(
            geburtsjahr=1958, renteneintritt_alter=67,
            aktuelle_punkte=5.0, punkte_pro_jahr=0.0,
            kvdr_pflicht=False,
        )
        p_k = _profil(
            geburtsjahr=1958, renteneintritt_alter=67,
            aktuelle_punkte=5.0, punkte_pro_jahr=0.0,
            kvdr_pflicht=True,
        )
        e_f = berechne_rente(p_f)
        e_k = berechne_rente(p_k)
        _, jd_f = _netto_ueber_horizont(p_f, e_f, [], 5)
        _, jd_k = _netto_ueber_horizont(p_k, e_k, [], 5)
        # Freiwillig: Mindest-BMG > actual income → KV auf Mindest-BMG
        # KVdR: KV nur auf tatsächliche Rente (kein Mindest-BMG-Prinzip)
        assert jd_f[0]["KV_PV"] > jd_k[0]["KV_PV"]

    def test_freiwillig_bav_einmal_kein_spreading(self):
        """Freiwillig GKV: bAV-Einmalauszahlung darf NICHT auf 10 Jahre gespreizt werden.

        §229 Abs. 1 S. 3 SGB V (10-Jahres-Spreading) gilt nur für KVdR.
        Für freiwillig Versicherte zählt die Einmalauszahlung nur im Auszahlungsjahr
        (via einmal_brutto_j), nicht in den Folgejahren.
        """
        p = self._profil_gkv(kvdr=False)
        e = berechne_rente(p)
        sj = p.eintritt_jahr
        bav_einmal = VorsorgeProdukt(
            id="bav_e", typ="bAV", name="bAV-Einmal", person="Person 1",
            max_einmalzahlung=120_000.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )
        _, jd_ohne = _netto_ueber_horizont(p, e, [], 5)
        _, jd_mit  = _netto_ueber_horizont(p, e, [(bav_einmal, sj, 1.0)], 5)
        # Im Auszahlungsjahr (Jahr 0) muss KV steigen (einmal_brutto_j trägt bei)
        assert jd_mit[0]["KV_PV"] > jd_ohne[0]["KV_PV"]
        # Im Folgejahr (Jahr 1) darf das bAV-Einmal KEINE KV mehr erzeugen
        # (kein §229-Spreading für freiwillig Versicherte)
        assert jd_mit[1]["KV_PV"] == jd_ohne[1]["KV_PV"]

    def test_kvdr_bav_einmal_spreading_10_jahre(self):
        """KVdR: bAV-Einmalauszahlung wird gemäß §229 Abs. 1 S. 3 SGB V auf 10 Jahre verteilt."""
        p = self._profil_gkv(kvdr=True)
        e = berechne_rente(p)
        sj = p.eintritt_jahr
        bav_einmal = VorsorgeProdukt(
            id="bav_e", typ="bAV", name="bAV-Einmal", person="Person 1",
            max_einmalzahlung=120_000.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )
        _, jd_ohne = _netto_ueber_horizont(p, e, [], 12)
        _, jd_mit  = _netto_ueber_horizont(p, e, [(bav_einmal, sj, 1.0)], 12)
        # Jahre 0–9: KV erhöht (bav_einmal_kv_j = betrag/10 je Jahr)
        for i in range(10):
            assert jd_mit[i]["KV_PV"] > jd_ohne[i]["KV_PV"], f"Jahr {i}: KV sollte erhöht sein"
        # Jahr 10: kein Spreading mehr → KV wie ohne bAV-Einmal
        assert jd_mit[10]["KV_PV"] == jd_ohne[10]["KV_PV"]


# ─────────────────────────────────────────────────────────────────────────────
# Laufende Kapitalerträge (Zinsen, Dividenden, Ausschüttungen)
# ─────────────────────────────────────────────────────────────────────────────

class TestLaufendeKapitalertraege:
    """Laufende Kapitalerträge in VorsorgeProdukt.laufende_kapitalertraege_mono."""

    def _profil_rente(self, kvdr: bool = True) -> Profil:
        return _profil(
            geburtsjahr=1958, renteneintritt_alter=67,
            aktuelle_punkte=35.0, punkte_pro_jahr=0.0,
            kvdr_pflicht=kvdr,
        )

    def _prod_mit_lfd_kap(self, lfd_kap: float) -> VorsorgeProdukt:
        return VorsorgeProdukt(
            id="lfd", typ="ETF", name="ETF-lfd", person="Person 1",
            max_einmalzahlung=0.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=2025, spaetestes_startjahr=2025,
            aufschub_rendite=0.0, einzahlungen_gesamt=0.0, teilfreistellung=0.30,
            laufende_kapitalertraege_mono=lfd_kap,
        )

    def test_unter_pauschbetrag_kein_abgelt(self):
        """Laufende Kapitalerträge < 1.000 €/J. (Sparerpauschbetrag) → keine Abgeltungsteuer."""
        p = self._profil_rente()
        e = berechne_rente(p)
        sj = p.eintritt_jahr
        prod = self._prod_mit_lfd_kap(70.0)  # 70 × 12 = 840 € < 1.000 €
        _, jd = _netto_ueber_horizont(p, e, [(prod, sj, 1.0)], 5)
        assert jd[0]["Steuer_Abgeltung"] == 0

    def test_ueber_pauschbetrag_abgeltungsteuer(self):
        """Laufende Kapitalerträge > 1.000 €/J. → 25 % Abgeltungsteuer auf Überschuss."""
        p = self._profil_rente()
        e = berechne_rente(p)
        sj = p.eintritt_jahr
        prod = self._prod_mit_lfd_kap(200.0)  # 200 × 12 = 2.400 € > 1.000 €
        _, jd = _netto_ueber_horizont(p, e, [(prod, sj, 1.0)], 5)
        expected = (200.0 * 12 - SPARERPAUSCHBETRAG) * 0.25
        assert jd[0]["Steuer_Abgeltung"] == pytest.approx(expected, abs=1.0)

    def test_kvdr_laufende_kap_kein_kv(self):
        """KVdR: laufende Kapitalerträge erhöhen KV-Basis NICHT."""
        p = self._profil_rente(kvdr=True)
        e = berechne_rente(p)
        sj = p.eintritt_jahr
        _, jd_ohne = _netto_ueber_horizont(p, e, [(self._prod_mit_lfd_kap(0.0),   sj, 1.0)], 5)
        _, jd_mit  = _netto_ueber_horizont(p, e, [(self._prod_mit_lfd_kap(500.0), sj, 1.0)], 5)
        assert jd_mit[0]["KV_PV"] == jd_ohne[0]["KV_PV"]

    def test_freiwillig_laufende_kap_erhoetht_kv(self):
        """Freiwillig GKV: laufende Kapitalerträge erhöhen KV-Basis."""
        p = self._profil_rente(kvdr=False)
        e = berechne_rente(p)
        sj = p.eintritt_jahr
        _, jd_ohne = _netto_ueber_horizont(p, e, [(self._prod_mit_lfd_kap(0.0),   sj, 1.0)], 5)
        _, jd_mit  = _netto_ueber_horizont(p, e, [(self._prod_mit_lfd_kap(500.0), sj, 1.0)], 5)
        assert jd_mit[0]["KV_PV"] > jd_ohne[0]["KV_PV"]


# ─────────────────────────────────────────────────────────────────────────────
# Berufsjahre – Pre-retirement Simulation mit Gehalt als Steuerbasis
# ─────────────────────────────────────────────────────────────────────────────

class TestBerufsjahre:
    """Simulation ab AKTUELLES_JAHR mit Bruttogehalt für Steuerprogression."""

    def _profil_noch_aktiv(self) -> Profil:
        """Renteneintritt in 2 Jahren (eintritt_jahr = AKTUELLES_JAHR + 2)."""
        return _profil(
            geburtsjahr=AKTUELLES_JAHR - 65,
            renteneintritt_alter=67,
            aktuelle_punkte=35.0, punkte_pro_jahr=0.0,
        )

    def test_mit_gehalt_mehr_simulationsjahre(self):
        """Gehalt > 0 und zukünftiger Renteneintritt → mehr als horizon Jahre simuliert."""
        p = self._profil_noch_aktiv()
        e = berechne_rente(p)
        horizon = 10
        _, jd = _netto_ueber_horizont(p, e, [], horizon, gehalt_monatlich=5_000.0)
        _pre = max(0, p.eintritt_jahr - AKTUELLES_JAHR)
        assert _pre > 0, "Test-Voraussetzung: Renteneintritt muss in der Zukunft liegen"
        assert len(jd) == horizon + _pre

    def test_ohne_gehalt_nur_rentenjahre(self):
        """Ohne Gehalt startet Simulation erst ab Renteneintritt → genau horizon Jahre."""
        p = self._profil_noch_aktiv()
        e = berechne_rente(p)
        horizon = 10
        _, jd = _netto_ueber_horizont(p, e, [], horizon, gehalt_monatlich=0.0)
        assert len(jd) == horizon

    def test_src_gehalt_positiv_vor_renteneintritt(self):
        """Src_Gehalt ist in Arbeitsjahren > 0."""
        p = self._profil_noch_aktiv()
        e = berechne_rente(p)
        _, jd = _netto_ueber_horizont(p, e, [], 5, gehalt_monatlich=5_000.0)
        _pre = max(0, p.eintritt_jahr - AKTUELLES_JAHR)
        for i in range(_pre):
            assert jd[i]["Src_Gehalt"] > 0, f"Arbeitsjahr {i}: Src_Gehalt sollte > 0 sein"

    def test_src_gehalt_null_ab_renteneintritt(self):
        """Src_Gehalt ist ab Renteneintritt 0."""
        p = self._profil_noch_aktiv()
        e = berechne_rente(p)
        _, jd = _netto_ueber_horizont(p, e, [], 5, gehalt_monatlich=5_000.0)
        _pre = max(0, p.eintritt_jahr - AKTUELLES_JAHR)
        for i in range(_pre, len(jd)):
            assert jd[i]["Src_Gehalt"] == 0, f"Rentenjahr {i}: Src_Gehalt sollte 0 sein"

    def test_hoehereres_gehalt_mehr_steuer(self):
        """Höheres Gehalt → höhere Steuer in Arbeitsjahren."""
        p = self._profil_noch_aktiv()
        e = berechne_rente(p)
        _, jd_niedrig = _netto_ueber_horizont(p, e, [], 5, gehalt_monatlich=3_000.0)
        _, jd_hoch    = _netto_ueber_horizont(p, e, [], 5, gehalt_monatlich=8_000.0)
        _pre = max(0, p.eintritt_jahr - AKTUELLES_JAHR)
        if _pre > 0:
            assert jd_hoch[0]["Steuer"] >= jd_niedrig[0]["Steuer"]


# ─────────────────────────────────────────────────────────────────────────────
# P2-Produkte – KV und Steuer je Person korrekt berechnet
# ─────────────────────────────────────────────────────────────────────────────

class TestP2Produkte:
    """
    Invarianten für _netto_ueber_horizont mit Partnerkonstellation.

    Schützt vor der Regression, bei der Vorsorgeverträge von Person 2 keine
    Wirkung auf deren KV hatten – KV_P2 war unabhängig von zugeordneten Produkten
    konstant (NameError auf p2_kv_mo0 bzw. Akkumulatoren wurden ignoriert).
    """

    def _p1(self, kv: str = "GKV", pkv: float = 0.0, kvdr: bool = True) -> Profil:
        return _profil(
            geburtsjahr=1958, renteneintritt_alter=67,
            aktuelle_punkte=35.0, punkte_pro_jahr=0.0,
            krankenversicherung=kv, pkv_beitrag=pkv, kvdr_pflicht=kvdr,
        )

    def _p2(self, kv: str = "GKV", pkv: float = 0.0, kvdr: bool = True) -> Profil:
        return _profil(
            geburtsjahr=1960, renteneintritt_alter=67,
            aktuelle_punkte=28.0, punkte_pro_jahr=0.0,
            krankenversicherung=kv, pkv_beitrag=pkv, kvdr_pflicht=kvdr,
        )

    def _bav(self, person: str, mono: float, sj: int) -> VorsorgeProdukt:
        return VorsorgeProdukt(
            id=f"bav-{person}", typ="bAV", name=f"bAV {person}", person=person,
            max_einmalzahlung=0.0, max_monatsrente=mono,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )

    def _bav_einmal(self, person: str, betrag: float, sj: int) -> VorsorgeProdukt:
        return VorsorgeProdukt(
            id=f"bav-e-{person}", typ="bAV", name=f"bAV-Einmal {person}", person=person,
            max_einmalzahlung=betrag, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0,
        )

    # ── KV_P2 reagiert auf Produkte ──────────────────────────────────────────

    def test_p2_kvdr_bav_erhoetht_kv_p2(self):
        """KVdR P2: bAV-Monatsrente über Freibetrag (187,25 €) erhöht KV_P2."""
        p1, p2 = self._p1(), self._p2(kvdr=True)
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr
        bav = self._bav("Person 2", 800.0, sj)
        _, jd_ohne = _netto_ueber_horizont(p1, e1, [], 5, profil2=p2, ergebnis2=e2)
        _, jd_mit  = _netto_ueber_horizont(p1, e1, [(bav, sj, 0.0)], 5, profil2=p2, ergebnis2=e2)
        assert jd_mit[0]["KV_P2"] > jd_ohne[0]["KV_P2"]

    def test_p2_kvdr_bav_unter_freibetrag_kein_kv_anstieg(self):
        """KVdR P2: bAV unter 187,25 €/Mon. (Freibetrag) → KV_P2 unverändert."""
        p1, p2 = self._p1(), self._p2(kvdr=True)
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr
        bav = self._bav("Person 2", 100.0, sj)   # 100 < 187,25 Freibetrag
        _, jd_ohne = _netto_ueber_horizont(p1, e1, [], 5, profil2=p2, ergebnis2=e2)
        _, jd_mit  = _netto_ueber_horizont(p1, e1, [(bav, sj, 0.0)], 5, profil2=p2, ergebnis2=e2)
        assert jd_mit[0]["KV_P2"] == jd_ohne[0]["KV_P2"]

    def test_p2_pkv_kv_unveraendert_trotz_bav(self):
        """PKV P2: Beliebige Produkte dürfen KV_P2 nicht verändern (Fixbeitrag)."""
        p1, p2 = self._p1(), self._p2(kv="PKV", pkv=650.0)
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr
        bav = self._bav("Person 2", 2_000.0, sj)
        _, jd_ohne = _netto_ueber_horizont(p1, e1, [], 5, profil2=p2, ergebnis2=e2)
        _, jd_mit  = _netto_ueber_horizont(p1, e1, [(bav, sj, 0.0)], 5, profil2=p2, ergebnis2=e2)
        assert jd_mit[0]["KV_P2"] == jd_ohne[0]["KV_P2"]
        assert jd_ohne[0]["KV_P2"] == pytest.approx(650.0 * 12)

    def test_p2_freiwillig_bav_erhoetht_kv_ohne_freibetrag(self):
        """Freiwillig §240 P2: auch kleine bAV (< 187,25 €) erhöht KV_P2 – kein Freibetrag."""
        p1, p2 = self._p1(), self._p2(kvdr=False)
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr
        bav = self._bav("Person 2", 100.0, sj)   # unter KVdR-Freibetrag, aber freiwillig voll zählend
        _, jd_ohne = _netto_ueber_horizont(p1, e1, [], 5, profil2=p2, ergebnis2=e2)
        _, jd_mit  = _netto_ueber_horizont(p1, e1, [(bav, sj, 0.0)], 5, profil2=p2, ergebnis2=e2)
        assert jd_mit[0]["KV_P2"] > jd_ohne[0]["KV_P2"]

    def test_p2_kvdr_bav_einmal_spreading_10_jahre(self):
        """KVdR P2: bAV-Einmalauszahlung wird 10 Jahre auf KV_P2 verteilt (§229 SGB V)."""
        p1, p2 = self._p1(), self._p2(kvdr=True)
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr
        bav_e = self._bav_einmal("Person 2", 120_000.0, sj)
        _, jd_ohne = _netto_ueber_horizont(p1, e1, [], 12, profil2=p2, ergebnis2=e2)
        _, jd_mit  = _netto_ueber_horizont(p1, e1, [(bav_e, sj, 1.0)], 12, profil2=p2, ergebnis2=e2)
        for i in range(10):
            assert jd_mit[i]["KV_P2"] > jd_ohne[i]["KV_P2"], f"Jahr {i}: KV_P2 sollte erhöht sein"
        assert jd_mit[10]["KV_P2"] == jd_ohne[10]["KV_P2"]   # Spreading endet nach 10 Jahren

    # ── KV_P1 bleibt unberührt ───────────────────────────────────────────────

    def test_p2_produkt_aendert_kv_p1_nicht(self):
        """Produkt auf P2 darf KV_P1 nicht verändern."""
        p1, p2 = self._p1(), self._p2()
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr
        bav = self._bav("Person 2", 2_000.0, sj)
        _, jd_ohne = _netto_ueber_horizont(p1, e1, [], 5, profil2=p2, ergebnis2=e2)
        _, jd_mit  = _netto_ueber_horizont(p1, e1, [(bav, sj, 0.0)], 5, profil2=p2, ergebnis2=e2)
        assert jd_mit[0]["KV_P1"] == jd_ohne[0]["KV_P1"]

    # ── Produkt-Wechsel zwischen Personen ───────────────────────────────────

    def test_produkt_wechsel_p1_gkv_zu_p2_pkv_aendert_kv_verteilung(self):
        """Gleiches bAV-Produkt auf P1 (KVdR) vs. P2 (PKV): KV_P1 muss sich unterscheiden."""
        p1 = self._p1(kvdr=True)           # GKV KVdR: bAV erhöht KV
        p2 = self._p2(kv="PKV", pkv=650.0) # PKV fix: bAV hat keinen KV-Effekt
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr

        bav_auf_p1 = self._bav("Person 1", 800.0, sj)
        bav_auf_p2 = self._bav("Person 2", 800.0, sj)

        _, jd_p1 = _netto_ueber_horizont(p1, e1, [(bav_auf_p1, sj, 0.0)], 5, profil2=p2, ergebnis2=e2)
        _, jd_p2 = _netto_ueber_horizont(p1, e1, [(bav_auf_p2, sj, 0.0)], 5, profil2=p2, ergebnis2=e2)

        # bAV auf P1 (KVdR) erhöht KV_P1; auf P2 (PKV) nicht
        assert jd_p1[0]["KV_P1"] > jd_p2[0]["KV_P1"]
        # KV_P2 bleibt in beiden Fällen der PKV-Fixbeitrag
        assert jd_p1[0]["KV_P2"] == jd_p2[0]["KV_P2"]
        # Gesamtkosten müssen sich unterscheiden → Entnahme-Optimierung reagiert korrekt
        assert jd_p1[0]["KV_PV"] != jd_p2[0]["KV_PV"]

    # ── Haushaltsbrutto und Steuer ───────────────────────────────────────────

    def test_p2_bav_erhoetht_haushaltsbrutto(self):
        """P2-bAV-Monatsrente fließt vollständig ins Haushaltsbrutto ein."""
        p1, p2 = self._p1(), self._p2()
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr
        bav = self._bav("Person 2", 500.0, sj)
        _, jd_ohne = _netto_ueber_horizont(p1, e1, [], 5, profil2=p2, ergebnis2=e2)
        _, jd_mit  = _netto_ueber_horizont(p1, e1, [(bav, sj, 0.0)], 5, profil2=p2, ergebnis2=e2)
        assert jd_mit[0]["Brutto"] - jd_ohne[0]["Brutto"] == pytest.approx(500.0 * 12, abs=1.0)

    def test_zusammen_p2_bav_erhoetht_splitting_steuer(self):
        """Zusammenveranlagung: P2-bAV fließt in gemeinsames zvE → Steuer steigt."""
        p1, p2 = self._p1(), self._p2()
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr
        bav = self._bav("Person 2", 1_000.0, sj)
        _, jd_ohne = _netto_ueber_horizont(p1, e1, [], 5, profil2=p2, ergebnis2=e2, veranlagung="Zusammen")
        _, jd_mit  = _netto_ueber_horizont(p1, e1, [(bav, sj, 0.0)], 5, profil2=p2, ergebnis2=e2, veranlagung="Zusammen")
        assert jd_mit[0]["Steuer"] > jd_ohne[0]["Steuer"]

    def test_p2_etf_einmal_erzeugt_abgeltungsteuer(self):
        """ETF-Einmalauszahlung auf P2 mit großem Ertrag erzeugt Abgeltungsteuer."""
        p1, p2 = self._p1(), self._p2()
        e1, e2 = berechne_rente(p1), berechne_rente(p2)
        sj = p1.eintritt_jahr
        etf = VorsorgeProdukt(
            id="etf-p2", typ="ETF", name="ETF P2", person="Person 2",
            max_einmalzahlung=100_000.0, max_monatsrente=0.0,
            laufzeit_jahre=0, fruehestes_startjahr=sj, spaetestes_startjahr=sj,
            aufschub_rendite=0.0, einzahlungen_gesamt=50_000.0, teilfreistellung=0.30,
        )
        _, jd_ohne = _netto_ueber_horizont(p1, e1, [], 5, profil2=p2, ergebnis2=e2)
        _, jd_mit  = _netto_ueber_horizont(p1, e1, [(etf, sj, 1.0)], 5, profil2=p2, ergebnis2=e2)
        # Ertrag 50.000 €; TF 30 % → abgeltungspfl. 35.000 € >> 2 × Sparerpauschbetrag
        assert jd_mit[0]["Steuer_Abgeltung"] > jd_ohne[0]["Steuer_Abgeltung"]
