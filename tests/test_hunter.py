#!/usr/bin/env python3
"""Unit tests for username_hunter. All network access is mocked."""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import username_hunter as uh


class FakeResponse:
    def __init__(self, status_code=200, text="", url="https://example.com/u/bob", json_data=None):
        self.status_code = status_code
        self.text = text
        self.url = url
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def site(**over):
    base = {"name": "TestSite", "category": "dev", "url": "https://example.com/u/{}",
            "type": "code"}
    base.update(over)
    return base


class CheckTests(unittest.TestCase):
    def setUp(self):
        # Fresh thread-local session per test so mocks don't leak.
        if hasattr(uh._tls, "session"):
            del uh._tls.session

    def _run(self, site_cfg, response=None, side_effect=None):
        sess = MagicMock()
        if side_effect is not None:
            sess.get.side_effect = side_effect
        else:
            sess.get.return_value = response
        with patch.object(uh, "_thread_session", return_value=sess):
            return uh.check(site_cfg, "bob", timeout=5)

    def test_code_type_200_is_found(self):
        res = self._run(site(), FakeResponse(200))
        self.assertTrue(res["found"])
        self.assertEqual(res["status"], 200)

    def test_code_type_404_is_not_found(self):
        res = self._run(site(), FakeResponse(404))
        self.assertFalse(res["found"])

    def test_api_type_with_json_key(self):
        cfg = site(type="api", api="https://example.com/api/{}",
                   json_key="data.id")
        res = self._run(cfg, FakeResponse(200, json_data={"data": {"id": 7}}))
        self.assertTrue(res["found"])

    def test_api_type_empty_json_key_value_is_not_found(self):
        cfg = site(type="api", api="https://example.com/api/{}",
                   json_key="data.id")
        res = self._run(cfg, FakeResponse(200, json_data={"data": {"id": 0}}))
        self.assertFalse(res["found"])

    def test_body_type_error_strings(self):
        cfg = site(type="body", error_strings=["user not found"])
        res = self._run(cfg, FakeResponse(200, text="<html>User not found</html>"))
        self.assertFalse(res["found"])

    def test_body_type_success_strings_required(self):
        cfg = site(type="body", success_strings=['"uniqueId":"{}"'])
        ok = self._run(cfg, FakeResponse(200, text='x "uniqueId":"bob" y'))
        self.assertTrue(ok["found"])
        bad = self._run(cfg, FakeResponse(200, text="some generic page"))
        self.assertFalse(bad["found"])

    def test_soft404_title_flips_found_to_miss(self):
        cfg = site()
        res = self._run(
            cfg, FakeResponse(200, text="<html><title>User not found</title></html>"))
        self.assertFalse(res["found"])
        self.assertTrue(res.get("soft404"))

    def test_soft404_does_not_fire_on_real_profile_title(self):
        cfg = site()
        res = self._run(
            cfg, FakeResponse(200, text="<html><title>bob (@bob) / Example</title></html>"))
        self.assertTrue(res["found"])
        self.assertNotIn("soft404", res)

    def test_final_url_contains_guard(self):
        cfg = site(final_url_contains="example.com/u/{}")
        redir = self._run(cfg, FakeResponse(
            200, url="https://example.com/login", text="<title>bob</title>"))
        self.assertFalse(redir["found"])
        stay = self._run(cfg, FakeResponse(
            200, url="https://example.com/u/bob", text="<title>bob</title>"))
        self.assertTrue(stay["found"])

    def test_retry_on_connection_error_then_success(self):
        import requests
        cfg = site()
        sess = MagicMock()
        sess.get.side_effect = [requests.ConnectionError("down"),
                                FakeResponse(200, text="<title>bob</title>")]
        with patch.object(uh, "_thread_session", return_value=sess), \
                patch("time.sleep", return_value=None):
            res = uh.check(cfg, "bob", timeout=5, retries=2, retry_delay=0.01)
        self.assertTrue(res["found"])
        self.assertEqual(sess.get.call_count, 2)

    def test_no_retry_left_records_error(self):
        import requests
        cfg = site()
        sess = MagicMock()
        sess.get.side_effect = requests.Timeout("slow")
        with patch.object(uh, "_thread_session", return_value=sess), \
                patch("time.sleep", return_value=None):
            res = uh.check(cfg, "bob", timeout=5, retries=1, retry_delay=0.01)
        self.assertFalse(res["found"])
        self.assertIn("error", res)
        self.assertEqual(sess.get.call_count, 2)

    def test_network_error_sets_found_false(self):
        import requests
        cfg = site()
        sess = MagicMock()
        sess.get.side_effect = requests.ConnectionError("nope")
        with patch.object(uh, "_thread_session", return_value=sess), \
                patch("time.sleep", return_value=None):
            res = uh.check(cfg, "bob", timeout=5, retries=0)
        self.assertFalse(res["found"])
        self.assertIn("error", res)


class HelperTests(unittest.TestCase):
    def test_page_title_extraction(self):
        self.assertEqual(uh._page_title("<title>  Hello World </title>"), "hello world")
        self.assertEqual(uh._page_title("no title here"), "")

    def test_resolve_json_key_nested(self):
        self.assertEqual(uh._resolve_json_key({"a": {"b": 5}}, "a.b"), 5)
        self.assertEqual(uh._resolve_json_key({"a": [1, 2]}, "a.1"), 2)
        self.assertIsNone(uh._resolve_json_key({"a": 1}, "a.b.c"))
        self.assertIsNone(uh._resolve_json_key({}, "x"))

    def test_sites_json_loads_and_counts(self):
        sites = uh.load_sites()
        self.assertGreaterEqual(len(sites), 140)
        for s in sites:
            self.assertIn("name", s)
            self.assertIn("url", s)
            self.assertIn("type", s)
            self.assertIn("{}", s["url"], f"{s['name']} url has no placeholder")

    def test_thread_sessions_are_thread_local(self):
        import threading
        seen = []

        def grab():
            seen.append(uh._thread_session())

        threads = [threading.Thread(target=grab) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len({id(s) for s in seen}), 4)


class ProfileTests(unittest.TestCase):
    def test_save_and_load_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_path = os.path.join(tmp, "profiles.json")
            with patch.object(uh, "PROFILES_DIR", tmp), \
                    patch.object(uh, "PROFILES_PATH", fake_path):
                uh.save_profile("quick", {"threads": 10, "timeout": 5})
                profiles = uh.load_profiles()
                self.assertEqual(profiles["quick"]["threads"], 10)
                uh.save_profile("deep", {"threads": 40})
                self.assertEqual(len(uh.load_profiles()), 2)

    def test_load_profiles_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(uh, "PROFILES_PATH",
                              os.path.join(tmp, "nope.json")):
                self.assertEqual(uh.load_profiles(), {})


class HtmlReportTests(unittest.TestCase):
    def test_html_report_escapes_and_lists_hits(self):
        found = [
            {"name": "GitHub", "category": "dev",
             "url": "https://github.com/bob\"><script>",
             "status": 200, "found": True},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.html")
            uh.write_html_report(found, "bob", path, elapsed=1.5, total=144)
            doc = open(path, encoding="utf-8").read()
        self.assertIn("&lt;script&gt;", doc)  # escaped, not raw
        self.assertNotIn('"><script>', doc)  # raw payload must not appear
        self.assertIn("GitHub", doc)
        self.assertIn("1 of 144", doc)

    def test_html_report_with_no_hits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "r.html")
            uh.write_html_report([], "nobody", path, elapsed=0.5, total=144)
            doc = open(path, encoding="utf-8").read()
        self.assertIn("No matches found", doc)


if __name__ == "__main__":
    unittest.main()
