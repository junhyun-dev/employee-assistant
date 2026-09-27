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
            "inquiry_scope": "both",
            "laptop_inquiry_goal": "replacement_process",
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
        self.assertEqual(response["result"]["request"]["inquiry_scope"], "both")
        material = set(response["result"]["material"]["evidence_ids"])
        for branch in response["result"]["branches"].values():
            self.assertLessEqual(set(branch["draft_proposal"]["evidence_ids"]), material)

        before = self.payload(laptop_inquiry_goal="before_replacement")
        status, _, raw = self.post(before)
        self.assertEqual(status, 200)
        before_response = json.loads(raw)["result"]
        self.assertEqual(
            before_response["request"]["laptop_inquiry_goal"],
            "before_replacement",
        )
        self.assertIn(
            "교체 여부를 정하기 전에",
            before_response["branches"]["laptop"]["draft_proposal"]["text"],
        )

        legacy = self.payload()
        del legacy["laptop_inquiry_goal"]
        del legacy["inquiry_scope"]
        status, _, raw = self.post(legacy)
        self.assertEqual(status, 200)
        self.assertEqual(
            json.loads(raw)["result"]["request"]["laptop_inquiry_goal"],
            "replacement_process",
        )
        self.assertEqual(
            json.loads(raw)["result"]["request"]["inquiry_scope"],
            "both",
        )

        status, _, raw = self.post(self.payload(exclude_laptop_evidence=True))
        response = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(response["ui_state"], "missing")
        self.assertEqual(response["result"]["branches"]["monitor"]["status"], "ready_rule_composed")
        self.assertIsNone(response["result"]["branches"]["laptop"]["draft_proposal"]["text"])

        status, _, raw = self.post(
            self.payload(inquiry_scope="monitor", exclude_laptop_evidence=True)
        )
        monitor_only = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(monitor_only["ui_state"], "normal")
        self.assertEqual(
            monitor_only["result"]["material"]["evidence_ids"],
            ["equipment", "approved-wfh-computer"],
        )
        self.assertEqual(
            monitor_only["result"]["branches"]["laptop"]["status"],
            "not_selected",
        )

        status, _, raw = self.post(
            self.payload(inquiry_scope="laptop", exclude_laptop_evidence=True)
        )
        laptop_only = json.loads(raw)
        self.assertEqual(status, 200)
        self.assertEqual(laptop_only["ui_state"], "missing")
        self.assertEqual(
            laptop_only["result"]["branches"]["monitor"]["status"],
            "not_selected",
        )

    def test_invalid_and_unsupported_requests(self) -> None:
        status, _, _ = self.post(self.payload(inquiry_type="arbitrary_free_text"))
        self.assertEqual(status, 422)
        status, _, _ = self.post(self.payload(employee_facts={"purchase_status": "approved"}))
        self.assertEqual(status, 400)
        for invalid_goal in (None, [], {}, True, 1, "diagnose"):
            with self.subTest(laptop_inquiry_goal=invalid_goal):
                status, _, raw = self.post(
                    self.payload(laptop_inquiry_goal=invalid_goal)
                )
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(raw)["error"]["code"], "invalid_value")
        for invalid_scope in (None, [], {}, True, 1, "automatic"):
            with self.subTest(inquiry_scope=invalid_scope):
                status, _, raw = self.post(
                    self.payload(inquiry_scope=invalid_scope)
                )
                self.assertEqual(status, 400)
                self.assertEqual(json.loads(raw)["error"]["code"], "invalid_value")
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

    def test_blank_fact_text_is_preserved_but_omitted_from_rule_draft(self) -> None:
        facts = {
            "tenure": "  ",
            "symptom": "\t ",
            "purchase_status": " \t",
        }
        status, _, raw = self.post(
            self.payload(
                laptop_inquiry_goal="before_replacement",
                employee_facts=facts,
            )
        )
        self.assertEqual(status, 200)
        result = json.loads(raw)["result"]
        draft = result["branches"]["laptop"]["draft_proposal"]["text"]

        self.assertEqual(result["request"]["employee_facts"], facts)
        self.assertTrue(draft.startswith("회사 노트북이 느려져 문의드립니다."))
        self.assertNotIn("[", draft)
        self.assertNotIn("구매 상태", draft)

    def test_monitor_detail_is_optional_and_preserved_as_raw_employee_input(self) -> None:
        generic_drafts = []
        for label, detail in (("absent", None), ("empty", ""), ("whitespace", " \t ")):
            with self.subTest(label=label):
                facts = {
                    "tenure": "2년 10개월",
                    "symptom": "오늘 화상회의 중",
                    "purchase_status": "purchased",
                }
                if detail is not None:
                    facts["monitor_employee_detail"] = detail
                status, _, raw = self.post(self.payload(employee_facts=facts))
                self.assertEqual(status, 200)
                result = json.loads(raw)["result"]
                draft = result["branches"]["monitor"]["draft_proposal"]["text"]

                self.assertEqual(result["request"]["employee_facts"], facts)
                self.assertTrue(draft.startswith("재택근무용 모니터 구입을 검토 중입니다."))
                self.assertNotIn("[신규/기존 직원", draft)
                self.assertNotIn("2년 10개월", draft)
                self.assertNotIn("이미 구매", draft)
                generic_drafts.append(draft)

        self.assertEqual(len(set(generic_drafts)), 1)

        facts = {
            "monitor_employee_detail": "  기존 직원, 입사일 2025-06-01  ",
        }
        status, _, raw = self.post(self.payload(employee_facts=facts))
        self.assertEqual(status, 200)
        result = json.loads(raw)["result"]
        self.assertEqual(result["request"]["employee_facts"], facts)
        self.assertTrue(
            result["branches"]["monitor"]["draft_proposal"]["text"].startswith(
                "직원 정보: 기존 직원, 입사일 2025-06-01\n"
            )
        )


if __name__ == "__main__":
    unittest.main()
