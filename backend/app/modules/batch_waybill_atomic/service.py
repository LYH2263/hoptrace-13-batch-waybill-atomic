"""整批运单级原子装载服务。

提交路径（择一）：单数据库事务覆盖本批全部运单写入 ——
一个 BEGIN IMMEDIATE 事务内完成：全部成员的正式 hop 写入、投影变更、
状态证明、批次行与成员行落库，然后一次 COMMIT。
任一成员的正式写入失败 ⇒ 整体 ROLLBACK（正式时间线与投影零变更），
再另起小事务只落「批次行(失败)+成员行(written=0)」保证批次边界可查。

硬约束：
- 禁止先提交部分运单再补失败运单（本服务无部分提交路径）；
- 批次标成功 ⇒ 所有成员正式线必含本批点（同事务提交）；
- 批次标失败 ⇒ 无任何成员投影已变（整批回滚）。
"""

import json
import uuid
from datetime import datetime, timezone

from app.db import FIXTURES_DIR, connect
from app.modules.batch_waybill_atomic import store
from app.seed import map_status

FIXTURE_NAME = "load_batch_atomic.json"


def load_fixture_payload() -> dict:
    path = FIXTURES_DIR / FIXTURE_NAME
    if not path.exists():
        raise FileNotFoundError(f"缺少 {FIXTURE_NAME}")
    return json.loads(path.read_text(encoding="utf-8"))


def run_atomic_batch(payload: dict) -> dict:
    """跑一个整批原子装载批次；返回的报告即从落库证明读回（报告与证明同源）。"""
    batch_id = payload.get("batch_id") or f"B-{uuid.uuid4().hex[:8]}"
    cutoff = payload.get("cutoff_ts")
    hops = payload.get("hops", [])
    if not hops:
        return {"ok": False, "error": "空批次：无任何轨迹点"}

    conn = connect()
    try:
        if store.get_batch(conn, batch_id):
            # 幂等重放：批次边界已落库，直接回同源证明，绝不二次改写正式线
            proof = store.get_proof(conn, batch_id)
            return {"ok": proof["outcome"] == "success", "replayed": True, "report": proof}

        members = _group_by_waybill(hops)
        conn.execute("BEGIN IMMEDIATE")
        try:
            written = dict.fromkeys(members, 0)
            for wid, wps in members.items():
                _ensure_waybill(conn, wid, wps)
                for hop in wps:
                    _insert_hop(conn, batch_id, wid, hop)
                    written[wid] += 1
                    _apply_projection(conn, wid, hop)
            store.record_batch(
                conn, batch_id, cutoff, "success",
                _member_rows(members, written), now=_now(),
            )
            conn.commit()
        except Exception as e:
            # 整批回滚：正式时间线 / 投影 / 状态证明 / 批行全部不落地
            conn.rollback()
            conn.execute("BEGIN IMMEDIATE")
            store.record_batch(
                conn, batch_id, cutoff, "failed",
                _member_rows(members, None), now=_now(), error=str(e),
            )
            conn.commit()
        proof = store.get_proof(conn, batch_id)
        return {"ok": proof["outcome"] == "success", "report": proof}
    finally:
        conn.close()


def _group_by_waybill(hops):
    """按运单分组（保持载荷中首现顺序），得出本批成员集合。"""
    members = {}
    for hop in hops:
        members.setdefault(hop["waybill_id"], []).append(hop)
    return members


def _member_rows(members, written):
    return [
        {
            "waybill_id": wid,
            "planned_points": len(wps),
            "written_points": 0 if written is None else written[wid],
        }
        for wid, wps in members.items()
    ]


def _ensure_waybill(conn, wid, wps):
    exists = conn.execute("SELECT 1 FROM waybills WHERE id=?", (wid,)).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO waybills(id, title, status_proj, created_at) VALUES (?,?,?,?)",
            (wid, wps[0].get("waybill_title") or wid, "未知", _now()),
        )


def _insert_hop(conn, batch_id, wid, hop):
    """正式线写入：严格 INSERT（不用 OR IGNORE），任何约束冲突都使整批失败。"""
    conn.execute(
        """
        INSERT INTO hops(id, waybill_id, event_ts, location_code, event_code, seq, channel, batch_id)
        VALUES (?,?,?,?,?,?, 'primary', ?)
        """,
        (
            hop["id"],
            wid,
            hop.get("event_ts"),
            hop.get("location_code"),
            hop.get("event_code"),
            hop.get("seq"),
            batch_id,
        ),
    )


def _apply_projection(conn, wid, hop):
    proj = map_status(hop.get("event_code"))
    conn.execute("UPDATE waybills SET status_proj=? WHERE id=?", (proj, wid))
    conn.execute(
        "INSERT INTO status_proofs(waybill_id, last_hop_id, mapped_code, proj_value, created_at) VALUES (?,?,?,?,?)",
        (wid, hop["id"], hop.get("event_code"), proj, _now()),
    )


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
