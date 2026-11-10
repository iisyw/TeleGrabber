import axios from 'axios';
import { ElMessage } from 'element-plus';

/**
 * 统一网络层，结构对齐 DefaultFramework/web/src/utils/request.js。
 * 本工具为个人单机使用，不启用内置登录鉴权。
 */
export function getBaseURL() {
  let url = '';
  if (
    typeof window !== 'undefined' &&
    window.__APP_CONFIG__ &&
    typeof window.__APP_CONFIG__.apiUrl === 'string'
  ) {
    url = window.__APP_CONFIG__.apiUrl;
  } else if (import.meta.env.VITE_API_URL) {
    url = import.meta.env.VITE_API_URL;
  }
  url = url.trim();
  if (url === '/' || url === '') return '';
  return url.replace(/\/+$/, '');
}

const service = axios.create({
  baseURL: getBaseURL(),
  timeout: 60000,
});

service.interceptors.response.use(
  (response) => {
    const res = response.data;
    if (!res || typeof res !== 'object' || typeof res.code !== 'number') {
      const error = new Error('接口响应格式不正确');
      if (!response.config?.silent && !response.config?.skipErrorToast) {
        ElMessage({ message: error.message, type: 'error', duration: 3000, grouping: true });
      }
      return Promise.reject(error);
    }

    if (res.code !== 10000) {
      const errorMsg = res.msg || '系统业务异常';
      if (!response.config?.silent && !response.config?.skipErrorToast) {
        ElMessage({ message: errorMsg, type: 'error', duration: 3000, grouping: true });
      }
      const error = new Error(errorMsg);
      error.response = { data: res };
      error.code = res.code;
      error.isBusinessError = true;
      error.toastShown = !response.config?.silent && !response.config?.skipErrorToast;
      return Promise.reject(error);
    }

    return res;
  },
  (error) => {
    let message = '网络请求失败';
    if (error.response) {
      const data = error.response.data;
      if (typeof data === 'object' && data !== null && typeof data.msg === 'string' && data.msg.trim()) {
        message = data.msg.trim();
      } else {
        message = getHTTPErrorMessage(error.response.status);
      }
    } else if (error.request) {
      message = '服务器无响应，请检查网络或后端服务状态';
    } else if (error.message) {
      message = error.message;
    }

    if (!error.config?.silent && !error.config?.skipErrorToast) {
      ElMessage({ message, type: 'error', duration: 3000, grouping: true });
      error.toastShown = true;
    }

    return Promise.reject(error);
  },
);

function getHTTPErrorMessage(status) {
  switch (status) {
    case 400:
      return '请求参数错误 (400)';
    case 403:
      return '请求被拒绝 (403)';
    case 404:
      return '请求的接口资源不存在 (404)';
    case 405:
      return '请求方法不受支持 (405)';
    case 408:
      return '请求响应超时 (408)';
    case 500:
      return '服务器内部错误 (500)';
    case 502:
      return '网关错误：后端服务未启动或不可达 (502)';
    case 503:
      return '服务暂不可用，服务器过载或维护 (503)';
    case 504:
      return '网关响应超时 (504)';
    default:
      return `网络请求失败 (${status})`;
  }
}

export default service;
