import request from '@/utils/request';

export function fetchTasks(params, options = {}) {
  return request.get('/api/tasks', { params, ...options }).then((res) => res.data);
}

export function fetchTaskDetail(taskId) {
  return request.get(`/api/tasks/${taskId}`).then((res) => res.data);
}

export function retryTask(taskId, priority = 0) {
  return request.post(`/api/tasks/${taskId}/retry`, null, {
    params: { priority },
  });
}

export function pauseTask(taskId) {
  return request.post(`/api/tasks/${taskId}/pause`);
}

export function resumeTask(taskId) {
  return request.post(`/api/tasks/${taskId}/resume`);
}

export function retryFailedTasks(limit = 20, sourceName = '', mediaGroupId = '', batchId = '') {
  return request.post('/api/tasks/retry-failed', null, {
    params: {
      limit,
      ...(sourceName ? { source_name: sourceName } : {}),
      ...(mediaGroupId ? { media_group_id: mediaGroupId } : {}),
      ...(batchId ? { batch_id: batchId } : {}),
    },
  });
}

export function cancelTask(taskId) {
  return request.post(`/api/tasks/${taskId}/cancel`);
}
