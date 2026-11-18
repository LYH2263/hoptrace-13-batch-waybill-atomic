<script setup>
import { onMounted, ref } from 'vue'
import { api } from '../api.js'

const rows = ref([])
const batches = ref([])
onMounted(async () => {
  rows.value = await api.proofs()
  batches.value = await api.loadBatches()
})
</script>

<template>
  <div class="page-card">
    <h1>证明</h1>
    <p class="lead">状态投影证明列表，与时间线末 hop 同源。</p>
    <table class="table">
      <thead>
        <tr><th>id</th><th>运单</th><th>末 hop</th><th>映射码</th><th>投影</th><th>时间</th></tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.id">
          <td>{{ r.id }}</td>
          <td>{{ r.waybill_id }}</td>
          <td>{{ r.last_hop_id }}</td>
          <td>{{ r.mapped_code }}</td>
          <td>{{ r.proj_value }}</td>
          <td>{{ r.created_at }}</td>
        </tr>
        <tr v-if="!rows.length"><td colspan="6" class="muted">暂无证明</td></tr>
      </tbody>
    </table>

    <h1 style="margin-top:32px">批原子证明</h1>
    <p class="lead">整批运单级原子边界：批次、成员运单、各单写入点数、总成败；与装载报告同源。</p>
    <table class="table">
      <thead>
        <tr><th>批次</th><th>总成败</th><th>成员运单（写入/计划）</th><th>正式线互证</th><th>时间</th></tr>
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
          <td>{{ b.consistent ? '一致 ✓' : '不一致 ✗' }}</td>
          <td>{{ b.created_at }}</td>
        </tr>
        <tr v-if="!batches.length"><td colspan="5" class="muted">暂无批次</td></tr>
      </tbody>
    </table>
  </div>
</template>
