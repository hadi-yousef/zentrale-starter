"""Tests zu den Befunden der Code-Prüfung (S-01 bis R-01). Nur Python, keine Pakete, alles in Testordnern.

  python3 -I -m unittest discover -s tests -v        (Windows: py -I -m unittest discover -s tests -v)

Jeder Test baut den Fehlerfall nach und prüft, dass er nicht mehr auftritt. Dazu gibt es Gegenfälle: Was erlaubt ist,
muss weiter gehen. Nichts außerhalb der Testordner wird angefasst; die Zentrale wird nicht gestartet.
"""
import contextlib
import importlib
import importlib.util
import io
import ipaddress
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

HIER = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="zs-test-")).resolve()
os.environ["ZENTRALE_DATEN"] = str(TMP / "daten")
os.environ["ZENTRALE_NOTIZEN"] = str(TMP / "daten" / "notizen")
os.environ["ZENTRALE_SCHLUESSEL_ORDNER"] = str(TMP / "keys")
os.environ["AUFRAEUMEN_PROTOKOLL"] = str(TMP / "protokoll.jsonl")
os.environ["FINANZ_DIR"] = str(TMP / "daten" / "finanzen")
for _p in (HIER / "zentrale", HIER / "aufraeumen", HIER):
    sys.path.insert(0, str(_p))

WIN = os.name == "nt"
ALT = time.time() - 30 * 86400


def alt_machen(p):
    """Datei oder ganzen Baum auf „vor 30 Tagen“ setzen."""
    p = Path(p)
    for d, dirs, files in os.walk(p):
        for x in files + dirs:
            if not os.path.islink(os.path.join(d, x)):
                os.utime(os.path.join(d, x), (ALT, ALT))
    os.utime(p, (ALT, ALT))


def link(ziel, name):
    try:
        os.symlink(ziel, name, target_is_directory=Path(ziel).is_dir())
    except (OSError, NotImplementedError) as e:
        raise unittest.SkipTest(f"Verknüpfung nicht möglich: {e}")


def skript(name, *args, env=None):
    # ohne -I: die Skripte laden ihre Nachbarn (protokoll.py) aus ihrem eigenen Ordner; gestartet wird im Testordner
    e = {k: v for k, v in {**os.environ, **(env or {})}.items() if k != "PYTHONPATH"}
    return subprocess.run([sys.executable, "-B", str(HIER / "aufraeumen" / name), *map(str, args)], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", env=e, cwd=str(TMP))


def neuer_ordner(name):
    d = TMP / name
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


# ---------- S-01: Titel im Blatt ----------

class S01_TitelAlsText(unittest.TestCase):
    def test_renderSheet_maskiert_titel_und_untertitel(self):
        h = (HIER / "zentrale" / "index.src.html").read_text(encoding="utf-8")
        self.assertIn("<h2>${esc(s.title)}</h2>", h)
        self.assertIn("<p>${esc(s.sub)}</p>", h)
        # keine doppelte Maskierung mehr in Titeln (sonst stünde „&amp;“ im Titel)
        self.assertNotIn("title: esc(", h)
        self.assertNotIn("sub: esc(", h)

    def test_gebaute_seite_ist_aktuell(self):
        src = (HIER / "zentrale" / "index.src.html").read_text(encoding="utf-8")
        fertig = (HIER / "zentrale" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<h2>${esc(s.title)}</h2>", fertig, "index.html neu bauen: python3 zentrale/bauen.py")
        self.assertEqual(src.count("title: pv("), fertig.count("title: pv("))


# ---------- S-04: Notizen über Verknüpfungen ----------

class S04_NotizGrenze(unittest.TestCase):
    def setUp(self):
        import notizen
        self.N = notizen
        self.wurzel = neuer_ordner("notizen-s04")
        self.aussen = neuer_ordner("aussen-s04")
        notizen.WURZEL = self.wurzel
        notizen.PAPIERKORB = self.wurzel / ".papierkorb"
        notizen._kopf.clear()

    def test_neu_schreibt_nicht_durch_ordner_verknuepfung(self):
        link(self.aussen, self.wurzel / "Geteilt")
        with self.assertRaises(ValueError):
            self.N.neu("Geteilt", "Test", "Inhalt")
        self.assertEqual(list(self.aussen.iterdir()), [], "es wurde außerhalb geschrieben")

    def test_neu_legt_keinen_ordner_draussen_an(self):
        link(self.aussen, self.wurzel / "Geteilt")
        with self.assertRaises(ValueError):
            self.N.neu("Geteilt/Neu/Tiefer", "Test", "Inhalt")
        self.assertFalse((self.aussen / "Neu").exists())

    def test_neu_schreibt_nicht_durch_kaputte_datei_verknuepfung(self):
        link(self.aussen / "gibtsnicht.md", self.wurzel / "Test.md")
        r = self.N.neu("", "Test", "Inhalt")
        self.assertEqual(r["pfad"], "Test 2.md")
        self.assertFalse((self.aussen / "gibtsnicht.md").exists())

    def test_liste_und_suche_zeigen_keine_datei_von_aussen(self):
        (self.aussen / "geheim.md").write_text("# Geheim\n\nwort-von-aussen\n", encoding="utf-8")
        link(self.aussen / "geheim.md", self.wurzel / "Verweis.md")
        self.N.neu("", "Eigene", "wort-von-innen")
        pfade = [n["pfad"] for n in self.N.liste()["notizen"]]
        self.assertNotIn("Verweis.md", pfade)
        self.assertEqual(self.N.suche("wort-von-aussen"), [])
        self.assertEqual(len(self.N.suche("wort-von-innen")), 1)

    def test_gegenfall_normale_ordner_gehen(self):
        r = self.N.neu("Projekte/Haus", "Plan", "Text")
        self.assertEqual(r["pfad"], "Projekte/Haus/Plan.md")
        self.assertEqual(self.N.lesen("Projekte/Haus/Plan.md")["titel"], "Plan")


# ---------- D-01 bis D-03: Sicherung ----------

class D01_D03_Sicherung(unittest.TestCase):
    def test_d01_gleichnamige_quellen_brechen_vor_dem_kopieren_ab(self):
        t = neuer_ordner("d01")
        for x, inhalt in (("A", "erste"), ("B", "zweite")):
            (t / x / "Documents").mkdir(parents=True)
            (t / x / "Documents" / "bericht.txt").write_text(inhalt, encoding="utf-8")
        r = skript("sichern.py", t / "A" / "Documents", t / "B" / "Documents", "--ziel", t / "ziel")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Kopiert wurde nichts", r.stdout + r.stderr)
        self.assertFalse((t / "ziel").exists() and any((t / "ziel").rglob("*")), "vor dem Abbruch wurde kopiert")

    def test_d01_gegenfall_verschiedene_namen_beide_vollstaendig(self):
        t = neuer_ordner("d01b")
        for x, inhalt in (("Documents", "erste"), ("Pictures", "zweite")):
            (t / x).mkdir()
            (t / x / "a.txt").write_text(inhalt, encoding="utf-8")
        r = skript("sichern.py", t / "Documents", t / "Pictures", "--ziel", t / "ziel")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual((t / "ziel" / "Documents" / "a.txt").read_text(encoding="utf-8"), "erste")
        self.assertEqual((t / "ziel" / "Pictures" / "a.txt").read_text(encoding="utf-8"), "zweite")
        v = json.loads((t / "ziel" / "_sicherung.json").read_text(encoding="utf-8"))
        self.assertTrue(v["vollstaendig"])
        self.assertEqual(sorted(d["pfad"] for d in v["dateien"]), ["Documents/a.txt", "Pictures/a.txt"])

    def test_d02_eigene_ordner_mit_mehrdeutigem_namen_werden_gesichert(self):
        t = neuer_ordner("d02")
        q = t / "Documents"
        for n in ("bin", "build", "dist", "out", "target"):
            (q / n).mkdir(parents=True)
            (q / n / "eigen.txt").write_text(n, encoding="utf-8")
        (q / "app").mkdir()
        (q / "app" / "package.json").write_text("{}", encoding="utf-8")
        (q / "app" / "dist").mkdir()
        (q / "app" / "dist" / "bundle.js").write_text("x", encoding="utf-8")
        (q / "app" / "node_modules").mkdir()
        r = skript("sichern.py", q, "--ziel", t / "ziel")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for n in ("bin", "build", "dist", "out", "target"):
            self.assertTrue((t / "ziel" / "Documents" / n / "eigen.txt").is_file(), f"{n} fehlt in der Sicherung")
        self.assertFalse((t / "ziel" / "Documents" / "app" / "dist").exists(), "Bau-Rest im Projekt sollte fehlen")
        v = json.loads((t / "ziel" / "_sicherung.json").read_text(encoding="utf-8"))
        gruende = {Path(x["pfad"]).name: x["grund"] for x in v["ausgelassen"]}
        self.assertIn("dist", gruende)
        self.assertIn("node_modules", gruende)
        self.assertIn("Ausgelassen", r.stdout)

    @unittest.skipIf(WIN or (hasattr(os, "geteuid") and os.geteuid() == 0), "Leserechte lassen sich hier nicht entziehen")
    def test_d03_nicht_lesbarer_ordner_ist_ein_fehler(self):
        t = neuer_ordner("d03")
        q = t / "Documents"
        (q / "zu").mkdir(parents=True)
        (q / "zu" / "x.txt").write_text("x", encoding="utf-8")
        (q / "offen.txt").write_text("y", encoding="utf-8")
        os.chmod(q / "zu", 0)
        try:
            r = skript("sichern.py", q, "--ziel", t / "ziel")
            p = skript("sichern.py", q, "--ziel", t / "ziel2", "--probe")
        finally:
            os.chmod(q / "zu", 0o755)
        self.assertNotEqual(r.returncode, 0, "unvollständige Sicherung meldet Erfolg")
        self.assertIn("UNVOLLSTÄNDIG", r.stdout + r.stderr)
        self.assertNotEqual(p.returncode, 0, "auch die Probe muss den Lesefehler melden")
        v = json.loads((t / "ziel" / "_sicherung.json").read_text(encoding="utf-8"))
        self.assertFalse(v["vollstaendig"])


# ---------- D-04, D-05: Putzrunde ----------

class D04_D05_Putzen(unittest.TestCase):
    def setUp(self):
        self.P = importlib.import_module("putzen")

    def projekt(self, ort):
        (ort / "app" / ".venv").mkdir(parents=True)
        (ort / "app" / ".venv" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
        (ort / "app" / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
        alt_machen(ort / "app")

    def test_d04_verknuepfte_wurzel_wird_nicht_durchsucht(self):
        heim, aussen = neuer_ordner("d04-heim"), neuer_ordner("d04-aussen")
        self.projekt(aussen)
        link(aussen, heim / "Projects")
        F = self.P.suchen(self.P.Orte(heim), 7, [])
        self.assertEqual([f for f in F if str(aussen) in str(Path(f["pfad"]).resolve())], [])

    def test_d04_gegenfall_echter_ordner_wird_gefunden(self):
        heim = neuer_ordner("d04b-heim")
        (heim / "Projects").mkdir()
        self.projekt(heim / "Projects")
        F = self.P.suchen(self.P.Orte(heim), 7, [])
        self.assertEqual([f["pfad"].name for f in F], [".venv"])
        self.assertTrue(self.P.in_grenze(F[0]["pfad"], F[0]["wurzel"]))

    def test_d04_grenze_vor_dem_entfernen(self):
        heim, aussen = neuer_ordner("d04c-heim"), neuer_ordner("d04c-aussen")
        (heim / "Projects").mkdir()
        (aussen / "x").mkdir()
        link(aussen, heim / "Projects" / "verweis")
        self.assertFalse(self.P.in_grenze(heim / "Projects" / "verweis" / "x", heim / "Projects"))
        self.assertFalse(self.P.in_grenze(aussen / "x", heim / "Projects"))

    def test_d05_frische_datei_tief_im_temp_ordner_haelt_ihn(self):
        heim = neuer_ordner("d05-heim")
        temp = heim / "AppData" / "Local" / "Temp"
        (temp / "arbeit" / "unter").mkdir(parents=True)
        (temp / "arbeit" / "unter" / "neu.txt").write_text("frisch", encoding="utf-8")
        (temp / "fertig" / "unter").mkdir(parents=True)
        (temp / "fertig" / "unter" / "alt.txt").write_text("alt", encoding="utf-8")
        alt_machen(temp / "fertig")
        os.utime(temp / "arbeit" / "unter", (ALT, ALT))
        os.utime(temp / "arbeit", (ALT, ALT))   # Ordnerzeiten alt, die Datei darin frisch
        namen = [f["pfad"].name for f in self.P.temp_alt(self.P.Orte(heim), 7)]
        self.assertNotIn("arbeit", namen)
        self.assertIn("fertig", namen)

    def test_d05_putzrunde_entfernt_nur_altes(self):
        heim = neuer_ordner("d05b-heim")
        temp = heim / "AppData" / "Local" / "Temp"
        (temp / "arbeit" / "unter").mkdir(parents=True)
        (temp / "arbeit" / "unter" / "neu.txt").write_text("frisch", encoding="utf-8")
        (temp / "fertig").mkdir()
        (temp / "fertig" / "alt.txt").write_text("alt", encoding="utf-8")
        alt_machen(temp / "fertig")
        os.utime(temp / "arbeit" / "unter", (ALT, ALT))
        os.utime(temp / "arbeit", (ALT, ALT))
        r = skript("putzen.py", "--wurzel", heim, "--los")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((temp / "arbeit" / "unter" / "neu.txt").is_file())
        self.assertFalse((temp / "fertig").exists())


# ---------- D-06: Protokoll vor dem Verschieben prüfen ----------

class D06_Protokoll(unittest.TestCase):
    def test_kaputtes_protokoll_verschiebt_nichts(self):
        t = neuer_ordner("d06")
        prot = t / "protokoll.jsonl"
        prot.write_text('{"nr": 1, "art": "verschieben", "von": "a", "nach": "b"}\n{"nr": 2, "art": "verschie', encoding="utf-8")
        (t / "datei.txt").write_text("x", encoding="utf-8")
        r = skript("verschieben.py", t / "datei.txt", t / "neu.txt", env={"AUFRAEUMEN_PROTOKOLL": str(prot)})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("kaputt", r.stdout + r.stderr)
        self.assertTrue((t / "datei.txt").is_file(), "die Datei wurde trotz kaputtem Protokoll verschoben")
        self.assertFalse((t / "neu.txt").exists())

    def test_gegenfall_heiles_protokoll_verschiebt_und_traegt_ein(self):
        t = neuer_ordner("d06b")
        prot = t / "protokoll.jsonl"
        (t / "datei.txt").write_text("x", encoding="utf-8")
        r = skript("verschieben.py", t / "datei.txt", t / "neu.txt", env={"AUFRAEUMEN_PROTOKOLL": str(prot)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        e = [json.loads(z) for z in prot.read_text(encoding="utf-8").splitlines()]
        self.assertEqual((e[-1]["nr"], e[-1]["art"]), (1, "verschieben"))
        r = skript("rueckgaengig.py", "1", env={"AUFRAEUMEN_PROTOKOLL": str(prot)})
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((t / "datei.txt").is_file())


# ---------- D-07: Update sichert nachweislich ----------

class D07_Update(unittest.TestCase):
    def git(self, *a, cwd=None):
        return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, *a], cwd=cwd, env=self.env, check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_vorhandener_zweigname_wird_nicht_wiederverwendet(self):
        if not shutil.which("git"):
            self.skipTest("git fehlt")
        t = neuer_ordner("d07")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
                        GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@localhost",
                        GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@localhost")
        oben, klon = t / "oben", t / "klon"
        self.git("init", "-q", str(oben))
        self.git("symbolic-ref", "HEAD", "refs/heads/main", cwd=oben)
        (oben / "zentrale").mkdir()
        (oben / "zentrale" / "hub.py").write_text('FASSUNG = "test"\n', encoding="utf-8")
        (oben / "arbeit.txt").write_text("OBEN\n", encoding="utf-8")
        self.git("add", ".", cwd=oben)
        self.git("commit", "-qm", "start", cwd=oben)
        self.git("clone", "-q", str(oben), str(klon))
        self.git("branch", "sicherung-vor-update-20261031-120000", cwd=klon)   # gibt es schon, zeigt auf den alten Stand
        (klon / "arbeit.txt").write_text("EIGENE AENDERUNG\n", encoding="utf-8")
        (klon / "neu.txt").write_text("NEUE DATEI\n", encoding="utf-8")

        spec = importlib.util.spec_from_file_location("einrichten_test", HIER / "einrichten.py")
        m = importlib.util.module_from_spec(spec)
        echt_run, echt_zeit = subprocess.run, time.strftime

        def run(args, **kw):
            if args[:2] == [m.sys.executable, str(klon / "regeln_verteilen.py")]:
                return subprocess.CompletedProcess(args, 0, "", "")
            assert args[:3] == ["git", "-C", str(klon)], args
            kw["env"] = {**kw.get("env", self.env), **{k: v for k, v in self.env.items() if k.startswith("GIT_C")}}
            return echt_run(args, **kw)

        with mock.patch.dict(os.environ, self.env, clear=True):
            spec.loader.exec_module(m)
            m.HIER = klon
            aus = io.StringIO()
            with mock.patch.object(m.subprocess, "run", side_effect=run), mock.patch.object(m, "autostart", return_value=[]), \
                    mock.patch.object(m, "holen", side_effect=AssertionError("kein Netz")), \
                    mock.patch.object(time, "strftime", side_effect=lambda f, *a: "20261031-120000" if f == "%Y%m%d-%H%M%S" else echt_zeit(f, *a)), \
                    contextlib.redirect_stdout(aus):
                m.update()
        zweige = self.git("branch", "--format=%(refname:short)", cwd=klon).split()
        self.assertIn("sicherung-vor-update-20261031-120000-2", zweige, aus.getvalue())
        self.assertEqual(self.git("show", "sicherung-vor-update-20261031-120000-2:arbeit.txt", cwd=klon), "EIGENE AENDERUNG")
        self.assertEqual(self.git("show", "sicherung-vor-update-20261031-120000-2:neu.txt", cwd=klon), "NEUE DATEI")
        self.assertEqual(self.git("show", "sicherung-vor-update-20261031-120000:arbeit.txt", cwd=klon), "OBEN", "alter Zweig verändert")


# ---------- S-03: Wer Aufgaben abhaken darf ----------

class S03_Abhaken(unittest.TestCase):
    def setUp(self):
        import hub, pos
        self.B, self.pos = hub.BESITZER, pos

    def offen(self, aid):
        return not next(a for a in self.pos._lesen()["aufgaben"] if a["id"] == aid)["erledigt"]

    def test_agent_hakt_aufgabe_des_besitzers_nicht_ab(self):
        a = self.pos.aufgabe_neu(self.B, {"titel": "Sache des Besitzers", "fuer": self.B})
        with self.assertRaises(PermissionError):
            self.pos.aufgabe_aendern("codex", a["id"], {"erledigt": True})
        self.assertTrue(self.offen(a["id"]), "die Änderung wurde trotz Fehler gespeichert")
        self.assertTrue(self.pos.aufgabe_aendern(self.B, a["id"], {"erledigt": True})["erledigt"])

    def test_fremder_agent_hakt_nicht_ab_anleger_und_zustaendiger_schon(self):
        a = self.pos.aufgabe_neu("codex", {"titel": "Besitzer: A oder B wählen", "fuer": self.B})
        with self.assertRaises(PermissionError):
            self.pos.aufgabe_aendern("claude", a["id"], {"erledigt": True})
        self.assertTrue(self.pos.aufgabe_aendern("codex", a["id"], {"erledigt": True})["erledigt"])   # im Chat erledigt
        b = self.pos.aufgabe_neu("claude", {"titel": "für codex", "fuer": "codex"})
        self.assertTrue(self.pos.aufgabe_aendern("codex", b["id"], {"erledigt": True})["erledigt"])
        c = self.pos.aufgabe_neu("codex", {"titel": "eigene"})
        self.assertTrue(self.pos.aufgabe_aendern("codex", c["id"], {"erledigt": True})["erledigt"])


# ---------- R-01: Kennungen ohne Doppel ----------

class R01_Kennungen(unittest.TestCase):
    def test_neue_id_nimmt_nie_eine_belegte(self):
        import hub
        L = [{"id": format(i, "06x")} for i in range(100000)]
        folge = iter(["000001", "000abc", "0186a0"])   # zwei belegte, dann eine freie
        with mock.patch.object(hub.secrets, "token_hex", side_effect=lambda n: next(folge)):
            self.assertEqual(hub.neue_id(L), "0186a0")

    def test_erzwungene_doppelte_kennung_trifft_nicht_den_falschen_eintrag(self):
        import hub, pos
        folge = iter(["aaaaaa", "aaaaaa", "bbbbbb"])
        with mock.patch.object(hub.secrets, "token_hex", side_effect=lambda n: next(folge)):
            a = pos.aufgabe_neu("codex", {"titel": "erste"})
            b = pos.aufgabe_neu("codex", {"titel": "zweite"})
        self.assertNotEqual(a["id"], b["id"])
        pos.aufgabe_aendern("codex", b["id"], {"titel": "zweite geändert"})
        A = {x["id"]: x["titel"] for x in pos._lesen()["aufgaben"]}
        self.assertEqual((A[a["id"]], A[b["id"]]), ("erste", "zweite geändert"))


# ---------- F-01 bis F-04, S-05: Finanzen ----------

class F_Finanzen(unittest.TestCase):
    def setUp(self):
        import hub, finanzen
        self.B, self.F = hub.BESITZER, finanzen
        p = Path(os.environ["ZENTRALE_DATEN"]) / "finanzen.json"
        if p.exists():
            p.unlink()

    def test_f01_gleicher_betrag_ist_nicht_gleicher_einkauf(self):
        F = self.F
        F.buchung_neu(self.B, {"betrag": "-20", "text": "Essen", "gegenpartei": "Café Beispiel", "datum": "2026-10-20", "konto": "Bargeld"})
        erg = F._einfuegen(F._lesen(), self.B, [{"datum": "2026-10-21", "betrag_cent": -2000, "text": "Tankstelle Beispiel", "gegenpartei": "Tankstelle"}],
                           "csv", "privat", "Girokonto")
        self.assertEqual((erg["neu"], erg["zusammengefuehrt"]), (1, 0))
        self.assertIn("Vielleicht dieselbe", erg["buchungen"][0]["notiz"])

    def test_f01_gegenfall_echte_doppelte_wird_zusammengefuehrt(self):
        F = self.F
        F.buchung_neu(self.B, {"betrag": "-35", "text": "Tanken", "datum": "2026-10-25"})
        erg = F._einfuegen(F._lesen(), self.B, [{"datum": "2026-10-26", "betrag_cent": -3500, "text": "Tankstelle Beispiel", "gegenpartei": "Tankstelle"}],
                           "csv", "privat", "Girokonto")
        self.assertEqual(erg["zusammengefuehrt"], 1)

    def test_f02_gleiche_nummer_anderer_aussteller_ist_eine_neue_rechnung(self):
        F = self.F
        a = F.rechnung_neu(self.B, {"name": "Lieferant A", "betrag": "50", "rechnungsnr": "2026-001", "bereich": "privat", "bezahlt": True})
        b = F.rechnung_neu(self.B, {"name": "Lieferant B", "betrag": "80", "rechnungsnr": "2026-001", "bereich": "firma"})
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(b["status"], "offen")
        c = F.rechnung_neu(self.B, {"name": "Lieferant B", "betrag": "80", "rechnungsnr": "2026-001", "bereich": "firma", "notiz": "ergänzt"})
        self.assertEqual(c["id"], b["id"], "gleiche Nummer, Aussteller und Bereich ist dieselbe Rechnung")

    def test_f03_privatbuchung_bezahlt_keine_firmenrechnung(self):
        F = self.F
        r = F.rechnung_neu(self.B, {"name": "Laden", "betrag": "20", "bereich": "firma"})
        d = F._lesen()
        x = {"betrag_cent": -2000, "bereich": "privat", "gegenpartei": "Laden", "text": "Laden Einkauf", "datum": F.heute().isoformat(),
             "nr": 99, "kategorie": "lebensmittel"}
        F._nach_buchungen(d, [x])
        self.assertEqual(next(y for y in d["rechnungen"] if y["id"] == r["id"])["status"], "offen")
        x["bereich"] = "firma"
        F._nach_buchungen(d, [x])
        self.assertEqual(next(y for y in d["rechnungen"] if y["id"] == r["id"])["status"], "bezahlt")

    def test_f04_fremdwaehrung_nicht_als_euro(self):
        F = self.F
        d = F._lesen()
        erg = F._einfuegen(d, self.B, [{"datum": "2026-10-22", "betrag_cent": -10000, "text": "Hotel", "gegenpartei": "Hotel", "waehrung": "USD"}],
                           "csv", "privat", "Karte")
        self.assertEqual(erg["neu"], 0)
        self.assertTrue(any("USD" in f for f in erg["fehler"]))
        erg = F._einfuegen(d, self.B, [{"datum": "2026-10-22", "betrag_cent": -1000, "text": "Bäcker", "gegenpartei": "Bäcker", "waehrung": "EUR"}],
                           "csv", "privat", "Karte")
        self.assertEqual(erg["neu"], 1)

    def test_s05_csv_ohne_formeln(self):
        F = self.F
        for t in ("=1+1", "+1", "-1+2", "@SUMME(A1)", " =1+1", "\t=1", "\r=1"):
            self.assertTrue(F._zelle(t).startswith("'"), repr(t))
        self.assertEqual(F._zelle("Laden"), "Laden")
        F.buchung_neu(self.B, {"betrag": "-5", "text": "=1+1", "gegenpartei": "@x", "notiz": "+2", "datum": "2026-10-20"})
        F._exportieren()
        csv = (Path(os.environ["FINANZ_DIR"]) / "Privat" / "Haushaltsbuch.csv").read_text(encoding="utf-8-sig")
        zeile = [z for z in csv.splitlines() if "1+1" in z][0]
        self.assertIn("'=1+1", zeile)
        self.assertIn("'@x", zeile)
        self.assertIn("'+2", zeile)
        self.assertIn("-5,00", zeile, "Beträge bleiben Zahlen")


# ---------- S-02: Andere Geräte nur verschlüsselt ----------

def adr(netz, n=1):
    """Eine Beispiel-Adresse aus einem Netz (so steht keine echte Adresse in den Tests)."""
    return str(ipaddress.ip_network(netz)[n])


TS4, TS6 = adr("100.64.0.0/10"), adr("fd7a:115c:a1e0::/48")
LAN = adr("192.168.0.0/16", 20)


class S02_NurTailscale(unittest.TestCase):
    def setUp(self):
        import app, hub
        self.app, self.hub = app, hub
        self.alt = (hub.HEIMNETZ, hub.LAN_OFFEN)
        hub.HEIMNETZ, hub.LAN_OFFEN = True, False
        hub.ABGEWIESEN.clear()

    def tearDown(self):
        self.hub.HEIMNETZ, self.hub.LAN_OFFEN = self.alt
        self.hub.ABGEWIESEN.clear()

    def test_heimnetz_nimmt_nur_diesen_rechner_und_tailscale(self):
        ok = self.app.absender_ok
        for ip in ("127.0.0.1", "::1", TS4, adr("100.64.0.0/10", -2), TS6, "::ffff:" + TS4):
            self.assertTrue(ok(ip), ip)
        for ip in (LAN, adr("10.0.0.0/8", 5), adr("172.16.0.0/12", 7), adr("169.254.0.0/16", 9), "8.8.8.8",
                   adr("100.128.0.0/16"), "fe80::1", "unsinn"):
            self.assertFalse(ok(ip), ip)
        self.assertIn(LAN, self.hub.ABGEWIESEN, "die Seite soll zeigen, wer abgewiesen wurde")
        self.assertNotIn("8.8.8.8", self.hub.ABGEWIESEN)

    def test_schalter_oeffnet_nur_das_heimnetz(self):
        self.hub.LAN_OFFEN = True
        ok = self.app.absender_ok
        self.assertTrue(ok(LAN))
        self.assertTrue(ok(TS4))
        self.assertFalse(ok("8.8.8.8"), "das Internet bleibt draußen")

    def test_ohne_heimnetz_lauscht_sie_ohnehin_nur_lokal(self):
        self.hub.HEIMNETZ = False
        self.assertTrue(self.app.absender_ok("127.0.0.1"))

    def test_anleitung_holt_den_melder_nicht_ueber_http(self):
        texte = [(HIER / n).read_text(encoding="utf-8") for n in ("docs/HOMELAB.md", "start.py", "melder/melder.py")]
        for x in texte:
            self.assertNotIn("/melder.py', 'melder.py'", x.replace("main/melder/melder.py', 'melder.py'", ""))
            self.assertNotRegex(x, r"(curl[^\n]*|von der Zentrale holen[^\n]*)http://")
        self.assertIn("https://raw.githubusercontent.com/", texte[0])

    def test_adressen_ohne_heimnetz_adresse(self):
        import geraete
        with mock.patch.object(geraete, "tailscale_ip", return_value=TS4), \
                mock.patch.object(geraete, "_eigene_ip", return_value=LAN), mock.patch.dict(os.environ, {"ZENTRALE_ADRESSEN": ""}):
            self.assertEqual(geraete.adressen(), [f"http://{TS4}:{self.hub.PORT}"])
            self.hub.LAN_OFFEN = True
            self.assertEqual(len(geraete.adressen()), 2)

    def test_tailscale_adresse_vom_befehl(self):
        import geraete
        for ausgabe, soll in ((TS4 + "\n", TS4), (LAN + "\n", ""), ("", "")):
            geraete._ts["zeit"] = 0
            with mock.patch.object(geraete.shutil, "which", return_value="tailscale"), \
                    mock.patch.object(geraete.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, ausgabe, "")):
                self.assertEqual(geraete.tailscale_ip(), soll)
        geraete._ts["zeit"] = 0


# ---------- Rückmeldungen aus dem Betrieb: Update, Regeln, Client ----------
def _git_umgebung():
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
               GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@localhost",
               GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@localhost")
    return env


def _git(env, *a, cwd=None):
    return subprocess.run(["git", "-c", "core.hooksPath=" + os.devnull, *a], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


VORLAGE = "# Regeln\n\n## Sprache\n- Deutsch.\n\n## Löschen\n- Nie löschen.\n"


class EigeneRegeln(unittest.TestCase):
    def setUp(self):
        if not shutil.which("git"):
            self.skipTest("git fehlt")
        self.t = neuer_ordner("regeln")
        self.env = _git_umgebung()
        self.heim = self.t / "heim"
        self.heim.mkdir()
        self.env.update(HOME=str(self.heim), USERPROFILE=str(self.heim))
        self.env.pop("CODEX_HOME", None)
        self.env.pop("CLAUDE_CONFIG_DIR", None)
        self.o = self.t / "zentrale"
        _git(self.env, "init", "-q", str(self.o))
        _git(self.env, "symbolic-ref", "HEAD", "refs/heads/main", cwd=self.o)
        shutil.copy(HIER / "regeln_verteilen.py", self.o / "regeln_verteilen.py")
        (self.o / ".gitignore").write_text("REGELN.lokal.md\nREGELN.ziele.txt\n", encoding="utf-8")
        (self.o / "REGELN.md").write_text(VORLAGE, encoding="utf-8")
        _git(self.env, "add", ".", cwd=self.o)
        _git(self.env, "commit", "-qm", "start", cwd=self.o)
        self.anfang = _git(self.env, "rev-parse", "HEAD", cwd=self.o)

    def verteilen(self, *args, env=None):
        return subprocess.run([sys.executable, "-B", str(self.o / "regeln_verteilen.py"), *args], env=env or self.env,
                              capture_output=True, text=True, encoding="utf-8")

    def update_nachstellen(self, eigener_text):
        """Wie update(): Eigenes liegt im Sicherungszweig, REGELN.md ist wieder die neue Vorlage."""
        _git(self.env, "checkout", "-qb", "sicherung-vor-update-20261101-120000", cwd=self.o)
        (self.o / "REGELN.md").write_text(eigener_text, encoding="utf-8")
        _git(self.env, "commit", "-qam", "eigene Regeln", "--allow-empty", cwd=self.o)
        _git(self.env, "checkout", "-q", "main", cwd=self.o)
        (self.o / "REGELN.md").write_text(VORLAGE + "\n## Neu\n- Neue Regel der Vorlage.\n", encoding="utf-8")
        _git(self.env, "commit", "-qam", "neue Vorlage", cwd=self.o)

    def test_eigene_regel_kommt_aus_der_sicherung_und_bleibt(self):
        self.update_nachstellen(VORLAGE.replace("- Deutsch.\n", "- Deutsch.\n- Immer mit Beispiel.\n"))
        r = self.verteilen()
        self.assertEqual(r.returncode, 0, r.stderr)
        lokal = (self.o / "REGELN.lokal.md").read_text(encoding="utf-8")
        self.assertIn("- Immer mit Beispiel.", lokal)
        self.assertIn("## Sprache", lokal, "die Zeile soll ihren Abschnitt behalten")
        self.assertNotIn("Nie löschen", lokal, "Zeilen der Vorlage gehören nicht hinein")
        anleitung = (self.heim / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("- Immer mit Beispiel.", anleitung)
        self.assertIn("Neue Regel der Vorlage", anleitung)
        self.assertLess(anleitung.index("Neue Regel der Vorlage"), anleitung.index("Immer mit Beispiel"))
        self.assertEqual(_git(self.env, "status", "--porcelain", cwd=self.o), "", "die eigene Datei darf Git nicht stören")
        self.verteilen()
        self.assertEqual((self.o / "REGELN.lokal.md").read_text(encoding="utf-8"), lokal, "zweimal aufrufen doppelt nichts")

    def test_entfernte_datei_kommt_nicht_wieder(self):
        self.update_nachstellen(VORLAGE + "- Eigene Zeile.\n")
        self.verteilen()
        (self.o / "REGELN.lokal.md").unlink()
        self.verteilen()
        self.assertFalse((self.o / "REGELN.lokal.md").exists())

    def test_vorhandene_eigene_regeln_bleiben_erhalten(self):
        (self.o / "REGELN.lokal.md").write_text("- Schon da.\n", encoding="utf-8")
        self.update_nachstellen(VORLAGE + "- Schon da.\n- Noch neu.\n")
        self.verteilen()
        lokal = (self.o / "REGELN.lokal.md").read_text(encoding="utf-8")
        self.assertEqual(lokal.count("- Schon da."), 1, lokal)
        self.assertIn("- Noch neu.", lokal)

    def test_gegenfall_unveraenderte_vorlage_legt_nichts_an(self):
        self.update_nachstellen(VORLAGE)
        self.verteilen()
        self.assertFalse((self.o / "REGELN.lokal.md").exists())

    def test_gegenfall_ohne_git_geht_es_auch(self):
        shutil.rmtree(self.o / ".git", onerror=lambda f, p, e: (os.chmod(p, 0o700), f(p)))
        r = self.verteilen()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Nie löschen", (self.heim / ".claude" / "CLAUDE.md").read_text(encoding="utf-8"))

    def test_weitere_ordner_aus_der_umgebung(self):
        env = dict(self.env, CLAUDE_CONFIG_DIR=str(self.t / "claude2"), CODEX_HOME=str(self.t / "codex2"))
        self.assertEqual(self.verteilen(env=env).returncode, 0)
        for p in (self.t / "claude2" / "CLAUDE.md", self.t / "codex2" / "AGENTS.md", self.heim / ".claude" / "CLAUDE.md",
                  self.heim / ".codex" / "AGENTS.md"):
            self.assertIn("Nie löschen", p.read_text(encoding="utf-8"), str(p))

    def test_ziel_wird_gemerkt(self):
        ziel = self.t / "t3" / "AGENTS.md"
        self.assertEqual(self.verteilen("--ziel", str(ziel)).returncode, 0)
        self.assertIn("Nie löschen", ziel.read_text(encoding="utf-8"))
        (self.o / "REGELN.md").write_text(VORLAGE + "- Später.\n", encoding="utf-8")
        self.verteilen()
        self.assertIn("- Später.", ziel.read_text(encoding="utf-8"), "ohne Schalter muss es auch dort ankommen")
        self.verteilen("--ziel", str(ziel))
        self.assertEqual((self.o / "REGELN.ziele.txt").read_text(encoding="utf-8").count("AGENTS.md"), 1)

    def test_ziel_muss_eine_datei_sein(self):
        r = self.verteilen("--ziel", str(self.t))
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.o / "REGELN.ziele.txt").exists())


class UpdateQuelle(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("einrichten_quelle", HIER / "einrichten.py")
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def finde(self, **remotes):
        def git(*a):
            aus = " ".join(remotes) if a == ("remote",) else remotes.get(a[-1], "")
            return subprocess.CompletedProcess(a, 0, aus + "\n", "")
        return self.m.quelle_finden(git)

    def test_offizielle_adresse_geht_vor(self):
        self.assertEqual(self.finde(origin="https://github.com/jemand/eigene-kopie.git",
                                    oben="ssh://github.com/hadi-yousef/zentrale-starter.git"), "oben")

    def test_anderer_name_mit_offizieller_adresse(self):
        self.assertEqual(self.finde(meine="https://github.com/hadi-yousef/zentrale-starter"), "meine")

    def test_sonst_origin_oder_die_einzige(self):
        self.assertEqual(self.finde(origin="https://example.invalid/a.git", b="https://example.invalid/b.git"), "origin")
        self.assertEqual(self.finde(b="https://example.invalid/b.git"), "b")

    def test_aehnlicher_name_zaehlt_nicht_als_offiziell(self):
        self.assertEqual(self.finde(origin="https://example.invalid/a.git",
                                    b="https://github.com/hadi-yousef/zentrale-starter-kopie.git"), "origin")

    def test_mehrdeutig_bleibt_leer(self):
        self.assertEqual(self.finde(a="https://example.invalid/a.git", b="https://example.invalid/b.git"), "")
        self.assertEqual(self.finde(), "")

    def test_update_mit_anderem_quellnamen_holt_die_neue_fassung(self):
        if not shutil.which("git"):
            self.skipTest("git fehlt")
        t, env = neuer_ordner("quelle"), _git_umgebung()
        oben, klon = t / "oben", t / "klon"
        _git(env, "init", "-q", str(oben))
        _git(env, "symbolic-ref", "HEAD", "refs/heads/main", cwd=oben)
        (oben / "zentrale").mkdir()
        (oben / "zentrale" / "hub.py").write_text('FASSUNG = "alt"\n', encoding="utf-8")
        _git(env, "add", ".", cwd=oben)
        _git(env, "commit", "-qm", "alt", cwd=oben)
        _git(env, "clone", "-q", "-o", "meine-quelle", str(oben), str(klon))
        (oben / "zentrale" / "hub.py").write_text('FASSUNG = "neu"\n', encoding="utf-8")
        _git(env, "commit", "-qam", "neu", cwd=oben)
        echt = subprocess.run

        def run(args, **kw):
            if args[0] != "git":
                return subprocess.CompletedProcess(args, 0, "", "")
            kw["env"] = env
            return echt(args, **kw)
        self.m.HIER = klon
        with mock.patch.object(self.m.subprocess, "run", side_effect=run), mock.patch.object(self.m, "autostart", return_value=[]), \
                mock.patch.object(self.m, "daten_zaehlen", return_value=(t, {})), contextlib.redirect_stdout(io.StringIO()):
            self.m.update()
        self.assertIn('"neu"', (klon / "zentrale" / "hub.py").read_text(encoding="utf-8"))


class ProjektnameInDerAdresse(unittest.TestCase):
    def test_name_mit_leerzeichen_und_umlaut(self):
        import app
        import pos
        import urllib.parse
        name = "Büro Umbau Test"
        pos.projekt_neu("claude", {"name": name})
        kodiert = urllib.parse.quote(name)
        r = app.Handler._post(None, "claude", f"/api/pos/projekte/{kodiert}", ["projekte", kodiert], {"naechster_schritt": "Weiter"})
        self.assertEqual((r["name"], r["naechster_schritt"]), (name, "Weiter"))

    def test_gegenfall_unbekannter_name_bleibt_ein_fehler(self):
        import app
        with self.assertRaises(Exception):
            app.Handler._post(None, "claude", "/api/pos/projekte/Gibt%20es%20nicht", ["projekte", "Gibt%20es%20nicht"], {"naechster_schritt": "x"})


class ClientTexte(unittest.TestCase):
    def setUp(self):
        import zentrale_client
        self.c = zentrale_client
        self.z = mock.Mock()
        self.z.post.return_value = {"nr": 3}

    def befehl(self, **kw):
        import argparse
        with contextlib.redirect_stdout(io.StringIO()) as aus:
            self.c.ausfuehren(self.z, argparse.Namespace(**kw))
        return aus.getvalue()

    def test_text_aus_datei_kommt_unversehrt_an(self):
        d = neuer_ordner("text") / "t.md"
        d.write_text("Text mit `backticks` und $(befehl)\n", encoding="utf-8")
        self.befehl(befehl="wunsch-notiz", nr="3", text=None, text_datei=str(d))
        self.assertEqual(self.z.post.call_args[0], ("/api/wuensche/3/notizen", {"text": "Text mit `backticks` und $(befehl)"}))
        self.befehl(befehl="bericht-antwort", nr="3", text=None, text_datei=str(d))
        self.assertEqual(self.z.post.call_args[0], ("/api/berichte/3/nachricht", {"text": "Text mit `backticks` und $(befehl)"}))

    def test_gegenfall_text_direkt_geht_weiter(self):
        self.befehl(befehl="wunsch-notiz", nr="3", text="Kurz", text_datei=None)
        self.assertEqual(self.z.post.call_args[0][1], {"text": "Kurz"})

    def test_ohne_text_kein_leerer_eintrag(self):
        with self.assertRaises(self.c.Fehler):
            self.befehl(befehl="wunsch-notiz", nr="3", text=None, text_datei=None)
        self.z.post.assert_not_called()

    def test_schalter_steht_in_der_hilfe(self):
        for b in ("wunsch-notiz", "bericht-antwort"):
            r = subprocess.run([sys.executable, "-B", str(HIER / "zentrale_client.py"), b, "--help"], capture_output=True,
                               text=True, encoding="utf-8", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            self.assertIn("--text-datei", r.stdout, b)

    def test_bericht_zeigt_projekt_und_wunsch(self):
        self.z.get.return_value = {"nr": 3, "titel": "T", "von": "claude", "zeit": 0, "kurz": "", "fragen": [], "verlauf": [],
                                   "projekt": "Website", "wunsch": 7}
        aus = self.befehl(befehl="bericht", nr="3")
        self.assertIn("Projekt: Website", aus)
        self.assertIn("Wunsch Nr. 7", aus)

    def test_laeufe_zeigen_die_kennung(self):
        l = {"agent": "claude", "lauf": "chat-abc", "titel": "Titel", "start": 0, "ende": 0, "status": "fertig"}
        self.z.get.return_value = {"aktiv": [l], "fertig": [l]}
        self.assertEqual(self.befehl(befehl="laeufe", anzahl=5).count("[Lauf chat-abc]"), 2)


class HookWunsch(unittest.TestCase):
    def test_zitierte_nummer_verschiebt_den_lauf_nicht(self):
        import laeufe
        laeufe.melden("claude", {"aktion": "start", "lauf": "chat-a", "titel": "Erste", "wunsch": "5", "quelle": "hook"})
        x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-a", "titel": "Zweite", "wunsch": "9", "quelle": "hook"})
        self.assertEqual(x["wunsch"], 5)

    def test_gesetzte_nummer_bleibt_gegen_den_hook(self):
        import laeufe
        laeufe.melden("claude", {"aktion": "start", "lauf": "chat-b", "titel": "Erste", "quelle": "hook"})
        laeufe.melden("claude", {"aktion": "stand", "lauf": "chat-b", "wunsch": "6"})
        x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-b", "titel": "Zweite", "wunsch": "9", "quelle": "hook"})
        self.assertEqual(x["wunsch"], 6)

    def test_gegenfall_erste_nummer_gilt_und_agent_darf_wechseln(self):
        import laeufe
        laeufe.melden("claude", {"aktion": "start", "lauf": "chat-c", "titel": "Ohne", "quelle": "hook"})
        x = laeufe.melden("claude", {"aktion": "start", "lauf": "chat-c", "titel": "Mit", "wunsch": "4", "quelle": "hook"})
        self.assertEqual(x["wunsch"], 4)
        x = laeufe.melden("claude", {"aktion": "stand", "lauf": "chat-c", "wunsch": "8"})
        self.assertEqual(x["wunsch"], 8)


def tearDownModule():
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
