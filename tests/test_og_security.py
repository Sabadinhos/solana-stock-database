import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("sdb_og_security", Path(__file__).parents[1] / "og.py")
og = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(og)


class Response:
    def __init__(self, data=b"x", ctype="image/png"):
        self.data = data

        class Headers(dict):
            def get_content_type(self):
                return self.get("Content-Type", "")

        self.headers = Headers({"Content-Length": str(len(data)), "Content-Type": ctype})

    def read(self, n=-1):
        return self.data[:n]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class OgSecurityTests(unittest.TestCase):
    def test_logo_rejects_http_and_private_hosts(self):
        self.assertIsNone(og._fetch_logo("http://127.0.0.1/a.png"))
        with patch.object(og.socket, "getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
            self.assertIsNone(og._fetch_logo("https://example.test/a.png"))

    def test_logo_rejects_non_image_and_oversized(self):
        with patch.object(og.urllib.request, "urlopen", return_value=Response(b"not-image", "text/html")):
            with patch.object(og, "_public_host", return_value=True):
                self.assertIsNone(og._fetch_logo("https://example.test/a"))
        with patch.object(og.urllib.request, "urlopen", return_value=Response(b"x" * (og.MAX_LOGO_BYTES + 1), "image/png")):
            with patch.object(og, "_public_host", return_value=True):
                self.assertIsNone(og._fetch_logo("https://example.test/a"))

    def test_logo_redirects_are_revalidated(self):
        class Redirect(Response):
            status = 302
            def __init__(self, location):
                super().__init__(b"", "text/html")
                self.headers["Location"] = location
                self._url = "https://example.test/a"
            def geturl(self):
                return self._url
        with patch.object(og.urllib.request, "urlopen", return_value=Redirect("https://127.0.0.1/private")):
            with patch.object(og, "_public_host", side_effect=lambda host: host != "127.0.0.1"):
                self.assertIsNone(og._fetch_logo("https://example.test/a"))

    def test_logo_redirect_loop_is_bounded(self):
        class Redirect(Response):
            status = 302
            def __init__(self):
                super().__init__(b"", "text/html")
                self.headers["Location"] = "https://example.test/a"
            def geturl(self):
                return "https://example.test/a"
        with patch.object(og.urllib.request, "urlopen", return_value=Redirect()) as fetch:
            with patch.object(og, "_public_host", return_value=True):
                self.assertIsNone(og._fetch_logo("https://example.test/a"))
                self.assertEqual(fetch.call_count, og.MAX_LOGO_REDIRECTS + 1)


if __name__ == "__main__":
    unittest.main()
