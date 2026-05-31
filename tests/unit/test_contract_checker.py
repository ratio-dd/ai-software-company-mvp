import unittest

from app.server import ArtifactHarness, ContractChecker, OpenAICompatibleProvider


class ContractCheckerTest(unittest.TestCase):
    def test_extracts_frontend_and_backend_request_keys(self):
        harness = ArtifactHarness()
        frontend_usages = harness.extract_frontend_usages({
            "frontend/src/app.js": '''
const API_SCHEMAS = {
  "/api/schedules/check-conflicts": ["courseId", "teacherId"]
};
fetch(apiUrl("/api/schedules/check-conflicts"), {
  method: "POST",
  body: JSON.stringify(payload)
});
'''
        })
        backend_routes = harness.extract_backend_routes({
            "backend/server.py": '''
ROUTES = [
    ("POST", "/api/schedules/check-conflicts"),
]
ROUTE_SCHEMAS = {
    ("POST", "/api/schedules/check-conflicts"): ["courseId", "teacherId"],
}
'''
        })

        self.assertEqual(frontend_usages[0]["request_keys"], ["courseId", "teacherId"])
        self.assertEqual(backend_routes[0]["request_keys"], ["courseId", "teacherId"])
        self.assertEqual(ContractChecker().compare(frontend_usages, backend_routes), [])

    def test_detects_request_key_mismatch(self):
        mismatches = ContractChecker().compare(
            [{"method": "POST", "path": "/api/schedules/check-conflicts", "request_keys": ["courseId"]}],
            [{"method": "POST", "path": "/api/schedules/check-conflicts", "request_keys": ["courseId", "teacherId"]}],
        )

        self.assertEqual(mismatches[0]["kind"], "request_keys_mismatch")
        self.assertEqual(mismatches[0]["frontend_keys"], ["courseId"])
        self.assertEqual(mismatches[0]["backend_keys"], ["courseId", "teacherId"])

    def test_extracts_backtick_fetch_and_schema_literals(self):
        harness = ArtifactHarness()
        frontend_usages = harness.extract_frontend_usages({
            "frontend/src/app.js": '''
const API_SCHEMAS = {
  `/api/schedule/check`: [`courseId`, `teacherId`]
};
fetch(apiUrl(`/api/schedule/check`), {
  method: `post`,
  body: JSON.stringify(payload)
});
'''
        })

        self.assertEqual(frontend_usages[0]["method"], "POST")
        self.assertEqual(frontend_usages[0]["path"], "/api/schedule/check")
        self.assertEqual(frontend_usages[0]["request_keys"], ["courseId", "teacherId"])

    def test_llm_parse_files_preserves_nested_json_content(self):
        provider = OpenAICompatibleProvider()
        files = provider.parse_files('{"files":{"api-contract.json":{"endpoints":[{"method":"GET","path":"/api/courses"}]}}}')

        self.assertEqual(files["api-contract.json"], '{\n  "endpoints": [\n    {\n      "method": "GET",\n      "path": "/api/courses"\n    }\n  ]\n}')


if __name__ == "__main__":
    unittest.main()
