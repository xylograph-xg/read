"""Independent source-engine tests; synthetic PDFs only, no model calls."""
import hashlib
from pathlib import Path
import tempfile
import unittest

import pymupdf
from read.api import parser__parse_pdf, evidence_quotes__verify_quotes, prompt_input__source_prompt


class SourceContract(unittest.TestCase):
    def test_parse_pdf_preserves_source_bytes_page_identity_and_numeric_conditions(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'synthetic.pdf'
            document = pymupdf.open()
            for text in ('Measured current is 7 mA at 300 K under condition A.',
                         'Measured current is 9 mA at 320 K under condition B.'):
                page = document.new_page()
                page.insert_text((72, 120), text)
            document.save(source)
            document.close()
            fingerprint = hashlib.sha256(source.read_bytes()).hexdigest()
            parsed = parser__parse_pdf(source, {'enable_equations': False})
            self.assertEqual(parsed.page_count, 2)
            for index, number in enumerate(('7 mA at 300 K', '9 mA at 320 K')):
                self.assertIn(number, parsed.page_texts[index])
                paragraph = next(p for p in parsed.paragraphs if number in p.text)
                self.assertEqual(paragraph.page, index)
                self.assertTrue(paragraph.cite().startswith(f'[p.{index+1}]'))
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), fingerprint)

    def test_quote_must_match_original_and_actual_sent_evidence(self):
        source = 'Measured current is 7 mA at 300 K under condition A.'
        quote = '“Measured current is 7 mA at 300 K under condition A.”'
        self.assertTrue(evidence_quotes__verify_quotes(quote, source, source)[1])
        self.assertFalse(evidence_quotes__verify_quotes(quote, source, source.replace('7 mA', '9 mA'))[1])
        self.assertFalse(evidence_quotes__verify_quotes(quote, source.replace('300 K', '320 K'), source)[1])

    def test_multiple_quotes_do_not_silently_accept_only_matching_subset(self):
        source = 'The measured current is 7 mA at 300 K.'
        raw = source + '\nThe measured current is 9 mA at 320 K.'
        entries, passed = evidence_quotes__verify_quotes(raw, source, source)
        self.assertEqual(len(entries), 2)
        self.assertFalse(passed)

    def test_prompt_evidence_retains_source_fields_and_excludes_notes_and_old_answers(self):
        fields = {'caption': 'Fig. 1. Original signal at 300 K.',
                  'equation_text': 'I = V / R', 'personal_notes': 'private note',
                  'old_answer': 'previous scientific conclusion'}
        prompt = prompt_input__source_prompt('rendered prompt', fields)
        self.assertIn(fields['caption'], prompt.evidence)
        self.assertIn(fields['equation_text'], prompt.evidence)
        self.assertNotIn(fields['personal_notes'], prompt.evidence)
        self.assertNotIn(fields['old_answer'], prompt.evidence)
