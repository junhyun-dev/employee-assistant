from __future__ import annotations

import http.client
import json
import threading
import unittest

from employee_assistant.server import HOST, make_server


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = make_server(0)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def request(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        connection = http.client.HTTPConnection(HOST, self.port, timeout=3)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        content = response.read()
        result = (response.status, dict(response.getheaders()), content)
        connection.close()
        return result

    def payload(self, **overrides) -> dict:
        value = {
            "client_request_id": 7,
            "inquiry_type": "monitor_and_laptop_replacement",
            "user_text": "모니터와 노트북 문의",
            "employee_facts": {"tenure": "4년", "symptom": "지난주부터 화상회의 중", "purchase_status": "not_purchased"},
            "exclude_laptop_evidence": False,
        }
        value.update(overrides)
        return value

    def post(self, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode()
        return self.request("POST", "/api/workspace", body, {"Content-Type": "application/json", "Content-Length": str(len(body))})

    def test_static_boundary_and_security_headers(self) -> None:
        status, headers, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("직원 업무 도우미".encode(), body)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("default-src 'self'", headers["Content-Security-Policy"])

        status, _, _ = self.request("GET", "/%2e%2e/README.md")
        self.assertEqual(status, 403)

    def test_supported_request_and_request_scoped_evidence(self) -> None:
        status, _, raw = self.post(self.payload())
        self.assertEqual(status, 200)
        response = json.loads(raw)
        self.assertEqual(response["client_request_id"], 7)
        self.assertEqual(response["ui_state"], "normal")
        material = set(response["result"]["material"]["evidence_ids"])
        for branch in response["result"]["branches"].values():
            self.assertLessEqual(set(branch["draft_proposal"]["evidence_ids"]), material)

        status, _, raw = self.post(self.payload(exclude_laptop_evidence=True))
        response = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(response["ui_state"], "missing")
        self.assertEqual(response["result"]["branches"]["monitor"]["status"], "ready_rule_composed")
        self.assertIsNone(response["result"]["branches"]["laptop"]["draft_proposal"]["text"])

    def test_invalid_and_unsupported_requests(self) -> None:
        status, _, _ = self.post(self.payload(inquiry_type="arbitrary_free_text"))
        self.assertEqual(status, 422)
        status, _, _ = self.post(self.payload(employee_facts={"purchase_status": "approved"}))
        self.assertEqual(status, 400)
        for invalid_purchase_status in ([], {}):
            with self.subTest(purchase_status=invalid_purchase_status):
                status, _, raw = self.post(
                    self.payload(employee_facts={"purchase_status": invalid_purchase_status})
                )
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(raw)["error"]["code"], "invalid_value")
        status, _, _ = self.request("POST", "/api/workspace", b"{}", {"Content-Type": "text/plain", "Content-Length": "2"})
        self.assertEqual(status, 415)
        status, _, _ = self.request(
            "POST",
            "/api/workspace",
            b"{}",
            {"Content-Type": "application/json", "Content-Length": str(33 * 1024)},
        )
        self.assertEqual(status, 413)

    def test_html_like_input_stays_json_text(self) -> None:
        marker = '\"><img id="injected" src=x onerror="window.hacked=1">'
        payload = self.payload(employee_facts={"tenure": marker, "symptom": "느림", "purchase_status": "unknown"})
        status, _, raw = self.post(payload)
        self.assertEqual(status, 200)
        response = json.loads(raw)
        self.assertEqual(response["result"]["request"]["employee_facts"]["tenure"], marker)
        self.assertIn(marker, response["result"]["branches"]["laptop"]["draft_proposal"]["text"])


if __name__ == "__main__":
    unittest.main()
