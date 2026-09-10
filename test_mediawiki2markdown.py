import re
import unittest

import mwclient

from mediawiki2markdown import (
    convert_internal_links,
    get_rendered_html,
    html_to_markdown,
)


class LiveWikiConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.site = mwclient.Site("docs.alliancecan.ca", path="/mediawiki/")

    def assert_page_has_no_raw_wrappers(self, page, expected_text):
        markdown = html_to_markdown(get_rendered_html(self.site, page))

        self.assertIn(expected_text, markdown)
        self.assertIsNone(
            re.search(r"</?(?:a|b|br|div|span)\b", markdown, re.IGNORECASE)
        )

    def test_french_ccv_guide(self):
        self.assert_page_has_no_raw_wrappers(
            "Alliance CCV submission guide/fr",
            "Renseignements généraux",
        )

    def test_french_arbutus_aws_cli_guide(self):
        page = "Accessing the Arbutus object storage with AWS CLI/fr"
        self.assert_page_has_no_raw_wrappers(page, "aws_access_key_id = <access_key>")

        rendered_html = get_rendered_html(self.site, page)
        rendered_html = convert_internal_links(
            rendered_html,
            {
                "Accessing the Arbutus object storage with AWS CLI": {},
                "Arbutus object storage": {},
            },
            "fr",
        )
        markdown = html_to_markdown(rendered_html)
        self.assertIn("(./Arbutus%20object%20storage.md", markdown)
        self.assertIn(
            "(../en/Accessing%20the%20Arbutus%20object%20storage%20with%20AWS%20CLI.md",
            markdown,
        )

    def test_internal_links_do_not_change_shell_conditions(self):
        rendered_html = '<pre>if [[ "$value" = yes ]]; then</pre>'

        converted = convert_internal_links(rendered_html, {}, "en")

        self.assertEqual(rendered_html, converted)

    def test_translation_divs_inside_code_are_removed(self):
        rendered_html = (
            "<pre>first line\n"
            '&lt;div class="mw-translate-fuzzy"&gt;second line&lt;/div&gt;'
            "</pre>"
        )

        markdown = html_to_markdown(rendered_html)

        self.assertIn("first line", markdown)
        self.assertIn("second line", markdown)
        self.assertNotRegex(markdown, r"</?div\b")


if __name__ == "__main__":
    unittest.main()
