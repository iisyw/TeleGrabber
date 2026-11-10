import request from '@/utils/request';

export function updateSourceMeta(payload) {
  return request.patch('/api/sources/meta', payload);
}
