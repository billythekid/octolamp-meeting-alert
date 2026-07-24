"""Tests for the .env parser and typed env accessors."""
import os
import tempfile
import unittest

from tests._helpers import ROOT  # noqa: F401  # sys.path setup
import octolamp_meeting_alert as m


class LoadDotenvTests(unittest.TestCase):
    def _write(self, contents: str) -> str:
        f = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False)
        f.write(contents)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def _cleanup_env(self, *keys: str) -> None:
        for k in keys:
            self.addCleanup(lambda k=k: os.environ.pop(k, None))

    def test_basic_key_value(self) -> None:
        path = self._write("TEST_BASIC=hello\n")
        self._cleanup_env("TEST_BASIC")
        os.environ.pop("TEST_BASIC", None)
        m._load_dotenv(path)
        self.assertEqual(os.environ["TEST_BASIC"], "hello")

    def test_ignores_comments_and_blank(self) -> None:
        path = self._write("# comment line\n\nTEST_KEEP=yes\n# TEST_SKIP=no\n")
        self._cleanup_env("TEST_KEEP", "TEST_SKIP")
        os.environ.pop("TEST_KEEP", None)
        os.environ.pop("TEST_SKIP", None)
        m._load_dotenv(path)
        self.assertEqual(os.environ["TEST_KEEP"], "yes")
        self.assertNotIn("TEST_SKIP", os.environ)

    def test_strips_surrounding_quotes(self) -> None:
        path = self._write('TEST_QUOTED="value with spaces"\nTEST_SINGLE=\'other\'\n')
        self._cleanup_env("TEST_QUOTED", "TEST_SINGLE")
        os.environ.pop("TEST_QUOTED", None)
        os.environ.pop("TEST_SINGLE", None)
        m._load_dotenv(path)
        self.assertEqual(os.environ["TEST_QUOTED"], "value with spaces")
        self.assertEqual(os.environ["TEST_SINGLE"], "other")

    def test_existing_env_wins(self) -> None:
        path = self._write("TEST_OVERRIDE=from_file\n")
        self._cleanup_env("TEST_OVERRIDE")
        os.environ["TEST_OVERRIDE"] = "from_shell"
        m._load_dotenv(path)
        self.assertEqual(os.environ["TEST_OVERRIDE"], "from_shell")

    def test_missing_file_is_silent(self) -> None:
        m._load_dotenv("/nonexistent/path/.env")  # should not raise

    def test_ignores_lines_without_equals(self) -> None:
        path = self._write("not a kv line\nGOOD=fine\n")
        self._cleanup_env("GOOD")
        os.environ.pop("GOOD", None)
        m._load_dotenv(path)
        self.assertEqual(os.environ["GOOD"], "fine")


class EnvAccessorTests(unittest.TestCase):
    def tearDown(self) -> None:
        for k in ("T_INT", "T_COL", "T_TUP"):
            os.environ.pop(k, None)

    def test_env_int_default_when_missing(self) -> None:
        os.environ.pop("T_INT", None)
        self.assertEqual(m._env_int("T_INT", 42), 42)

    def test_env_int_default_when_blank(self) -> None:
        os.environ["T_INT"] = ""
        self.assertEqual(m._env_int("T_INT", 7), 7)

    def test_env_int_parses(self) -> None:
        os.environ["T_INT"] = "99"
        self.assertEqual(m._env_int("T_INT", 0), 99)

    def test_env_colour_default_when_missing(self) -> None:
        self.assertEqual(m._env_colour("T_COL", [1, 2, 3]), [1, 2, 3])

    def test_env_colour_parses_rgb(self) -> None:
        os.environ["T_COL"] = "10, 20 , 30"
        self.assertEqual(m._env_colour("T_COL", [0, 0, 0]), [10, 20, 30])

    def test_env_colour_wrong_arity_falls_back(self) -> None:
        os.environ["T_COL"] = "10,20"
        self.assertEqual(m._env_colour("T_COL", [1, 2, 3]), [1, 2, 3])

    def test_env_tuple_default_when_missing(self) -> None:
        self.assertEqual(m._env_tuple("T_TUP", ("a",)), ("a",))

    def test_env_tuple_lowercases_and_trims(self) -> None:
        os.environ["T_TUP"] = "  Alpha , BETA "
        self.assertEqual(m._env_tuple("T_TUP", ()), ("alpha", "beta"))

    def test_env_tuple_strips_per_item_quotes(self) -> None:
        os.environ["T_TUP"] = 'plain,"With Spaces",\'Single Quoted\''
        self.assertEqual(
            m._env_tuple("T_TUP", ()),
            ("plain", "with spaces", "single quoted"),
        )

    def test_env_tuple_skips_empty_items(self) -> None:
        os.environ["T_TUP"] = "a,,b,"
        self.assertEqual(m._env_tuple("T_TUP", ()), ("a", "b"))


if __name__ == "__main__":
    unittest.main()
