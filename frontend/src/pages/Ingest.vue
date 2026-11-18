<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const result = ref(null)
const busy = ref(false)
const err = ref('')

const batchReport = ref(null)
const batchBusy = ref(false)
const batchErr = ref('')
const batches = ref([])

async function run() {
  busy.value = true
  err.value = ''
  try {
    result.value = await api.ingest()
  } catch (e) {
    err.value = String(e.message || e)
  } finally {
    busy.value = false
  }
}

async function runAtomic() {
  batchBusy.value = true
  batchErr.value = ''
  try {
    const res = await api.runLoadBatch()
    batchReport.value = res.report || null
    if (!res.ok && !batchReport.value) batchErr.value = res.error || '批次失败'
    await loadBatchList()
  } catch (e) {
    batchErr.value = String(e.message || e)
  } finally {
    batchBusy.value = false
  }
}

async function loadBatchList() {
  batches.value = await api.loadBatches()
}

onMounted(() => {
  loadBatchList().catch(() => {})
})
</script>

<template>
  <div class="page-card">
    <h1>装载</h1>
    <p class="lead">从本地夹具跑一批轨迹点装载。乱序重排 / 截止旁路 / 重复隔离由功能题空桩补齐。</p>
    <button class="btn" :disabled="busy" @click="run">{{ busy ? '装载中…' : '跑装载批次' }}</button>
    <p v-if="err" class="muted" style="margin-top:12px">{{ err }}</p>
    <pre v-if="result" style="margin-top:16px;font-family:var(--mono);font-size:12px;white-space:pre-wrap">{{ result }}</pre>

    <h1 style="margin-top:32px">整批原子装载</h1>
    <p class="lead">
      一批覆盖多个运单时整批同成败：任一运单正式写入失败，全部运单的时间线与投影变更一律回滚。
      夹具 load_batch_atomic.json 含「第二单故意失败」场景。
    </p>
    <button class="btn" :disabled="batchBusy" @click="runAtomic">
      {{ batchBusy ? '装载中…' : '跑原子批次（含故意失败）' }}
    </button>
    <p v-if="batchErr" class="muted" style="margin-top:12px">{{ batchErr }}</p>

    <div v-if="batchReport" style="margin-top:16px">
      <p>
        <span class="badge" :class="batchReport.outcome === 'success' ? 'ok' : 'bad'">
          {{ batchReport.outcome === 'success' ? '批次成功' : '批次失败·已整批回滚' }}
        </span>
        <span style="margin-left:10px;font-family:var(--mono);font-size:13px">{{ batchReport.batch_id }}</span>
      </p>
      <p v-if="batchReport.error" class="muted" style="font-family:var(--mono);font-size:12px">
        失败原因：{{ batchReport.error }}
      </p>
      <table class="table" style="margin-top:10px">
        <thead>
          <tr><th>成员运单</th><th>计划点数</th><th>写入点数</th><th>正式线现存本批点</th></tr>
        </thead>
        <tbody>
          <tr v-for="m in batchReport.members" :key="m.waybill_id">
            <td>{{ m.waybill_id }}</td>
            <td>{{ m.planned_points }}</td>
            <td>{{ m.written_points }}</td>
            <td>{{ m.formal_points_now }}</td>
          </tr>
        </tbody>
      </table>
      <p class="muted" style="font-size:12px;margin-top:8px">
        互证：{{ batchReport.consistent ? '成员表与正式线一致 ✓' : '成员表与正式线不一致 ✗' }}
      </p>
    </div>

    <template v-if="batches.length">
      <h1 style="margin-top:32px">批次边界</h1>
      <table class="table">
        <thead>
          <tr><th>批次</th><th>成败</th><th>成员</th><th>写入合计</th><th>时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="b in batches" :key="b.batch_id">
            <td>{{ b.batch_id }}</td>
            <td>
              <span class="badge" :class="b.outcome === 'success' ? 'ok' : 'bad'">
                {{ b.outcome === 'success' ? '成功' : '失败' }}
              </span>
            </td>
            <td>
              <span class="member-chips">
                <span v-for="m in b.members" :key="m.waybill_id">
                  {{ m.waybill_id }} · {{ m.written_points }}/{{ m.planned_points }}
                </span>
              </span>
            </td>
            <td>{{ b.written_total }}</td>
            <td>{{ b.created_at }}</td>
          </tr>
        </tbody>
      </table>
    </template>
  </div>
</template>
