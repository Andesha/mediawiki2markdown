import re
import unittest

import mwclient

from mediawiki2markdown import get_rendered_html, html_to_markdown


class LiveWikiConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = mwclient.Site("docs.alliancecan.ca", path="/mediawiki/")

    def assert_page_has_no_raw_wrappers(self, page, expected_text):
        markdown = html_to_markdown(get_rendered_html(self.site, page))

        self.assertIn(expected_text, markdown)
        self.assertIsNone(re.search(r"</?(?:a|div|span)\b", markdown, re.IGNORECASE))

    def test_french_ccv_guide(self):
        self.assert_page_has_no_raw_wrappers(
            "Alliance CCV submission guide/fr",
            "Renseignements généraux",
        )

    def test_french_arbutus_aws_cli_guide(self):
        self.assert_page_has_no_raw_wrappers(
            "Accessing the Arbutus object storage with AWS CLI/fr",
            "aws_access_key_id = <access_key>",
        )


if __name__ == "__main__":
    unittest.main()
