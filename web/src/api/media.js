import request from '@/utils/request';

export function fetchSources(sourceType) {
  return request
    .get('/api/sources', {
      params: sourceType ? { source_type: sourceType } : {},
    })
    .then((res) => res.data);
}

export function fetchStats(params) {
  return request.get('/api/stats', { params }).then((res) => res.data);
}

export function fetchMedia(params) {
  return request.get('/api/media', { params }).then((res) => res.data);
}

export function deleteMediaById(id) {
  return request.delete(`/api/media/${id}`);
}

export function deleteMediaGroup(groupId) {
  return request.delete(`/api/media_group/${encodeURIComponent(groupId)}`);
}

export function updateMediaMeta(mediaId, payload) {
  return request.patch(`/api/media/${mediaId}/meta`, payload);
}
