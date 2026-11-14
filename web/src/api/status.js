import request from '@/utils/request';

export function fetchSystemStatus() {
  return request.get('/api/status').then((res) => res.data);
}

export function runHealthCheck() {
  return request.post('/api/status/health').then((res) => res.data);
}

export function fetchHealthIssues(params) {
  return request.get('/api/status/health/issues', { params }).then((res) => res.data);
}

export function repairHealthIssues(action = 'all') {
  return request.post('/api/status/health/repair', { action }).then((res) => res.data);
}

export function cleanMissingHealthFiles(ids) {
  return request.post('/api/status/health/clean-missing', { ids }).then((res) => res.data);
}
