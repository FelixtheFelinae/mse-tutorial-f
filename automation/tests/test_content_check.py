import unittest

from automation.moderation_agent.content_check import CheckerConfig, check_text
from automation.moderation_agent.models import Action


CONFIG = CheckerConfig(
    site_contact_emails={"submit@example.com"},
    trusted_contact_paths={"docs/contribute.md"},
    template_prefixes=["docs/page-templates/"],
    metadata_exempt_paths={"docs/contribute.md"},
    metadata_exempt_prefixes=["docs/page-templates/"],
)


class ContentCheckTests(unittest.TestCase):
    def test_secret_assignment_is_quarantined(self):
        report = check_text(
            "docs/baoyan/new.md",
            'api_key = "abcdefghijklmnopqrstuv"',
            CONFIG,
        )
        self.assertEqual(report.action, Action.QUARANTINE)
        self.assertIn("SECRET_ASSIGNMENT", {item.rule_id for item in report.findings})

    def test_article_with_ready_metadata_passes(self):
        content = """---
publication:
  status: ready
  author_consent_confirmed: true
  third_party_data_checked: true
  media_rights_confirmed: true
---

# 一篇经验

这是作者的一手经历。
"""
        report = check_text("docs/baoyan/new.md", content, CONFIG)
        self.assertEqual(report.action, Action.AUTO_PUBLISH)
        self.assertEqual(report.findings, [])

    def test_unapproved_contact_requires_revision(self):
        content = """---
publication:
  status: ready
  author_consent_confirmed: true
  public_contact_consent: false
  third_party_data_checked: true
  media_rights_confirmed: true
---

联系邮箱：person@example.com
"""
        report = check_text("docs/baoyan/new.md", content, CONFIG)
        self.assertEqual(report.action, Action.RETURN_FOR_REVISION)
        self.assertIn("PRIVACY_EMAIL", {item.rule_id for item in report.findings})

    def test_site_contact_is_allowed_on_trusted_page(self):
        report = check_text(
            "docs/contribute.md",
            "投稿邮箱：submit@example.com",
            CONFIG,
        )
        self.assertEqual(report.action, Action.AUTO_PUBLISH)

    def test_template_placeholders_are_not_reported(self):
        report = check_text(
            "docs/page-templates/article.md",
            "# [待填写：标题]",
            CONFIG,
        )
        self.assertEqual(report.action, Action.AUTO_PUBLISH)


if __name__ == "__main__":
    unittest.main()
