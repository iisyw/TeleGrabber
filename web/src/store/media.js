import { defineStore } from 'pinia';
import {
  fetchMedia,
  fetchSources,
  fetchStats,
  deleteMediaById,
  deleteMediaGroup,
} from '@/api/media';
import { updateSourceMeta } from '@/api/sources';

function mediaQuery(state) {
  const params = {
    limit: state.limit,
    sort: state.sortBy,
  };
  if (state.cursorId !== null) {
    params.cursor_id = state.cursorId;
    if (state.cursorTime) params.cursor_time = state.cursorTime;
  }
  if (state.currentSearch) params.search = state.currentSearch;
  if (state.mediaType) params.media_type = state.mediaType;
  if (state.favorite) params.favorite = true;
  if (state.tag) params.tag = state.tag;
  if (state.dateFrom) params.date_from = state.dateFrom;
  if (state.dateTo) params.date_to = state.dateTo;
  if (state.currentSourceName) params.source_name = state.currentSourceName;
  if (state.currentSourceType) params.source_type = state.currentSourceType;
  return params;
}

export const useMediaStore = defineStore('media', {
  state: () => ({
    sources: [],
    sourceCounts: {},
    currentSourceName: '',
    currentSourceType: '',
    currentSearch: '',
    mediaType: '',
    dateFrom: '',
    dateTo: '',
    favorite: false,
    tag: '',
    sortBy: 'message_time',
    mediaList: [],
    cursorTime: '',
    cursorId: null,
    limit: 30,
    isLoading: false,
    isLastPage: false,
    stats: null,
    error: '',
    _seq: 0,
  }),

  actions: {
    applySourceCounts(payload) {
      const counts = {};
      const sources = (payload && payload.sources) || [];
      sources.forEach((s) => {
        counts[s.source_name] = {
          media: s.media_count || 0,
          messages: s.message_count || 0,
        };
      });
      const totals = (payload && payload.totals) || {};
      counts[''] = {
        media: totals.media_count || 0,
        messages: totals.message_count || 0,
      };
      this.sources = sources;
      this.sourceCounts = counts;
    },

    async loadSources() {
      try {
        const payload = await fetchSources(this.currentSourceType);
        this.applySourceCounts(payload);
      } catch {
        // 错误提示由 request.js 拦截器统一负责
      }
    },

    async loadStats() {
      const params = {};
      if (this.currentSearch) params.search = this.currentSearch;
      if (this.mediaType) params.media_type = this.mediaType;
      if (this.favorite) params.favorite = true;
      if (this.tag) params.tag = this.tag;
      if (this.dateFrom) params.date_from = this.dateFrom;
      if (this.dateTo) params.date_to = this.dateTo;
      if (this.currentSourceName) params.source_name = this.currentSourceName;
      if (this.currentSourceType) params.source_type = this.currentSourceType;
      try {
        this.stats = await fetchStats(params);
      } catch {
        // 错误提示由 request.js 拦截器统一负责
      }
    },

    /**
     * 加载媒体列表。reset=true 时开启新一轮请求，旧的请求结果会被丢弃，
     * 避免切换来源/搜索时旧响应覆盖新状态。
     */
    async loadMedia(reset = false) {
      if (!reset && (this.isLoading || this.isLastPage)) return false;

      const seq = ++this._seq;
      if (reset) {
        this.mediaList = [];
        this.cursorTime = '';
        this.cursorId = null;
        this.isLastPage = false;
        this.error = '';
      }
      this.isLoading = true;

      try {
        const data = (await fetchMedia(mediaQuery(this))) || [];
        if (seq !== this._seq) return false;

        if (data.length < this.limit) this.isLastPage = true;
        const last = data[data.length - 1];
        if (last) {
          this.cursorTime = last.message_time || last.datetime || '';
          this.cursorId = last.id;
        }
        this.mediaList = reset ? data : this.mediaList.concat(data);
        return true;
      } catch (error) {
        if (seq === this._seq) this.error = '加载失败';
        return false;
      } finally {
        if (seq === this._seq) this.isLoading = false;
      }
    },

    loadMore() {
      return this.loadMedia(false);
    },

    async refresh() {
      await Promise.allSettled([
        this.loadSources(),
        this.loadStats(),
        this.loadMedia(true),
      ]);
    },

    async selectSource(sourceName) {
      if (this.currentSourceName === sourceName) return;
      this.currentSourceName = sourceName;
      await Promise.allSettled([this.loadStats(), this.loadMedia(true)]);
    },

    async selectSourceType(type) {
      if (this.currentSourceType === type) return;
      this.currentSourceType = type;
      this.currentSourceName = '';
      await this.loadSources();
      await Promise.allSettled([this.loadStats(), this.loadMedia(true)]);
    },

    async setSearch(value) {
      const next = (value || '').trim();
      if (this.currentSearch === next) return;
      this.currentSearch = next;
      await Promise.allSettled([this.loadStats(), this.loadMedia(true)]);
    },

    async setSort(sort) {
      if (this.sortBy === sort) return;
      this.sortBy = sort;
      await this.loadMedia(true);
    },

    async setFilters(filters) {
      const nextType = filters.media_type || '';
      const nextFrom = filters.date_from || '';
      const nextTo = filters.date_to || '';
      const nextFavorite = Boolean(filters.favorite);
      const nextTag = (filters.tag || '').trim();
      if (
        this.mediaType === nextType && this.dateFrom === nextFrom &&
        this.dateTo === nextTo && this.favorite === nextFavorite && this.tag === nextTag
      ) return;
      this.mediaType = nextType;
      this.dateFrom = nextFrom;
      this.dateTo = nextTo;
      this.favorite = nextFavorite;
      this.tag = nextTag;
      await Promise.allSettled([this.loadStats(), this.loadMedia(true)]);
    },

    async deleteItem(id) {
      await deleteMediaById(id);
      this.mediaList = this.mediaList.filter((item) => String(item.id) !== String(id));
      await Promise.allSettled([this.loadStats(), this.loadSources()]);
    },

    async deleteGroup(groupId) {
      await deleteMediaGroup(groupId);
      this.mediaList = this.mediaList.filter((item) => item.media_group_id !== groupId);
      await Promise.allSettled([this.loadStats(), this.loadSources()]);
    },

    async setSourceMeta(sourceName, patch) {
      await updateSourceMeta({ source_name: sourceName, ...patch });
      const target = this.sources.find((item) => item.source_name === sourceName);
      if (target) Object.assign(target, patch);
      this.sources = [...this.sources].sort(
        (a, b) => Number(b.pinned || 0) - Number(a.pinned || 0),
      );
    },
  },
});
