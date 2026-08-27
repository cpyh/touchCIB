import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from src.pipelines.run_all import main


class RunAllTestCase(unittest.TestCase):
    @patch("src.pipelines.run_all.run_command")
    def test_every_stage_uses_current_python_executable(self, run_command):
        with redirect_stdout(StringIO()):
            result = main(["--a1-model", "lgbm_onehot"])

        self.assertEqual(result, 0)
        commands = [call.args[1] for call in run_command.call_args_list]
        self.assertTrue(commands)
        self.assertTrue(all(command[0] == sys.executable for command in commands))
        self.assertIn(
            [sys.executable, "-m", "src.marketing", "--model", "lgbm_onehot"],
            commands,
        )
        self.assertIn(
            [
                sys.executable,
                "-m",
                "src.partA1serving.training.train_and_save",
                "--profile",
                "full",
                "--model",
                "lgbm_onehot",
            ],
            commands,
        )


if __name__ == "__main__":
    unittest.main()
