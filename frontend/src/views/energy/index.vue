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
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>
    <p v-if="statsMessage" class="stats-note">{{ statsMessage }}</p>

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
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
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

type Row = Record<string, string | number | null>
type Card = { label: string; value: number }

const ENDPOINT = '/api/energy'
// 列顺序以后端 /api/energy 返回口径为准：原始量在前，派生指标由后端统一现算。
const columns = ["记录编号", "统计日期", "用电量", "处理水量", "单位电耗", "药剂用量", "药剂单耗", "吨水电耗", "记录人员", "记录状态"]
const actions = ["提交填报", "复核确认", "标记争议"]
const statuses = ["待填报", "已填报", "已复核", "有争议"]
const fallbackStats: Card[] = [{"label": "本月用电量", "value": 0}, {"label": "吨水电耗均值", "value": 0}, {"label": "药剂单耗", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const stats = ref<Card[]>(fallbackStats)
const statsMessage = ref('')
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

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
    const payload = (await response.json().catch(() => null)) as
      | { ok?: boolean; message?: string }
      | null
    // 重复复核、未填报先复核等被后端拦下时，展示后端给出的口径说明。
    if (!response.ok || payload?.ok === false) {
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
  // 卡片数字来自后端 stats 口径，和表格、导出共用同一套派生指标，避免页面数字不一致。
  try {
    const response = await request(`${ENDPOINT}/stats`)
    if (!response.ok) {
      throw new Error('统计卡片读取失败')
    }
    const payload = await response.json()
    stats.value = payload.cards ?? fallbackStats
    statsMessage.value = payload.message ?? ''
  } catch (error) {
    stats.value = fallbackStats
    statsMessage.value = error instanceof Error ? error.message : '统计卡片读取失败'
  }
}

onMounted(() => {
  void reload()
  void loadStats()
})
</script>
