"""Exercise the production ASGI app over loopback HTTP, including authentication."""
import unittest

from scripts.verify import walkthrough


class HttpJourney(unittest.TestCase):
    def test_two_users_purchase_recovery_and_three_instalments(self):
        walkthrough(verbose=False)
