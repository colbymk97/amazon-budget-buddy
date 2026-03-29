import io
import json
import unittest
from argparse import Namespace
from contextlib import redirect_stdout
from unittest.mock import patch

from amazon_spending.actual_sync import ActualConfig, load_config, save_config
from amazon_spending.cli import _handle_actual_configure
from amazon_spending.db import connect, init_db


class ActualConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = connect(":memory:")
        init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_save_and_load_actual_config_round_trip(self) -> None:
        cfg = ActualConfig(
            base_url="http://localhost:5006",
            password="secret",
            file="My Budget",
            account_name="Chase Sapphire",
        )

        save_config(self.conn, cfg)
        loaded = load_config(self.conn)

        self.assertEqual(loaded, cfg)

    def test_cli_actual_configure_persists_and_shows_without_password(self) -> None:
        save_config(
            self.conn,
            ActualConfig(
                base_url="http://localhost:5006",
                password="secret",
                file="My Budget",
                account_name="Old Account",
            ),
        )

        configure_args = Namespace(
            base_url=None,
            password=None,
            file=None,
            account_name="Updated Account",
            clear_account_name=False,
            show=False,
            test_connection=False,
            output_json=False,
        )

        with redirect_stdout(io.StringIO()):
            _handle_actual_configure(configure_args, self.conn)

        updated = load_config(self.conn)
        self.assertEqual(updated.account_name, "Updated Account")
        self.assertEqual(updated.password, "secret")

        show_args = Namespace(
            base_url=None,
            password=None,
            file=None,
            account_name=None,
            clear_account_name=False,
            show=True,
            test_connection=False,
            output_json=True,
        )
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            _handle_actual_configure(show_args, self.conn)

        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload,
            {
                "configured": True,
                "base_url": "http://localhost:5006",
                "file": "My Budget",
                "account_name": "Updated Account",
                "password_configured": True,
            },
        )

    def test_cli_actual_configure_prompts_for_password_when_missing(self) -> None:
        args = Namespace(
            base_url="http://localhost:5006",
            password=None,
            file="My Budget",
            account_name=None,
            clear_account_name=False,
            show=False,
            test_connection=False,
            output_json=False,
        )

        with patch("amazon_spending.cli.getpass.getpass", return_value="prompt-secret"):
            with redirect_stdout(io.StringIO()):
                _handle_actual_configure(args, self.conn)

        loaded = load_config(self.conn)
        self.assertEqual(loaded.password, "prompt-secret")

    def test_cli_actual_configure_can_test_connection_before_saving(self) -> None:
        args = Namespace(
            base_url="http://localhost:5006",
            password="secret",
            file="My Budget",
            account_name="Checking",
            clear_account_name=False,
            show=False,
            test_connection=True,
            output_json=False,
        )

        with patch("amazon_spending.actual_sync.test_connection") as mock_test_connection:
            with redirect_stdout(io.StringIO()):
                _handle_actual_configure(args, self.conn)

        saved = load_config(self.conn)
        self.assertEqual(saved.account_name, "Checking")
        mock_test_connection.assert_called_once()

    def test_cli_actual_configure_stops_when_connection_test_fails(self) -> None:
        args = Namespace(
            base_url="http://localhost:5006",
            password="secret",
            file="My Budget",
            account_name=None,
            clear_account_name=False,
            show=False,
            test_connection=True,
            output_json=False,
        )

        stderr = io.StringIO()
        with patch("amazon_spending.actual_sync.test_connection", side_effect=RuntimeError("boom")):
            with redirect_stdout(io.StringIO()):
                with patch("sys.stderr", stderr):
                    with self.assertRaises(SystemExit):
                        _handle_actual_configure(args, self.conn)

        self.assertIsNone(load_config(self.conn))
        self.assertIn("Error: boom", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
