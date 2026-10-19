import unittest
from resume_gen.guard import _display_location


class ResumeLocationPolicyTests(unittest.TestCase):
    def test_location_broadens_without_claiming_residence_in_the_target_province(self):
        profile = {'contact': {'location': 'London, ON, Canada'}}
        self.assertEqual(_display_location(profile, 'London, Ontario'), 'London, ON, Canada')
        self.assertEqual(_display_location(profile, 'Toronto, ON'), 'Ontario, Canada')
        self.assertEqual(_display_location(profile, 'Calgary, Alberta'), 'Canada · Applying in Alberta')
        self.assertEqual(_display_location(profile, 'Vancouver, BC'), 'Canada · Applying in British Columbia')
        self.assertEqual(_display_location(profile, 'Remote, Canada'), 'Canada')
