"""batch_waybill_atomic 验收：整批同成败、回滚后点数与批前一致、证明同源。"""

import json

import pytest
from fastapi.testclient import TestClient

from app import seed
from app.db import DB_PATH, FIXTURES_DIR, connect
from app.main import app
from app.modules.batch_waybill_atomic import service, store


@pytest.fixture(autouse=True)
def fresh_db():
    if DB_PATH.exists():
        DB_PATH.unlink()
    seed.init_db()
    yield


def _snapshot(conn):
    """每单正式线点数 + 投影 + 证明总数 —— 批前批后对照用。"""
    waybills = {
        r["id"]: {"status_proj": r["status_proj"]}
        for r in conn.execute("SELECT id, status_proj FROM waybills")
    }
    for wid in waybills:
        waybills[wid]["points"] = conn.execute(
            "SELECT COUNT(*) AS c FROM hops WHERE waybill_id=? AND channel='primary' AND retracted=0",
            (wid,),
        ).fetchone()["c"]
    proofs = conn.execute("SELECT COUNT(*) AS c FROM status_proofs").fetchone()["c"]
    return {"waybills": waybills, "proofs_total": proofs}


def _failing_payload():
    return json.loads((FIXTURES_DIR / "load_batch_atomic.json").read_text(encoding="utf-8"))


def _ok_payload():
    return {
        "batch_id": "B-ATOMIC-OK",
        "cutoff_ts": "2026-11-18T10:00:00Z",
        "hops": [
            {"id": "H-B1", "waybill_id": "WB-1001", "event_ts": "2026-11-18T09:10:00Z",
             "location_code": "HZ-STATION", "event_code": "OUT_FOR_DELIVERY", "seq": 6},
            {"id": "H-B2", "waybill_id": "WB-1002", "event_ts": "2026-11-18T09:20:00Z",
             "location_code": "SH-LOCAL", "event_code": "DELIVERED", "seq": 3},
        ],
    }


def test_failed_batch_rolls_back_every_waybill():
    """夹具「第二单故意失败」：整批回滚后各单点数/投影与批前一致。"""
    conn = connect()
    before = _snapshot(conn)
    conn.close()

    result = service.run_atomic_batch(_failing_payload())

    assert result["ok"] is False
    report = result["report"]
    assert report["outcome"] == "failed"
    assert "NOT NULL" in report["error"]
    # 批次边界可查：成员表记录运单集合与成败，成员写入点数全 0
    assert {m["waybill_id"] for m in report["members"]} == {"WB-1001", "WB-1002"}
    assert all(m["written_points"] == 0 for m in report["members"])
    assert all(m["formal_points_now"] == 0 for m in report["members"])
    assert report["consistent"] is True
    planned = {m["waybill_id"]: m["planned_points"] for m in report["members"]}
    assert planned == {"WB-1001": 2, "WB-1002": 1}

    conn = connect()
    after = _snapshot(conn)
    # 硬约束：批次标失败 ⇒ 任一成员正式线点数与投影均未变
    assert after == before
    assert not conn.execute(
        "SELECT 1 FROM hops WHERE batch_id='B-ATOMIC-01'"
    ).fetchone()
    conn.close()


def test_success_batch_commits_all_members_together():
    """成功路径：全部成员正式线同见本批点，投影齐变，证明一致。"""
    conn = connect()
    before = _snapshot(conn)
    conn.close()

    result = service.run_atomic_batch(_ok_payload())

    assert result["ok"] is True
    report = result["report"]
    assert report["outcome"] == "success"
    assert report["written_total"] == 2
    assert report["consistent"] is True
    for m in report["members"]:
        assert m["written_points"] == m["planned_points"] == 1
        # 硬约束：批次标成功 ⇒ 成员正式线现存本批点
        assert m["formal_points_now"] == 1

    conn = connect()
    after = _snapshot(conn)
    assert after["waybills"]["WB-1001"]["points"] == before["waybills"]["WB-1001"]["points"] + 1
    assert after["waybills"]["WB-1002"]["points"] == before["waybills"]["WB-1002"]["points"] + 1
    assert after["waybills"]["WB-1001"]["status_proj"] == "派送中"
    assert after["waybills"]["WB-1002"]["status_proj"] == "已签收"
    conn.close()


def test_replay_is_idempotent_and_never_patches_half_batch():
    """重跑同一 batch_id：只回同源证明，不二次改写（禁止补失败运单造成半截批次）。"""
    first = service.run_atomic_batch(_failing_payload())
    conn = connect()
    mid = _snapshot(conn)
    conn.close()
    second = service.run_atomic_batch(_failing_payload())

    assert second["replayed"] is True
    assert second["ok"] is False
    assert second["report"] == first["report"]

    conn = connect()
    assert _snapshot(conn) == mid
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM load_batches WHERE id='B-ATOMIC-01'"
    ).fetchone()["c"] == 1
    conn.close()


def test_api_report_and_proof_share_one_source():
    """装载报告、批证明接口、时间线/检查器同源。"""
    with TestClient(app) as client:
        run = client.post("/api/load-batch/run").json()
        assert run["ok"] is False
        report = run["report"]

        proof = client.get(f"/api/load-batches/{report['batch_id']}").json()
        assert proof == report  # 报告与证明同源

        listed = client.get("/api/load-batches").json()
        assert [b["batch_id"] for b in listed] == [report["batch_id"]]
        assert listed[0]["outcome"] == "failed"

        # 检查器视角：时间线接口带本单批次成员信息，与证明同源
        timeline = client.get("/api/waybills/WB-1001/timeline").json()
        lb = timeline["load_batches"]
        assert len(lb) == 1
        assert lb[0]["batch_id"] == report["batch_id"]
        assert lb[0]["outcome"] == "failed"
        assert lb[0]["written_points"] == 0
        # 回滚后时间线不含本批任何点
        assert all(h["batch_id"] != report["batch_id"] for h in timeline["hops"])

        missing = client.get("/api/load-batches/NOPE")
        assert missing.status_code == 404
