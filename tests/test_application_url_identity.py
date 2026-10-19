import unittest
from resume_gen.automation.autoapply import _norm_url


class ApplicationUrlIdentityTests(unittest.TestCase):
    def test_query_posting_ids_cannot_merge_employers(self):
        self.assertNotEqual(_norm_url('https://londontechjobs.ca/job.aspx?jid=canada-life'),
                            _norm_url('https://londontechjobs.ca/job.aspx?jid=td'))
        self.assertNotEqual(_norm_url('https://ca.indeed.com/viewjob?jk=one'),
                            _norm_url('https://ca.indeed.com/viewjob?jk=two'))

    def test_tracking_parameters_and_order_do_not_duplicate_postings(self):
        self.assertEqual(_norm_url('https://EXAMPLE.com/job/?jid=one&utm_source=mail#apply'),
                         _norm_url('https://example.com/job?jid=one'))
        self.assertEqual(_norm_url('https://example.com/job?b=2&a=1'),
                         _norm_url('https://example.com/job?a=1&b=2'))
