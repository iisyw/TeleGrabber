import request from '@/utils/request';

export function fetchStorageSummary() {
  return request.get('/api/storage/summary').then((res) => res.data);
}

export function fetchDuplicates(limit = 50) {
  return request.get('/api/duplicates', { params: { limit } }).then((res) => res.data);
}
