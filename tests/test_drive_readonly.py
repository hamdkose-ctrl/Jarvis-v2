import unittest
from modules import drive_readonly as drive


class FakeRequest:
    def __init__(self, payload):
        self.payload = payload
    def execute(self):
        return self.payload


class FakeFiles:
    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return FakeRequest({"files": [{"id": "a", "name": "Plan", "mimeType": "text/plain"}]})


class FakeDrive:
    def __init__(self):
        self.files_api = FakeFiles()
    def files(self):
        return self.files_api


class FakeDocs:
    def documents(self):
        return self
    def get(self, **kwargs):
        return FakeRequest({"title": "Not", "body": {"content": [
            {"paragraph": {"elements": [{"textRun": {"content": "Merhaba\n"}}]}}
        ]}})


class FakeSheets:
    def spreadsheets(self):
        return self
    def values(self):
        return self
    def get(self, **kwargs):
        return FakeRequest({"range": "Sayfa1!A1:B2", "values": [["ad", "değer"], ["A", "1"]]})


class DriveReadonlyTests(unittest.TestCase):
    def test_file_list_is_bounded_and_metadata_only(self):
        rows = drive.list_files(FakeDrive(), query="name contains 'plan'", limit=5)
        self.assertEqual(rows, [{"id": "a", "name": "Plan", "mime_type": "text/plain"}])

    def test_docs_extracts_bounded_visible_text(self):
        result = drive.read_document(FakeDocs(), "doc-1")
        self.assertEqual(result["title"], "Not")
        self.assertEqual(result["text"], "Merhaba")

    def test_sheets_reads_values_without_mutation(self):
        result = drive.read_sheet(FakeSheets(), "sheet-1", "Sayfa1!A1:B2")
        self.assertEqual(result["values"][1][0], "A")

    def test_invalid_ids_ranges_and_mutating_operations_are_rejected(self):
        with self.assertRaises(drive.DriveReadonlyError):
            drive.validate_file_id("../secret")
        with self.assertRaises(drive.DriveReadonlyError):
            drive.read_sheet(FakeSheets(), "sheet-1", "A1;delete")
        with self.assertRaises(drive.DriveReadonlyError):
            drive.assert_readonly_operation("update")


if __name__ == "__main__":
    unittest.main()
