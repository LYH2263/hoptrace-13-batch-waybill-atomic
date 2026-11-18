from fastapi import APIRouter, HTTPException

from app.db import connect
from app.modules.batch_waybill_atomic import service, store

router = APIRouter(prefix="/api")


@router.post("/load-batch/run")
def run_load_batch():
    """从本地夹具跑一个整批原子装载批次（夹具含「第二单故意失败」场景）。"""
    try:
        payload = service.load_fixture_payload()
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return service.run_atomic_batch(payload)


@router.get("/load-batches")
def list_load_batches():
    """批原子证明列表（只读）：批次、成员运单、各单写入点数、总成败。"""
    conn = connect()
    try:
        return store.list_proofs(conn)
    finally:
        conn.close()


@router.get("/load-batches/{batch_id}")
def load_batch_proof(batch_id: str):
    """单批原子证明（只读），与装载报告同源。"""
    conn = connect()
    try:
        proof = store.get_proof(conn, batch_id)
        if not proof:
            raise HTTPException(404, "批次不存在")
        return proof
    finally:
        conn.close()
