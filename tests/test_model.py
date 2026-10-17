import os
import tempfile

os.environ["GPSTOCK_DATA_DIR"] = tempfile.mkdtemp(prefix="gpstock-test-")

import duckdb  # noqa: E402
import pytest  # noqa: E402

from gpstock.build import build, export  # noqa: E402
from gpstock.generate import generate  # noqa: E402
from gpstock.report import build_report  # noqa: E402


@pytest.fixture(scope="module")
def built():
    generate()
    c = duckdb.connect(":memory:")
    checks = build(c)
    yield c, checks
    c.close()


@pytest.fixture(scope="module")
def con(built):
    return built[0]


def test_all_data_checks_pass(built):
    checks = built[1]
    assert checks.failing_rows.sum() == 0, checks


def test_clinical_use_rises_in_flu_season(con):
    winter, rest = con.execute("""
        SELECT avg(used) FILTER (WHERE d.season = 'Winter (flu season)'), avg(used) FILTER (WHERE d.season = 'Rest of year')
        FROM fact_daily_stock f JOIN dim_date d USING (date) JOIN dim_item i USING (item_id)
        WHERE i.is_clinical AND d.is_open_day""").fetchone()
    assert winter > rest * 1.1


def test_spend_only_counts_real_purchases(con):
    leaked = con.execute("""SELECT count(*) FROM fact_movement
                            WHERE spend_gbp > 0 AND movement_kind IN ('opening', 'transfer in')""").fetchone()[0]
    assert leaked == 0


def test_waste_is_a_realistic_share_of_use(con):
    pct = con.execute("""SELECT sum(waste_gbp) / sum(value_gbp) FILTER (WHERE movement_kind = 'used')
                         FROM fact_movement""").fetchone()[0]
    assert 0.005 < pct < 0.10


def test_urgent_requests_are_reviewed_faster(con):
    hours = dict(con.execute("SELECT priority, avg(hours_to_review) FROM fact_request GROUP BY 1").fetchall())
    assert hours["urgent"] < hours["normal"]


def test_export_and_report(con, tmp_path):
    counts = export(con, tmp_path)
    assert (tmp_path / "GP_Stock_PowerBI.xlsx").exists() and counts["FactDailyStock"] == 365 * 2 * 39
    html = build_report(con)
    assert "Expiry watch list" in html and "plotly" in html
