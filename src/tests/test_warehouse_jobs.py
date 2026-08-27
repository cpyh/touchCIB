import unittest
from threading import Barrier
from datetime import date
from unittest.mock import MagicMock, patch

from src import warehouse_jobs
from src.app import app


class WarehouseJobsTestCase(unittest.TestCase):
    def test_definition_exposes_fixed_dag(self) -> None:
        definition = warehouse_jobs.pipeline_definition()
        stages = {stage["stage_id"]: stage for stage in definition["stages"]}

        self.assertEqual(list(stages), ["warehouse", "quality", "marketing", "portfolio", "bi"])
        self.assertEqual(stages["quality"]["depends_on"], ["warehouse"])
        self.assertEqual(stages["bi"]["depends_on"], ["marketing", "portfolio"])
        self.assertEqual(definition["default_business_date"], "2026-04-15")
        self.assertEqual(definition["dws_snapshot_date"], "2026-03-31")

    def test_start_creates_one_background_run(self) -> None:
        thread = MagicMock()
        thread_factory = MagicMock(return_value=thread)
        with (
            patch.object(warehouse_jobs, "_latest_run", None),
            patch.object(warehouse_jobs.threading, "Thread", thread_factory),
        ):
            run = warehouse_jobs.start_pipeline_run()

        self.assertEqual(run["status"], "running")
        self.assertEqual(run["business_date"], "2026-04-15")
        self.assertEqual(len(run["stages"]), 5)
        self.assertTrue(all(stage["status"] == "pending" for stage in run["stages"]))
        self.assertEqual(
            thread_factory.call_args.kwargs["args"],
            (run["run_id"], date(2026, 4, 15)),
        )
        thread.start.assert_called_once_with()

    def test_running_pipeline_rejects_duplicate_trigger(self) -> None:
        with patch.object(warehouse_jobs, "_latest_run", {"status": "running"}):
            with self.assertRaises(warehouse_jobs.PipelineBusyError):
                warehouse_jobs.start_pipeline_run()

    @patch("src.warehouse_jobs.subprocess.Popen")
    def test_stage_execution_uses_fixed_python_module(self, popen: MagicMock) -> None:
        process = popen.return_value
        process.stdout = ["one\n", "two\n"]
        process.wait.return_value = 0
        with patch.object(
            warehouse_jobs,
            "_latest_run",
            {"logs": [], "stages": []},
        ):
            warehouse_jobs._run_module(
                warehouse_jobs.STAGES[1],
                date(2026, 4, 16),
            )

        command = popen.call_args.args[0]
        self.assertEqual(command[1:4], ["-u", "-m", "src.scripts.check_data_quality"])
        self.assertNotIn("shell", popen.call_args.kwargs)

    def test_business_date_is_only_added_to_date_aware_stages(self) -> None:
        selected = date(2026, 4, 16)

        self.assertEqual(warehouse_jobs._stage_args(warehouse_jobs.STAGES[0], selected), ())
        self.assertEqual(
            warehouse_jobs._stage_args(warehouse_jobs.STAGES[2], selected),
            ("--strategy-date", "2026-04-16"),
        )
        self.assertEqual(
            warehouse_jobs._stage_args(warehouse_jobs.STAGES[3], selected),
            ("--calculation-date", "2026-04-16"),
        )

    def test_marketing_and_portfolio_stages_really_run_in_parallel(self) -> None:
        branch_barrier = Barrier(2, timeout=2)

        def run_module(stage, _business_date):
            if stage.stage_id in {"marketing", "portfolio"}:
                branch_barrier.wait()

        thread = MagicMock()
        with patch.object(warehouse_jobs, "_latest_run", None):
            with patch.object(
                warehouse_jobs.threading,
                "Thread",
                return_value=thread,
            ):
                run = warehouse_jobs.start_pipeline_run()
            with (
                patch.object(warehouse_jobs, "_run_module", side_effect=run_module),
                patch.object(
                    warehouse_jobs,
                    "_bi_snapshot",
                    return_value={
                        "dws_customers": 8000,
                        "business_date": "2026-04-15",
                        "marketing_rows": 24000,
                        "marketing_customers": 8000,
                        "portfolio_scenarios": 20,
                    },
                ),
            ):
                warehouse_jobs._run_pipeline(run["run_id"], date(2026, 4, 15))
                completed = warehouse_jobs.latest_pipeline_run()

        self.assertEqual(completed["status"], "success")
        self.assertEqual(completed["current_stages"], [])
        self.assertTrue(all(stage["status"] == "success" for stage in completed["stages"]))


class WarehouseJobsRouteTestCase(unittest.TestCase):
    def setUp(self) -> None:
        app.config["TESTING"] = True
        self.client = app.test_client()

    @patch("src.app.latest_pipeline_run", return_value=None)
    def test_latest_route_returns_definition(self, _latest: MagicMock) -> None:
        response = self.client.get("/pipeline/runs/latest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["definition"]["stages"]), 5)
        self.assertIsNone(response.get_json()["run"])

    @patch("src.app.start_pipeline_run")
    def test_start_route_is_async(self, start: MagicMock) -> None:
        start.return_value = {"run_id": "manual_test", "status": "running"}

        response = self.client.post(
            "/pipeline/runs",
            json={"business_date": "2026-04-16"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.get_json()["run"]["run_id"], "manual_test")
        start.assert_called_once_with(date(2026, 4, 16))

    @patch("src.app.start_pipeline_run")
    def test_start_route_rejects_invalid_business_date(self, start: MagicMock) -> None:
        response = self.client.post(
            "/pipeline/runs",
            json={"business_date": "2026-02-30"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("YYYY-MM-DD", response.get_json()["error"])
        start.assert_not_called()

    @patch("src.app.start_pipeline_run")
    def test_start_route_rejects_parallel_run(self, start: MagicMock) -> None:
        start.side_effect = warehouse_jobs.PipelineBusyError("busy")

        response = self.client.post("/pipeline/runs", json={})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error"], "busy")


if __name__ == "__main__":
    unittest.main()
