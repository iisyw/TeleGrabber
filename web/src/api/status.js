import request from '@/utils/request';

export function fetchSystemStatus() {
  return request.get('/api/status').then((res) => res.data);
}

export function runHealthCheck() {
  return request.post('/api/status/health').then((res) => res.data);
}
