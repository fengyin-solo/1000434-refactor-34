<template>
  <section class="page" data-module="energy">
    <header class="page-head">
      <div>
        <h2>能耗管理管理</h2>
        <p class="page-desc">维护能耗记录，围绕记录编号、统计日期、用电量、单位电耗做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记能耗记录</button>
        <button class="btn" type="button" @click="exportRows">导出能耗管理清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value ?? '—' }}</strong>
        <span v-if="item.unit" class="stat-unit">{{ item.unit }}</span>
      </article>
    </div>
    <p v-if="statsNote" class="stats-note">{{ statsNote }}</p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <template v-if="allowedActions(row).length">
              <button
                v-for="action in allowedActions(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
            <span v-else class="muted-text">无可执行动作</span>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无能耗管理数据，可先登记能耗记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条能耗管理记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null | string[]>
type StatItem = { label: string; value: number | null; unit?: string }
type StatsPayload = {
  month: string
  month_power: number | null
  water_power: number | null
  chemical_consumption: number | null
  count: number
  note: string
}

const ENDPOINT = '/api/energy'
const columns = ["记录编号", "统计日期", "用电量", "单位电耗", "药剂单耗", "吨水电耗", "记录人员", "记录状态"]
const actions = ["提交填报", "复核确认", "标记争议"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
// 统计卡片与列表同源，由后端 /api/energy/stats 按共用口径返回；空数据时后端给 null。
const stats = ref<StatItem[]>([
  { label: '本月用电量', value: null, unit: 'kWh' },
  { label: '吨水电耗均值', value: null, unit: 'kWh/t' },
  { label: '药剂单耗', value: null, unit: 'kg/t' },
])
const statsNote = ref('')

function allowedActions(row: Row): string[] {
  const list = row.actions
  return Array.isArray(list) ? (list as string[]) : actions
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '能耗记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    // 重复填报、重复复核这类业务拦截后端以 200 + ok:false 返回，
    // 必须把 message 展示出来，不能静默留在原状态。
    const payload = await response.json().catch(() => null) as { ok?: boolean; message?: string } | null
    if (!response.ok || !payload?.ok) {
      throw new Error(payload?.message || '能耗管理动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadStats()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '能耗管理操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('能耗记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '能耗管理列表读取失败'
  }
}

async function loadStats() {
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('统计读取失败')
    }
    const payload = (await response.json()) as StatsPayload
    stats.value = [
      { label: '本月用电量', value: payload.month_power, unit: 'kWh' },
      { label: '吨水电耗均值', value: payload.water_power, unit: 'kWh/t' },
      { label: '药剂单耗', value: payload.chemical_consumption, unit: 'kg/t' },
    ]
    statsNote.value = payload.note
  } catch {
    statsNote.value = '统计卡片暂时读取失败，列表数据不受影响'
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>
