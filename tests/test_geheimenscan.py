"""app/secret_scan.py: vindt echte geheimvormen, laat plaatshouders en openbare adressen met rust en toont nooit een waarde."""
import unittest

from app import secret_scan as S

B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def names(text):
    return [n for _, n in S.scan_text(text)]


class ScanTests(unittest.TestCase):
    def test_vindt_echte_vormen(self):
        self.assertEqual(names("-----BEGIN PRIVATE KEY-----"), ["privésleutel (PEM)"])  # geheimscan:ok
        self.assertEqual(names("k = 'sk-ant-" + "a" * 30 + "'"), ["Anthropic-sleutel"])
        self.assertEqual(names("TELEGRAM = '123456789:" + "A" * 35 + "'"), ["Telegram-bottoken"])
        self.assertEqual(names("x = " + (B58 * 2)[:88]), ["Solana-geheim (base58)"])
        self.assertEqual(names("[" + ",".join(["7"] * 64) + "]"), ["Solana-geheim (lijst van 64 bytes)"])
        self.assertEqual(names("JWT_SECRET=Zq8xV2mN4pL7wR1tY6uH9"), ["toegewezen geheim"])  # geheimscan:ok

    def test_laat_plaatshouders_en_adressen_met_rust(self):
        self.assertEqual(names("JWT_SECRET=change-me-to-a-long-random-string"), [])
        self.assertEqual(names("JWT_SECRET=test_secret_value_12345"), [])
        self.assertEqual(names("JWT_SECRET=<vul-hier-in>"), [])
        self.assertEqual(names("wallet = '" + B58[:44] + "'"), [])          # een Solana-adres is openbaar
        self.assertEqual(names("TOKEN = os.getenv('X')"), [])
        self.assertEqual(names("JWT_SECRET=Zq8xV2mN4pL7wR1tY6uH9  # geheimscan:ok"), [])

    def test_verboden_bestanden(self):
        for p in (".env", "data/.env.prod", "keys/id_ed25519", "a/wallet.pem", "sol-keypair.json"):
            self.assertTrue(S.forbidden_file(p), p)
        for p in (".env.example", "app/config.py", "docs/blueprint.md"):
            self.assertFalse(S.forbidden_file(p), p)


if __name__ == "__main__":
    unittest.main()
