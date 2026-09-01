import json
import tempfile
import unittest
from pathlib import Path

from automation.moderation_agent.mail_ingest import ingest_eml, parse_eml
from automation.moderation_agent.queue import ModerationQueue


RAW_EMAIL = b"""From: Alice <alice@example.com>
To: submit@example.com
Subject: [Submission] Test article
Message-ID: <submission-1@example.com>
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary=boundary

--boundary
Content-Type: text/plain; charset=utf-8

This is a campus experience article.
--boundary
Content-Type: text/plain; name=notes.txt
Content-Disposition: attachment; filename=notes.txt

attachment content
--boundary--
"""


class MailQueueTests(unittest.TestCase):
    def test_parse_eml_extracts_body_and_attachment_metadata(self):
        submission = parse_eml(RAW_EMAIL)
        self.assertEqual(submission.sender, "alice@example.com")
        self.assertIn("campus experience", submission.body)
        self.assertEqual(len(submission.attachments), 1)
        self.assertEqual(submission.attachments[0]["filename"], "notes.txt")

    def test_message_id_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "queue.sqlite3"
            _, first_job_id, first_created = ingest_eml(RAW_EMAIL, database)
            _, second_job_id, second_created = ingest_eml(RAW_EMAIL, database)
            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertEqual(first_job_id, second_job_id)
            jobs = ModerationQueue(database).list_jobs()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["status"], "RECEIVED")

    def test_content_hash_is_idempotent_across_message_ids(self):
        second_message = RAW_EMAIL.replace(
            b"<submission-1@example.com>", b"<submission-2@example.com>"
        )
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "queue.sqlite3"
            _, first_job_id, first_created = ingest_eml(RAW_EMAIL, database)
            _, second_job_id, second_created = ingest_eml(second_message, database)
            self.assertTrue(first_created)
            self.assertFalse(second_created)
            self.assertEqual(first_job_id, second_job_id)


if __name__ == "__main__":
    unittest.main()
