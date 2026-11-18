"""批成员落库与批原子证明读模型。

批次边界形态（择一）：批次成员表 —— load_batches(批次行：成败/错误) +
load_batch_members(运单集合、每单计划/写入点数)。禁止只记总成功数。

报告与证明同源：装载报告、批原子证明接口、装载页/检查器全部读这两张表 +
正式线 hops(batch_id 列) 现场互证，不另起统计口径。
"""


def record_batch(conn, batch_id, cutoff_ts, outcome, members, now, error=None):
    """在调用方事务内写入批次行 + 成员行。

    members: [{"waybill_id", "planned_points", "written_points"}, ...]
    成功批次与正式写入同事务提交；失败批次在整批回滚后另起小事务落库，
    成员 written_points 一律为 0 —— 批次标失败则无任何成员投影/时间线已变。
    """
    written_total = sum(m["written_points"] for m in members)
    conn.execute(
        """
        INSERT INTO load_batches(id, cutoff_ts, outcome, error, member_count, written_total, created_at)
        VALUES (?,?,?,?,?,?,?)
        """,
        (batch_id, cutoff_ts, outcome, error, len(members), written_total, now),
    )
    for m in members:
        conn.execute(
            """
            INSERT INTO load_batch_members(batch_id, waybill_id, planned_points, written_points)
            VALUES (?,?,?,?)
            """,
            (batch_id, m["waybill_id"], m["planned_points"], m["written_points"]),
        )


def get_batch(conn, batch_id):
    row = conn.execute(
        "SELECT * FROM load_batches WHERE id=?", (batch_id,)
    ).fetchone()
    return dict(row) if row else None


def get_proof(conn, batch_id):
    """批原子证明（只读）：批次、成员运单、各单写入点数、总成败 + 正式线互证。"""
    batch = get_batch(conn, batch_id)
    if not batch:
        return None
    members = [
        dict(r)
        for r in conn.execute(
            """
            SELECT waybill_id, planned_points, written_points
            FROM load_batch_members WHERE batch_id=? ORDER BY waybill_id
            """,
            (batch_id,),
        ).fetchall()
    ]
    for m in members:
        # 互证：正式线上归属本批的现存点数（与成员表落库值对照）
        m["formal_points_now"] = conn.execute(
            """
            SELECT COUNT(*) AS c FROM hops
            WHERE batch_id=? AND waybill_id=? AND channel='primary' AND retracted=0
            """,
            (batch_id, m["waybill_id"]),
        ).fetchone()["c"]
    return {
        "batch_id": batch["id"],
        "cutoff_ts": batch["cutoff_ts"],
        "outcome": batch["outcome"],
        "error": batch["error"],
        "member_count": batch["member_count"],
        "written_total": batch["written_total"],
        "created_at": batch["created_at"],
        "members": members,
        "consistent": _check_consistency(batch["outcome"], members),
    }


def list_proofs(conn):
    rows = conn.execute(
        "SELECT id FROM load_batches ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return [get_proof(conn, r["id"]) for r in rows]


def batches_for_waybill(conn, waybill_id):
    """某运单参与过的装载批次（检查器/时间线视角，与证明同源）。"""
    rows = conn.execute(
        """
        SELECT m.batch_id, m.planned_points, m.written_points, b.outcome, b.created_at
        FROM load_batch_members m
        JOIN load_batches b ON b.id = m.batch_id
        WHERE m.waybill_id=?
        ORDER BY b.created_at DESC, m.batch_id DESC
        """,
        (waybill_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _check_consistency(outcome, members):
    """硬约束现场校验：
    - 批次标成功 ⇒ 每个成员正式线现存本批点数 == 落库写入点数；
    - 批次标失败 ⇒ 每个成员正式线现存本批点数 == 0 且落库写入点数 == 0。
    """
    if outcome == "success":
        return all(m["formal_points_now"] == m["written_points"] for m in members)
    return all(
        m["formal_points_now"] == 0 and m["written_points"] == 0 for m in members
    )
